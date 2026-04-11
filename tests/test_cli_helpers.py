"""Tests de régression pour l'association match ↔ PDF dans le CLI."""

import importlib
import os
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from pyvolley.cli.helpers import (
    build_pdf_index,
    find_pdf_for_match,
    expand_saison_inputs,
    format_saison_short,
    saisons_to_db_codes,
)
from pyvolley.shared.pdf_storage import build_pdf_storage_path
from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo


def _make_match(code_match: str, saison_code: str | None, source_pdf: str | None = None):
    saison = SimpleNamespace(code=saison_code) if saison_code else None
    return SimpleNamespace(code_match=code_match, source_pdf=source_pdf, saison=saison)


def test_find_pdf_for_match_prefers_same_season(tmp_path):
    pdf_base = tmp_path / "pdfs"
    season_a = pdf_base / "2023-2024"
    season_b = pdf_base / "2024-2025"
    season_a.mkdir(parents=True)
    season_b.mkdir(parents=True)

    pdf_a = season_a / "EMA001.pdf"
    pdf_b = season_b / "EMA001.pdf"
    pdf_a.write_bytes(b"%PDF-1.4\n")
    pdf_b.write_bytes(b"%PDF-1.4\n")

    index = build_pdf_index(pdf_base)
    match = _make_match("EMA001", "2024-2025")

    found = find_pdf_for_match(match, pdf_base, index)

    assert found == pdf_b


def test_find_pdf_for_match_uses_legacy_unscoped_fallback(tmp_path):
    pdf_base = tmp_path / "pdfs"
    pdf_base.mkdir(parents=True)

    legacy_pdf = pdf_base / "LIRA_EMA002.pdf"
    legacy_pdf.write_bytes(b"%PDF-1.4\n")

    index = build_pdf_index(pdf_base)
    match = _make_match("EMA002", "2025-2026")

    found = find_pdf_for_match(match, pdf_base, index)

    assert found == legacy_pdf


def test_find_pdf_for_match_supports_structured_storage_format(tmp_path):
    pdf_base = tmp_path / "pdfs"
    structured_pdf = build_pdf_storage_path(
        pdf_base,
        saison_code="2025-2026",
        entite_code="LIRA",
        poule_code="EMA",
        match_code="EMA007",
        journee="12",
        unique_hint=123,
    )
    structured_pdf.parent.mkdir(parents=True, exist_ok=True)
    structured_pdf.write_bytes(b"%PDF-1.4\n")

    index = build_pdf_index(pdf_base)
    match = _make_match("EMA007", "2025-2026")

    found = find_pdf_for_match(match, pdf_base, index)

    assert found == structured_pdf


def test_expand_saison_inputs_single_short_format():
    assert expand_saison_inputs(["23/24"]) == ["2023/2024"]


def test_expand_saison_inputs_range_short_format():
    assert expand_saison_inputs(["22/25"]) == [
        "2022/2023",
        "2023/2024",
        "2024/2025",
    ]


def test_saisons_to_db_codes_from_range():
    assert saisons_to_db_codes(["22/25"]) == [
        "2022-2023",
        "2023-2024",
        "2024-2025",
    ]


def test_format_saison_short_accepts_legacy_long_code():
    assert format_saison_short("2024-2025") == "24/25"


def test_expand_saison_inputs_rejects_invalid_token():
    with pytest.raises(ValueError):
        expand_saison_inputs(["2024"])


def test_pdf_redownload_reason_invalid_local_pdf(tmp_path):
    cli_main = importlib.import_module("pyvolley.cli.main")

    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"not-a-pdf")

    match = SimpleNamespace(date_match=date(2025, 2, 10))
    reason = cli_main._get_pdf_redownload_reason(
        match,
        bad_pdf,
        today=date(2025, 2, 12),
    )

    assert reason == "invalid-local-pdf"


def test_pdf_redownload_reason_downloaded_before_match_date(tmp_path):
    cli_main = importlib.import_module("pyvolley.cli.main")

    old_pdf = tmp_path / "old.pdf"
    old_pdf.write_bytes(b"%PDF-1.4\n" + (b"A" * 1100) + b"\n%%EOF\n")

    downloaded_before = date(2025, 2, 10)
    match_date = date(2025, 2, 12)
    ts = datetime.combine(downloaded_before, datetime.min.time()).timestamp()
    os.utime(old_pdf, (ts, ts))

    match = SimpleNamespace(date_match=match_date)
    reason = cli_main._get_pdf_redownload_reason(
        match,
        old_pdf,
        today=date(2025, 2, 13),
    )

    assert reason == "downloaded-before-match-date"


def test_pdf_redownload_reason_none_for_pdf_downloaded_on_match_day(tmp_path):
    cli_main = importlib.import_module("pyvolley.cli.main")

    fresh_pdf = tmp_path / "fresh.pdf"
    fresh_pdf.write_bytes(b"%PDF-1.4\n" + (b"B" * 1100) + b"\n%%EOF\n")

    downloaded_on = date(2025, 2, 12)
    match_date = date(2025, 2, 12)
    ts = datetime.combine(downloaded_on, datetime.min.time()).timestamp()
    os.utime(fresh_pdf, (ts, ts))

    match = SimpleNamespace(date_match=match_date)
    reason = cli_main._get_pdf_redownload_reason(
        match,
        fresh_pdf,
        today=date(2025, 2, 13),
    )

    assert reason is None


def test_import_only_download_passes_entity_filter(monkeypatch):
    cli_main = importlib.import_module("pyvolley.cli.main")

    class DummyScraper:
        pass

    import pyvolley.scrapers.ffvb as ffvb_module
    import pyvolley.database.connection as db_connection

    monkeypatch.setattr(ffvb_module, "FFVBScraper", lambda: DummyScraper())
    monkeypatch.setattr(cli_main, "resolve_entities", lambda *args, **kwargs: ["ABCCS"])
    monkeypatch.setattr(cli_main, "resolve_saisons", lambda *args, **kwargs: ["2025/2026"])
    monkeypatch.setattr(db_connection, "init_db", lambda: None)

    captured: dict[str, object] = {}

    def fake_import_download(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli_main, "_import_download", fake_import_download)

    runner = CliRunner()
    result = runner.invoke(cli_main.app, ["import", "--only", "download", "-e", "ABCCS"])

    assert result.exit_code == 0, result.stdout
    assert captured.get("entity") == ["ABCCS"]


def test_list_matches_uses_export_match_info_fields(monkeypatch):
    cli_main = importlib.import_module("pyvolley.cli.main")

    class DummyScraper:
        def scrape_entity(self, entity, saison, poule=None):
            return [
                ExportMatchInfo(
                    code_match="EMA001",
                    entite_code=entity,
                    saison=saison,
                    poule_code="EMA",
                    date_match=date(2025, 1, 1),
                    score_sets="3/1",
                    equipe_a_nom="Equipe A",
                    equipe_b_nom="Equipe B",
                    feuille_match_url="https://example.test/match.pdf",
                )
            ]

    import pyvolley.scrapers.ffvb as ffvb_module

    monkeypatch.setattr(ffvb_module, "FFVBScraper", lambda: DummyScraper())

    runner = CliRunner()
    result = runner.invoke(
        cli_main.app,
        ["list", "matches", "ABCCS", "--saison", "24/25", "--limit", "1"],
    )

    assert result.exit_code == 0, result.stdout
    assert "EMA001" in result.stdout
    assert "3/1" in result.stdout


def test_compute_player_stats_filters_on_entity(monkeypatch, test_session):
    cli_main = importlib.import_module("pyvolley.cli.main")

    from pyvolley.database.models import EntiteFFVBDB, SaisonDB, CompetitionDB, MatchDB

    saison = SaisonDB(code="2025-2026", nom="Saison 2025-2026")
    entite_a = EntiteFFVBDB(code="ABCCS", nom="Entité A", type="ligue")
    entite_b = EntiteFFVBDB(code="LIRA", nom="Entité B", type="ligue")
    test_session.add_all([saison, entite_a, entite_b])
    test_session.flush()

    comp_a = CompetitionDB(nom="Comp A", saison_id=saison.id, entite_id=entite_a.id)
    comp_b = CompetitionDB(nom="Comp B", saison_id=saison.id, entite_id=entite_b.id)
    test_session.add_all([comp_a, comp_b])
    test_session.flush()

    test_session.add_all(
        [
            MatchDB(
                code_match="M-A",
                has_details=True,
                match_joue=True,
                parsing_status="parsed",
                competition_id=comp_a.id,
                saison_id=saison.id,
            ),
            MatchDB(
                code_match="M-B",
                has_details=True,
                match_joue=True,
                parsing_status="parsed",
                competition_id=comp_b.id,
                saison_id=saison.id,
            ),
        ]
    )
    test_session.commit()

    import pyvolley.database.connection as db_connection
    import pyvolley.database.player_stats_service as player_stats_service
    import pyvolley.database.repositories as repositories_module

    @contextmanager
    def fake_get_db():
        yield test_session

    monkeypatch.setattr(db_connection, "init_db", lambda: None)
    monkeypatch.setattr(db_connection, "get_db", fake_get_db)

    called_match_ids: list[int] = []

    class DummyService:
        def __init__(self, session):
            self.session = session

        def compute_and_store_for_match(self, match_db, *, force=False):
            called_match_ids.append(match_db.id)
            return 1

    class DummyRepo:
        def __init__(self, session):
            self.session = session

        def is_match_stale(self, match_id, expected_joueur_ids, match_updated_at):
            return True

    class DummyProgress:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add_task(self, *args, **kwargs):
            return 1

        def update(self, *args, **kwargs):
            return None

    monkeypatch.setattr(player_stats_service, "JoueurMatchStatsService", DummyService)
    monkeypatch.setattr(repositories_module, "JoueurMatchStatsRepository", DummyRepo)
    monkeypatch.setattr(cli_main, "make_progress", lambda _console: DummyProgress())

    runner = CliRunner()
    result = runner.invoke(cli_main.app, ["compute-player-stats", "--entity", "ABCCS"])

    assert result.exit_code == 0, result.stdout
    assert len(called_match_ids) == 1


def test_compute_player_stats_skips_up_to_date_without_force(monkeypatch, test_session):
    cli_main = importlib.import_module("pyvolley.cli.main")

    from pyvolley.database.models import (
        EntiteFFVBDB,
        SaisonDB,
        CompetitionDB,
        MatchDB,
        EquipeDB,
        JoueurDB,
        ParticipationMatchDB,
    )

    saison = SaisonDB(code="2024-2025", nom="Saison 2024-2025")
    entite = EntiteFFVBDB(code="ABCCS", nom="Entité A", type="ligue")
    test_session.add_all([saison, entite])
    test_session.flush()

    competition = CompetitionDB(nom="Comp", saison_id=saison.id, entite_id=entite.id)
    equipe = EquipeDB(nom="Equipe A", saison_id=saison.id, competition_id=None)
    joueur = JoueurDB(licence="LIC-001", nom="DUPONT", prenom="Jean")
    test_session.add_all([competition, equipe, joueur])
    test_session.flush()

    match = MatchDB(
        code_match="MATCH-001",
        has_details=True,
        match_joue=True,
        parsing_status="parsed",
        competition_id=competition.id,
        saison_id=saison.id,
        equipe_a_id=equipe.id,
    )
    test_session.add(match)
    test_session.flush()

    participation = ParticipationMatchDB(
        match_id=match.id,
        joueur_id=joueur.id,
        equipe_id=equipe.id,
    )
    test_session.add(participation)
    test_session.commit()

    import pyvolley.database.connection as db_connection
    import pyvolley.database.player_stats_service as player_stats_service
    import pyvolley.database.repositories as repositories_module

    @contextmanager
    def fake_get_db():
        yield test_session

    monkeypatch.setattr(db_connection, "init_db", lambda: None)
    monkeypatch.setattr(db_connection, "get_db", fake_get_db)

    compute_calls: list[int] = []

    class DummyService:
        def __init__(self, session):
            self.session = session

        def compute_and_store_for_match(self, match_db, *, force=False):
            compute_calls.append(match_db.id)
            return 1

    class DummyRepo:
        def __init__(self, session):
            self.session = session

        def delete_all(self):
            return 0

        def is_match_stale(self, match_id, expected_joueur_ids, match_updated_at):
            return False

    class DummyProgress:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add_task(self, *args, **kwargs):
            return 1

        def update(self, *args, **kwargs):
            return None

    monkeypatch.setattr(player_stats_service, "JoueurMatchStatsService", DummyService)
    monkeypatch.setattr(repositories_module, "JoueurMatchStatsRepository", DummyRepo)
    monkeypatch.setattr(cli_main, "make_progress", lambda _console: DummyProgress())

    runner = CliRunner()
    result = runner.invoke(cli_main.app, ["compute-player-stats", "--entity", "ABCCS"])

    assert result.exit_code == 0, result.stdout
    assert compute_calls == []


def test_compute_player_stats_skips_when_no_expected_players(monkeypatch, test_session):
    cli_main = importlib.import_module("pyvolley.cli.main")

    from pyvolley.database.models import EntiteFFVBDB, SaisonDB, CompetitionDB, MatchDB

    saison = SaisonDB(code="2024-2025", nom="Saison 2024-2025")
    entite = EntiteFFVBDB(code="ABCCS", nom="Entité A", type="ligue")
    test_session.add_all([saison, entite])
    test_session.flush()

    competition = CompetitionDB(nom="Comp", saison_id=saison.id, entite_id=entite.id)
    test_session.add(competition)
    test_session.flush()

    match = MatchDB(
        code_match="MATCH-EMPTY-001",
        has_details=True,
        match_joue=True,
        parsing_status="parsed",
        competition_id=competition.id,
        saison_id=saison.id,
    )
    test_session.add(match)
    test_session.commit()

    import pyvolley.database.connection as db_connection
    import pyvolley.database.player_stats_service as player_stats_service
    import pyvolley.database.repositories as repositories_module

    @contextmanager
    def fake_get_db():
        yield test_session

    monkeypatch.setattr(db_connection, "init_db", lambda: None)
    monkeypatch.setattr(db_connection, "get_db", fake_get_db)

    compute_calls: list[int] = []

    class DummyService:
        def __init__(self, session):
            self.session = session

        def compute_and_store_for_match(self, match_db, *, force=False):
            compute_calls.append(match_db.id)
            return 0

    class DummyRepo:
        def __init__(self, session):
            self.session = session

        def is_match_stale(self, match_id, expected_joueur_ids, match_updated_at):
            return False

    class DummyProgress:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add_task(self, *args, **kwargs):
            return 1

        def update(self, *args, **kwargs):
            return None

    monkeypatch.setattr(player_stats_service, "JoueurMatchStatsService", DummyService)
    monkeypatch.setattr(repositories_module, "JoueurMatchStatsRepository", DummyRepo)
    monkeypatch.setattr(cli_main, "make_progress", lambda _console: DummyProgress())

    runner = CliRunner()
    result = runner.invoke(cli_main.app, ["compute-player-stats", "--entity", "ABCCS"])

    assert result.exit_code == 0, result.stdout
    assert compute_calls == []
