"""Tests du moteur de vraisemblance des données parser."""

from datetime import date

from pyvolley.core.models import Match, Set
from pyvolley.parsers.plausibility import PlausibilityEngine


def test_date_year_corrected_from_saison():
    match = Match(
        code_match="TEST001",
        saison="2024-2025",
        date=date(2026, 1, 12),
    )

    report = PlausibilityEngine().check(match, policy="auto")

    assert match.date == date(2025, 1, 12)
    assert report.corrected_count >= 1
    assert any(i.field == "date" for i in report.issues)


def test_duration_normalized_from_minutes_format():
    match = Match(
        code_match="TEST002",
        duree_totale="75'",
    )

    report = PlausibilityEngine().check(match, policy="auto")

    assert match.duree_totale == "1h15"
    assert report.corrected_count >= 1


def test_duration_removed_when_invraisemblable_and_no_fallback():
    match = Match(
        code_match="TEST003",
        duree_totale="9h59",
    )

    report = PlausibilityEngine().check(match, policy="auto")

    assert match.duree_totale is None
    assert report.removed_count >= 1


def test_score_realigned_from_set_details():
    match = Match(
        code_match="TEST004",
        score_final="3/0",
        sets_a=3,
        sets_b=0,
        sets=[
            Set(numero=1, score_a=25, score_b=22),
            Set(numero=2, score_a=21, score_b=25),
            Set(numero=3, score_a=25, score_b=20),
            Set(numero=4, score_a=25, score_b=23),
        ],
    )

    report = PlausibilityEngine().check(match, policy="auto")

    assert match.score_final == "3/1"
    assert match.sets_a == 3
    assert match.sets_b == 1
    assert report.corrected_count >= 1


def test_report_only_policy_does_not_modify_data():
    match = Match(
        code_match="TEST005",
        saison="2024-2025",
        date=date(2026, 2, 1),
    )

    report = PlausibilityEngine().check(match, policy="report-only")

    assert match.date == date(2026, 2, 1)
    assert report.flagged_count >= 1
    assert report.corrected_count == 0
