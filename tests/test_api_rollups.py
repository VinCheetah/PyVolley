"""
Tests pour les endpoints API liés aux statistiques et rollups.
"""

from datetime import date
import pytest
from starlette.testclient import TestClient

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pyvolley.web.app import create_web_app
from pyvolley.api.dependencies import get_session
from pyvolley.database.models import (
    Base, SaisonDB, CompetitionDB, PouleDB, ClubDB, EquipeDB, JoueurDB,
    MatchDB, ParticipationMatchDB, JoueurMatchStatsDB, JoueurSaisonStatsDB,
)
from pyvolley.database.rollup_service import RollupStatsService


@pytest.fixture(scope="module")
def client():
    """Crée un client de test avec des données de rollups pré-calculées en mémoire."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()

    s1 = SaisonDB(code="2025-2026", nom="Saison 2025-2026")
    session.add(s1)
    session.flush()

    comp = CompetitionDB(nom="TEST ELITE", saison_id=s1.id, genre="MASCULIN", niveau="ELITE")
    session.add(comp)
    session.flush()

    club = ClubDB(nom="TEST CLUB", code_ffvb="9990001")
    session.add(club)
    session.flush()

    eq = EquipeDB(nom="TEST EQUIPE", club_id=club.id, saison_id=s1.id, competition_id=comp.id)
    session.add(eq)
    session.flush()

    j = JoueurDB(licence="9999999", nom="TEST", prenom="JOUEUR")
    session.add(j)
    session.flush()

    service = RollupStatsService(session)
    service.compute_player_season_stats(saison_id=s1.id)
    service.compute_team_season_stats(saison_id=s1.id)
    service.compute_player_career_stats()

    app = create_web_app()

    def override_get_session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    session.close()


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
    res = client.get("/api/equipes/1/saisons-stats")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_joueur_saisons_stats(client):
    res = client.get("/api/joueurs/1/saisons-stats")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
