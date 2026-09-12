"""Tests for scraping and ingestion pipeline optimizations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from pyvolley.core.geocoding import (
    GeocodingCache,
    GeocodingResult,
    geocode_addresses_batch,
)
from pyvolley.scrapers.ffvb.competition_info import (
    CompetitionIndex,
    CompetitionMeta,
    build_competition_index,
    clear_competition_cache,
)


def test_geocode_addresses_batch_with_cache(tmp_path: Path, monkeypatch):
    """Vérifie que geocode_addresses_batch consulte et peuple le cache."""
    cache_file = tmp_path / "test_geo_cache.json"
    cache = GeocodingCache(cache_file)
    monkeypatch.setattr("pyvolley.core.geocoding.get_geocoding_cache", lambda: cache)

    # Pré-remplir le cache
    cache.set("1 RUE DE LA PAIX PARIS", "75001", GeocodingResult(
        latitude=48.868, longitude=2.329, label="1 Rue de la Paix", score=0.95, match_type="housenumber"
    ))

    items = [
        {"id": "s1", "adresse": "1 rue de la paix", "ville": "75001 Paris", "nom": "Salle A"},
        ("2 rue de paris", "75002 Paris", "Salle B"),
    ]

    mock_csv_response = (
        "latitude,longitude,result_score\n"
        "48.867,2.340,0.92\n"
    )

    with patch("pyvolley.core.geocoding.urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_csv_response.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        results = geocode_addresses_batch(items, use_cache=True)

    assert "s1" in results
    assert results["s1"].latitude == 48.868
    # Vérifier que le cache a été sauvegardé sur disque
    assert cache_file.exists()


def test_competition_index_disk_cache(tmp_path: Path, monkeypatch):
    """Vérifie que l'index de compétition est persisté sur disque et rechargé."""
    monkeypatch.setattr("pyvolley.core.config.settings.data_dir", tmp_path)
    clear_competition_cache(clear_disk=True)

    client = MagicMock()
    mock_meta = CompetitionMeta(
        poule_code="EMA",
        nom_complet="ELITE MASCULINE - POULE A",
        genre="MASCULIN",
        niveau="ELITE",
    )
    mock_index = CompetitionIndex(
        entite_code="ABCCS",
        entite_nom="National",
        entite_type="nationale",
        saison="2022/2023",
        competitions={"EMA": mock_meta},
        groupes={"ELITE": ["EMA"]},
    )

    with patch(
        "pyvolley.scrapers.ffvb.competition_info.scrape_competition_index",
        return_value=mock_index,
    ) as mock_scrape:
        # Premier appel : scrape + sauvegarde disque
        idx1 = build_competition_index(client, "http://base", "ABCCS", "2022/2023")
        assert idx1.get("EMA").niveau == "ELITE"
        assert mock_scrape.call_count == 1

        # Vider uniquement la mémoire pour forcer la lecture disque
        clear_competition_cache(clear_disk=False)

        # Deuxième appel : rechargement disque sans re-scrape
        idx2 = build_competition_index(client, "http://base", "ABCCS", "2022/2023")
        assert idx2.get("EMA").niveau == "ELITE"
        assert mock_scrape.call_count == 1  # Pas de second scrape !


def test_enrich_from_pdf_deferred_player_stats(test_session, full_match):
    """Vérifie que defer_player_stats=True diffère les stats et que compute_player_stats_for_matches les calcule en lot."""
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import MatchDB, JoueurMatchStatsDB
    from sqlalchemy import select

    service = MatchImportService(test_session)
    # Créer un match initial
    match_initial = MatchDB(
        code_match="TST-DEF-001",
        parsing_status="downloaded",
        match_joue=True,
    )
    test_session.add(match_initial)
    test_session.flush()

    # Enrichir avec defer_player_stats=True
    was_enriched = service.enrich_from_pdf(
        match_initial, full_match, force=True, defer_rollups=True, defer_player_stats=True,
    )
    assert was_enriched is True
    test_session.flush()

    # Les stats joueurs détaillées ne doivent pas être calculées en ligne
    stats_count = test_session.scalar(
        select(JoueurMatchStatsDB).where(JoueurMatchStatsDB.match_id == match_initial.id)
    )
    assert stats_count is None

    # Maintenant calculer en lot via compute_player_stats_for_matches
    computed_rows = service.compute_player_stats_for_matches([match_initial.id])
    test_session.flush()
    assert computed_rows > 0

    all_stats = list(test_session.scalars(
        select(JoueurMatchStatsDB).where(JoueurMatchStatsDB.match_id == match_initial.id)
    ).all())
    assert len(all_stats) == computed_rows


def test_fast_header_imports_hoisted():
    """Vérifie que les fonctions de normalisation du header rapide sont importées au niveau module."""
    import pyvolley.parsers.extractors.fast.header as fast_header

    assert hasattr(fast_header, "normalize_genre")
    assert hasattr(fast_header, "normalize_categorie")
    assert hasattr(fast_header, "extract_division_number")
    assert hasattr(fast_header, "classify_level")


def test_sqlite_bulk_mode(test_session):
    """Vérifie que sqlite_bulk_mode configure et restaure proprement les pragmas SQLite."""
    from pyvolley.database.connection import sqlite_bulk_mode
    from pyvolley.core.config import settings
    from sqlalchemy import text

    if not settings.is_sqlite:
        return

    with sqlite_bulk_mode(test_session):
        val = test_session.execute(text("PRAGMA wal_autocheckpoint")).scalar()
        assert val == 0

    val_restored = test_session.execute(text("PRAGMA wal_autocheckpoint")).scalar()
    assert val_restored == 1000

    # Test avec transaction active (par ex. après un flush)
    from pyvolley.database.models import ImportLogDB
    log = ImportLogDB(operation="test_bulk", source="test", total_attempted=1, status="running")
    test_session.add(log)
    test_session.flush()
    assert test_session.in_transaction()

    with sqlite_bulk_mode(test_session):
        val_in_tx = test_session.execute(text("PRAGMA wal_autocheckpoint")).scalar()
        assert val_in_tx == 0
    test_session.rollback()


def test_clear_caches_clear_all_flag(test_session):
    """Vérifie que clear_caches(clear_all=False) préserve les entités en cache."""
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import ClubDB

    service = MatchImportService(test_session)
    service._club_cache["TEST_CLUB"] = ClubDB(nom="TEST_CLUB")
    service._participation_seen.add((1, 2))

    # Purge partielle (commit batch normal)
    service.clear_caches(clear_all=False)
    assert "TEST_CLUB" in service._club_cache
    assert len(service._participation_seen) == 0

    # Purge totale (rollback)
    service.clear_caches(clear_all=True)
    assert len(service._club_cache) == 0


