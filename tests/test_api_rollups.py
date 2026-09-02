"""
Tests pour les endpoints API liés aux statistiques et rollups.
"""

from datetime import date
import pytest
from starlette.testclient import TestClient

from pyvolley.web.app import create_web_app
from pyvolley.database.connection import get_db
from pyvolley.database.models import (
    SaisonDB, CompetitionDB, PouleDB, ClubDB, EquipeDB, JoueurDB,
    MatchDB, ParticipationMatchDB, JoueurMatchStatsDB,
)
from pyvolley.database.rollup_service import RollupStatsService


@pytest.fixture
def client(monkeypatch):
    """Crée un client de test avec des données de rollups pré-calculées."""
    app = create_web_app()
    with TestClient(app) as test_client:
        with get_db() as session:
            s1 = session.query(SaisonDB).first()
            if not s1:
                s1 = SaisonDB(code="2025-2026", nom="Saison 2025-2026")
                session.add(s1)
                session.flush()

            comp = session.query(CompetitionDB).first()
            if not comp:
                comp = CompetitionDB(nom="TEST ELITE", saison_id=s1.id, genre="MASCULIN", niveau="ELITE")
                session.add(comp)
                session.flush()

            club = session.query(ClubDB).first()
            if not club:
                club = ClubDB(nom="TEST CLUB", code_ffvb="9990001")
                session.add(club)
                session.flush()

            eq = session.query(EquipeDB).first()
            if not eq:
                eq = EquipeDB(nom="TEST EQUIPE", club_id=club.id, saison_id=s1.id, competition_id=comp.id)
                session.add(eq)
                session.flush()

            j = session.query(JoueurDB).first()
            if not j:
                j = JoueurDB(licence="9999999", nom="TEST", prenom="JOUEUR")
                session.add(j)
                session.flush()

            # Calculer les rollups
            service = RollupStatsService(session)
            service.compute_player_season_stats()
            service.compute_team_season_stats()
            service.compute_player_career_stats()

        yield test_client


def test_api_leaderboards_scorers(client):
    res = client.get("/api/stats/leaderboards/scorers")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_leaderboards_servers(client):
    res = client.get("/api/stats/leaderboards/servers")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_leaderboards_career(client):
    res = client.get("/api/stats/leaderboards/career")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_stats_palmares(client):
    res = client.get("/api/stats/palmares")
    assert res.status_code == 200
    data = res.json()
    assert "results" in data
    assert "top_victoires" in data["results"]


def test_api_equipe_saisons_stats(client):
    with get_db() as session:
        eq = session.query(EquipeDB).first()
        eq_id = eq.id if eq else 1
    res = client.get(f"/api/equipes/{eq_id}/saisons-stats")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_joueur_saisons_stats(client):
    with get_db() as session:
        j = session.query(JoueurDB).first()
        j_id = j.id if j else 1
    res = client.get(f"/api/joueurs/{j_id}/saisons-stats")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
