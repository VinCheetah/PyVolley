from datetime import date as dt_date
from types import SimpleNamespace

from pyvolley.web.routes.joueurs import (
    _estimate_player_max_age,
    _extract_youth_ages_from_text,
    _season_end_year_from_code,
)


def _build_row(
    *,
    match_id: int,
    season_code: str | None,
    match_date: dt_date,
    competition: object | None,
    equipe_joueur: object | None = None,
    niveau: str | None = None,
) -> dict:
    saison = SimpleNamespace(code=season_code) if season_code else None
    match = SimpleNamespace(id=match_id, date_match=match_date)
    return {
        "match": match,
        "saison": saison,
        "competition": competition,
        "equipe_joueur": equipe_joueur,
        "niveau": niveau,
    }


def test_season_end_year_from_code_supports_long_and_short_formats() -> None:
    assert _season_end_year_from_code("2025-2026") == 2026
    assert _season_end_year_from_code("2025/2026") == 2026
    assert _season_end_year_from_code("25/26") == 2026


def test_extract_youth_ages_from_text_supports_m_and_u_notation() -> None:
    assert _extract_youth_ages_from_text("Tournoi U18 et M15") == [18, 15]


def test_estimate_player_max_age_keeps_strictest_birth_date_bound() -> None:
    rows = [
        _build_row(
            match_id=101,
            season_code="2025-2026",
            match_date=dt_date(2025, 10, 4),
            competition=SimpleNamespace(
                categorie="M18",
                nom="Coupe de France M18",
                niveau="NATIONALE",
            ),
        ),
        _build_row(
            match_id=102,
            season_code="2022-2023",
            match_date=dt_date(2023, 5, 14),
            competition=SimpleNamespace(
                categorie="M13",
                nom="Tournoi regional M13",
                niveau="REGIONALE",
            ),
        ),
    ]

    estimated = _estimate_player_max_age(rows, reference_date=dt_date(2026, 4, 9))

    assert estimated is not None
    assert estimated["birth_date_min"] == "2010-01-01"
    assert estimated["max_age_years"] == 16
    assert "M13" in estimated["best_category_labels"]
    assert estimated["best_season_labels"] == ["2022-2023"]


def test_estimate_player_max_age_returns_none_without_youth_categories() -> None:
    rows = [
        _build_row(
            match_id=201,
            season_code="2025-2026",
            match_date=dt_date(2025, 11, 2),
            competition=SimpleNamespace(
                categorie="SENIOR",
                nom="Nationale 2 masculine",
                niveau="NATIONALE",
            ),
        )
    ]

    assert _estimate_player_max_age(rows, reference_date=dt_date(2026, 4, 9)) is None
