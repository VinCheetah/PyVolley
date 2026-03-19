from datetime import date
from types import SimpleNamespace

from rich.console import Console

from pyvolley.cli.main import _apply_plausibility_core_to_match_db
from pyvolley.cli.plausibility_cli import display_plausibility_summary


def test_apply_plausibility_core_to_match_db_updates_fields():
    match_db = SimpleNamespace(
        date_match=date(2026, 1, 10),
        duree_totale="9h59",
        score_sets="3/0",
        sets_equipe_a=3,
        sets_equipe_b=0,
    )
    core_match = SimpleNamespace(
        date=date(2025, 1, 10),
        duree_totale=None,
        score_final="3/1",
        sets_a=3,
        sets_b=1,
    )

    changes = _apply_plausibility_core_to_match_db(
        match_db,
        core_match,
        apply_changes=True,
    )

    assert len(changes) == 4
    assert match_db.date_match == date(2025, 1, 10)
    assert match_db.duree_totale is None
    assert match_db.score_sets == "3/1"
    assert match_db.sets_equipe_b == 1


def test_apply_plausibility_core_to_match_db_dry_run_keeps_values():
    match_db = SimpleNamespace(
        date_match=date(2026, 1, 10),
        duree_totale="9h59",
        score_sets="3/0",
        sets_equipe_a=3,
        sets_equipe_b=0,
    )
    core_match = SimpleNamespace(
        date=date(2025, 1, 10),
        duree_totale=None,
        score_final="3/1",
        sets_a=3,
        sets_b=1,
    )

    changes = _apply_plausibility_core_to_match_db(
        match_db,
        core_match,
        apply_changes=False,
    )

    assert len(changes) == 4
    assert match_db.date_match == date(2026, 1, 10)
    assert match_db.duree_totale == "9h59"
    assert match_db.score_sets == "3/0"
    assert match_db.sets_equipe_b == 0


def test_display_plausibility_summary_renders_without_name_error():
    console = Console(record=True)
    results = [
        {
            "plausibility_report": {
                "summary": {
                    "by_action": {"auto_fix": 2},
                    "by_rule": {"score.format": 1},
                }
            }
        }
    ]

    display_plausibility_summary(console, results)
    output = console.export_text()

    assert "auto_fix" in output
    assert "score.format" in output
