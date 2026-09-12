"""Tests unitaires pour le module de métriques de performance et timing CLI."""

import time
from rich.console import Console
from typer.testing import CliRunner

from pyvolley.cli.timing import (
    format_duration,
    format_rate,
    StepMetric,
    PipelineTimer,
)
from pyvolley.cli.main import app


runner = CliRunner()


def test_format_duration():
    """Vérifie le formatage lisible des durées pour différentes échelles."""
    assert format_duration(None) == "—"
    assert format_duration(-1.0) == "0.0s"
    assert format_duration(0.045) == "45ms"
    assert format_duration(0.85) == "850ms"
    assert format_duration(1.23) == "1.2s"
    assert format_duration(59.9) == "59.9s"
    assert format_duration(65.0) == "1m 05s"
    assert format_duration(3665.0) == "1h 01m 05s"


def test_format_rate():
    """Vérifie le formatage des débits (it/s, m/s, it/min)."""
    assert format_rate(None, 10.0) == "—"
    assert format_rate(0, 10.0) == "—"
    assert format_rate(100, None) == "—"
    assert format_rate(100, 0.0) == "—"
    assert format_rate(100, 10.0, unit="it") == "10.0 it/s"
    assert format_rate(50, 5.0, unit="m") == "10.0 m/s"
    # Cadence lente (< 1 it/s) convertie en cadence par minute
    assert format_rate(30, 60.0, unit="it") == "30.0 it/min"


def test_step_metric_lifecycle():
    """Vérifie le cycle de vie d'une métrique d'étape et de sous-étapes."""
    step = StepMetric(name="Scraping")
    assert step.duration is None
    assert step.status == "PENDING"

    step.start()
    assert step.status == "RUNNING"
    time.sleep(0.02)
    step.finish(count=15, status="OK")

    assert step.status == "OK"
    assert step.count == 15
    assert step.duration is not None and step.duration >= 0.01

    # Sous-étapes
    sub = StepMetric(name="Download PDFs")
    sub.start()
    sub.finish(count=10, status="OK")
    step.sub_steps.append(sub)

    assert len(step.sub_steps) == 1
    assert step.sub_steps[0].name == "Download PDFs"


def test_pipeline_timer_context_manager():
    """Vérifie l'utilisation de PipelineTimer avec des context managers."""
    timer = PipelineTimer(name="Test Pipeline")
    timer.start()

    with timer.step("Extraction") as s1:
        time.sleep(0.01)
        with timer.sub_step("Phase A") as sub_a:
            sub_a.count = 5
        s1.count = 20

    with timer.step("Calculs") as s2:
        time.sleep(0.01)
        s2.count = 100

    timer.finish()

    assert len(timer.steps) == 2
    assert timer.steps[0].name == "Extraction"
    assert timer.steps[0].count == 20
    assert len(timer.steps[0].sub_steps) == 1
    assert timer.steps[0].sub_steps[0].name == "Phase A"
    assert timer.steps[1].name == "Calculs"
    assert timer.steps[1].count == 100
    assert timer.total_duration is not None and timer.total_duration >= 0.02


def test_pipeline_timer_display_summary_modes():
    """Vérifie l'affichage du récapitulatif selon le niveau de détail."""
    test_console = Console(record=True, width=120)
    timer = PipelineTimer(name="Test Summary Pipeline", console=test_console)
    timer.start()

    with timer.step("Étape Principale") as step:
        time.sleep(0.01)
        step.count = 50
        with timer.sub_step("Sous-étape 1") as sub:
            sub.count = 25

    timer.finish()

    # 1. Mode 'none' -> aucun affichage
    test_console.file = None  # Reset buffer
    test_console.clear()
    timer.display_summary(detail="none")
    output_none = test_console.export_text()
    assert output_none.strip() == ""

    # 2. Mode 'summary' -> tableau avec étape principale
    test_console.clear()
    timer.display_summary(detail="summary")
    output_summary = test_console.export_text()
    assert "Récapitulatif des performances" in output_summary
    assert "Étape Principale" in output_summary
    # La sous-étape ne doit pas figurer en mode 'summary'
    assert "Sous-étape 1" not in output_summary
    assert "Total" in output_summary

    # 3. Mode 'detailed' -> tableau avec indentation de la sous-étape
    test_console.clear()
    timer.display_summary(detail="detailed")
    output_detailed = test_console.export_text()
    assert "Récapitulatif des performances" in output_detailed
    assert "Étape Principale" in output_detailed
    assert "Sous-étape 1" in output_detailed
    assert "Total" in output_detailed


def test_cli_import_help_timing_options():
    """Vérifie la présence de l'option timing dans l'aide de pyvolley import."""
    result = runner.invoke(app, ["import", "--help"])
    assert result.exit_code == 0
    assert "--timing-detail" in result.output
    assert "-T" in result.output


def test_cli_compute_all_help_timing_options():
    """Vérifie la présence de l'option timing dans l'aide de pyvolley compute all."""
    result = runner.invoke(app, ["compute", "all", "--help"])
    assert result.exit_code == 0
    assert "--timing-detail" in result.output
    assert "-T" in result.output


def test_cli_compute_all_execution_timing(monkeypatch):
    """Vérifie l'exécution de pyvolley compute all avec récapitulatif temporel."""
    import pyvolley.cli.commands.compute_cmd as compute_mod

    monkeypatch.setattr(compute_mod, "compute_player_stats", lambda **kw: None)
    monkeypatch.setattr(compute_mod, "compute_rollups", lambda **kw: None)
    monkeypatch.setattr(compute_mod, "compute_geo", lambda **kw: None)
    monkeypatch.setattr(compute_mod, "compute_licences", lambda **kw: None)
    monkeypatch.setattr(compute_mod, "compute_stats", lambda **kw: None)

    # 1. Avec --timing-detail summary
    res = runner.invoke(app, ["compute", "all", "--skip-roles", "--timing-detail", "summary"])
    assert res.exit_code == 0, res.stdout
    assert "Récapitulatif" in res.stdout
    assert "Stats Joueurs par Match" in res.stdout

    # 2. Avec --timing-detail none
    res_none = runner.invoke(app, ["compute", "all", "--skip-roles", "--timing-detail", "none"])
    assert res_none.exit_code == 0, res_none.stdout
    assert "Récapitulatif de la Chaîne de Calculs" not in res_none.stdout


def test_cli_import_execution_timing(monkeypatch):
    """Vérifie l'exécution de pyvolley import avec récapitulatif temporel."""
    import importlib
    cli_main = importlib.import_module("pyvolley.cli.main")
    import pyvolley.cli.commands.import_cmd as import_mod
    import pyvolley.database.connection as db_conn

    monkeypatch.setattr(db_conn, "init_db", lambda: None)
    monkeypatch.setattr(cli_main, "_import_scrape", lambda *args, **kw: None)
    monkeypatch.setattr(import_mod, "_import_scrape", lambda *args, **kw: None)

    # 1. Mode summary
    res = runner.invoke(cli_main.app, ["import", "-e", "ABCCS", "-s", "24/25", "--only", "scrape", "--timing-detail", "summary"])
    assert res.exit_code == 0, res.stdout
    assert "Récapitulatif du Pipeline d'Import" in res.stdout
    assert "1. Scrape" in res.stdout

    # 2. Mode none
    res_none = runner.invoke(cli_main.app, ["import", "-e", "ABCCS", "-s", "24/25", "--only", "scrape", "--timing-detail", "none"])
    assert res_none.exit_code == 0, res_none.stdout
    assert "Récapitulatif du Pipeline d'Import" not in res_none.stdout


