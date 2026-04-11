"""Tests pour le cache de statistiques pré-calculées.

Couvre :
- build_filter_key (clé canonique JSON)
- compute_and_store (calcul + persistance)
- get_cached_or_compute (lecture cache / recalcul)
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from pyvolley.database.models import Base, MatchDB, StatsCacheDB
from pyvolley.database.repositories import StatsCacheRepository
from pyvolley.database.stats_service import StatsAmusantesService, StatsFilters


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    Sess = sessionmaker(bind=engine)
    s = Sess()
    yield s
    s.rollback()
    s.close()


# ---------------------------------------------------------------------------
# Helper – build a played match with no competition / team FK
# ---------------------------------------------------------------------------


def _add_played_match(session: Session, code: str = "TEST-001") -> MatchDB:
    m = MatchDB(
        code_match=code,
        match_joue=True,
        sets_equipe_a=3,
        sets_equipe_b=1,
        score_sets="3/1",
    )
    session.add(m)
    session.flush()
    return m


# ---------------------------------------------------------------------------
# Tests — build_filter_key
# ---------------------------------------------------------------------------


class TestBuildFilterKey:
    def test_empty_filters_is_valid_json(self):
        key = StatsAmusantesService.build_filter_key(StatsFilters())
        parsed = json.loads(key)
        assert parsed["saison_id"] is None
        assert parsed["genre"] is None

    def test_all_filters_present(self):
        f = StatsFilters(
            saison_id=7,
            genre="M",
            categorie="Senior",
            niveau_min="REGIONAL",
            niveau_max="NATIONAL",
            departement="75",
        )
        key = StatsAmusantesService.build_filter_key(f)
        parsed = json.loads(key)
        assert parsed["saison_id"] == 7
        assert parsed["genre"] == "M"
        assert parsed["departement"] == "75"

    def test_key_is_stable(self):
        f = StatsFilters(saison_id=1, genre="F")
        assert (
            StatsAmusantesService.build_filter_key(f)
            == StatsAmusantesService.build_filter_key(f)
        )

    def test_different_filters_different_keys(self):
        k1 = StatsAmusantesService.build_filter_key(StatsFilters(saison_id=1))
        k2 = StatsAmusantesService.build_filter_key(StatsFilters(saison_id=2))
        assert k1 != k2


# ---------------------------------------------------------------------------
# Tests — compute_and_store
# ---------------------------------------------------------------------------


class TestComputeAndStore:
    def test_stores_entry_in_db(self, session: Session):
        _add_played_match(session)
        session.commit()

        service = StatsAmusantesService(session)
        filters = StatsFilters()
        result = service.compute_and_store(filters)

        # Result contains the expected keys
        assert "top_matchs" in result
        assert "top_equipes" in result

        # Verify persistence
        repo = StatsCacheRepository(session)
        key = service.build_filter_key(filters)
        entry = repo.get_by_filter_key(key)
        assert entry is not None
        assert entry.match_count == 1

    def test_updates_existing_entry(self, session: Session):
        _add_played_match(session, "M-001")
        session.commit()

        service = StatsAmusantesService(session)
        filters = StatsFilters()
        service.compute_and_store(filters)

        # Add another match and recompute
        _add_played_match(session, "M-002")
        session.commit()

        service2 = StatsAmusantesService(session)
        service2.compute_and_store(filters)

        repo = StatsCacheRepository(session)
        entries = repo.list_all()
        # Only one entry for the same filter key
        assert sum(1 for e in entries if e.filter_key == service.build_filter_key(filters)) == 1
        entry = repo.get_by_filter_key(service.build_filter_key(filters))
        assert entry is not None
        assert entry.match_count == 2


# ---------------------------------------------------------------------------
# Tests — get_cached_or_compute
# ---------------------------------------------------------------------------


class TestGetCachedOrCompute:
    def test_returns_fresh_data_when_no_cache(self, session: Session):
        _add_played_match(session)
        session.commit()

        service = StatsAmusantesService(session)
        result, from_cache = service.get_cached_or_compute(StatsFilters())
        assert from_cache is False
        assert "top_matchs" in result

    def test_returns_cached_data_when_match_count_unchanged(self, session: Session):
        _add_played_match(session)
        session.commit()

        service = StatsAmusantesService(session)
        filters = StatsFilters()

        # Pre-populate cache
        service.compute_and_store(filters)

        # Next call should read from cache
        service2 = StatsAmusantesService(session)
        result, from_cache = service2.get_cached_or_compute(filters)
        assert from_cache is True
        assert "top_matchs" in result

    def test_bypasses_cache_when_match_count_changed(self, session: Session):
        _add_played_match(session, "OLD-001")
        session.commit()

        service = StatsAmusantesService(session)
        filters = StatsFilters()
        service.compute_and_store(filters)

        # Add a new match — cache becomes stale
        _add_played_match(session, "NEW-002")
        session.commit()

        service2 = StatsAmusantesService(session)
        result, from_cache = service2.get_cached_or_compute(filters)
        assert from_cache is False
        assert "top_matchs" in result

    def test_bypasses_cache_when_match_data_changed_but_count_stable(self, session: Session):
        _add_played_match(session, "UNCHANGED-COUNT-001")
        session.commit()

        service = StatsAmusantesService(session)
        filters = StatsFilters()
        service.compute_and_store(filters)

        match = session.scalar(
            select(MatchDB).where(MatchDB.code_match == "UNCHANGED-COUNT-001")
        )
        assert match is not None
        match.sets_equipe_b = 2
        match.score_sets = "3/2"
        # Force une valeur clairement postérieure au cache pour éviter toute ambiguïté temporelle.
        assert match.updated_at is not None
        match.updated_at = match.updated_at + timedelta(minutes=10)
        session.commit()

        service2 = StatsAmusantesService(session)
        result, from_cache = service2.get_cached_or_compute(filters)
        assert from_cache is False
        assert "top_matchs" in result
