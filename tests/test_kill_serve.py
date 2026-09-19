"""Tests pour l'arrêt des processus pyvolley serve."""

from pyvolley.cli.commands.pipeline_cmd import (
    find_pids_on_port,
    find_pyvolley_serve_pids,
    kill_pids,
    kill_active_serve,
)


def test_find_pids_on_port_unused():
    """Vérifie que la détection sur un port inutilisé renvoie une liste vide."""
    pids = find_pids_on_port(59999)
    assert isinstance(pids, list)
    assert len(pids) == 0


def test_kill_pids_safe_with_empty():
    """Vérifie que kill_pids gère les listes vides sans erreur."""
    killed = kill_pids([])
    assert killed == []


def test_find_pyvolley_serve_pids_excludes_current():
    """Vérifie que la détection des processus n'inclut jamais le processus de test lui-même."""
    import os
    pids = find_pyvolley_serve_pids()
    assert os.getpid() not in pids
    if hasattr(os, "getppid"):
        assert os.getppid() not in pids
