"""Tests pour la commande CLI pyvolley compare."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pyvolley.cli.main import app

runner = CliRunner()


def test_compare_help():
    """Vérifie que la commande compare --help s'exécute correctement sans erreur."""
    result = runner.invoke(app, ["compare", "--help"])
    assert result.exit_code == 0
    assert "Comparer la vitesse d'exécution" in result.output
    assert "--parsers" in result.output or "-p" in result.output


def test_compare_invalid_parser():
    """Vérifie le message d'erreur lorsqu'un parser inconnu est spécifié."""
    result = runner.invoke(app, ["compare", "-p", "unknown_parser"])
    assert result.exit_code == 1
    assert "Parser 'unknown_parser' non reconnu" in result.output


def test_compare_custom_parsers_flags(tmp_path):
    """Vérifie l'exécution de la comparaison avec -p legacy -p fast."""
    result = runner.invoke(app, ["compare", str(tmp_path), "-p", "legacy", "-p", "fast"])
    assert result.exit_code == 0
    assert "Aucun fichier PDF trouvé" in result.output


def test_compare_custom_parsers_comma_separated(tmp_path):
    """Vérifie le parsing de plusieurs parsers séparés par des virgules."""
    result = runner.invoke(app, ["compare", str(tmp_path), "-p", "legacy,fast"])
    assert result.exit_code == 0
    assert "Aucun fichier PDF trouvé" in result.output


def test_compare_execution_with_pdf():
    """Vérifie le comportement de compare lorsqu'un vrai PDF est fourni."""
    sample_pdf = Path("data/data_sample/BMAA003.pdf")
    if not sample_pdf.exists():
        pytest.skip("Fichier de test data/data_sample/BMAA003.pdf introuvable.")

    result = runner.invoke(app, ["compare", str(sample_pdf), "-p", "legacy", "-p", "fast", "-v"])
    assert result.exit_code == 0
    assert "Comparaison des Parsers PyVolley" in result.output
    assert "Legacy" in result.output
    assert "Fast" in result.output
