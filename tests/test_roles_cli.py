"""Tests CLI pour le module pyvolley roles (diffuse, inspect, audit, evaluate-match)."""

from typer.testing import CliRunner
from pyvolley.cli.main import app

runner = CliRunner()


def test_roles_cli_help():
    """Vérifie que la commande roles --help liste bien les 4 sous-commandes."""
    result = runner.invoke(app, ["roles", "--help"])
    assert result.exit_code == 0
    assert "diffuse" in result.output
    assert "inspect" in result.output
    assert "audit" in result.output
    assert "evaluate-match" in result.output


def test_roles_cli_audit():
    """Vérifie que roles audit s'exécute et affiche les métriques."""
    result = runner.invoke(app, ["roles", "audit"])
    assert result.exit_code == 0
    assert "Audit global des rôles" in result.output or "Aucune statistique" in result.output


def test_roles_cli_evaluate_match():
    """Vérifie que roles evaluate-match décompose les deux équipes."""
    result = runner.invoke(app, ["roles", "evaluate-match", "1"])
    assert result.exit_code in (0, 1)
    assert "Équipe A" in result.output or "Match #1" in result.output


def test_compute_all_cli_help():
    """Vérifie que la commande compute all documente l'étape de diffusion des rôles et --skip-roles."""
    result = runner.invoke(app, ["compute", "all", "--help"])
    assert result.exit_code == 0
    assert "--skip-roles" in result.output
    assert "Diffusion réseau des rôles" in result.output
