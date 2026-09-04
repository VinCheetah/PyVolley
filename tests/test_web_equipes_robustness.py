"""Tests de robustesse pour la route web détail équipe et l'API cartographique."""

from datetime import date
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pyvolley.web.app import create_web_app
from pyvolley.api.dependencies import get_session
from pyvolley.database.models import (
    Base,
    EquipeDB,
    ClubDB,
    CompetitionDB,
    SaisonDB,
    MatchDB,
    EquipeSaisonStatsDB,
)


def test_web_equipe_detail_and_map_with_unplayed_matches_and_season_stats():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    session = TestingSessionLocal()

    saison = SaisonDB(code="2025-2026", nom="Saison 2025-2026")
    club = ClubDB(nom="Volley Club Test")
    session.add_all([saison, club])
    session.flush()

    competition = CompetitionDB(nom="Régionale Masculine", niveau="REGIONALE", saison_id=saison.id)
    session.add(competition)
    session.flush()

    equipe = EquipeDB(nom="Equipe 1", club_id=club.id, saison_id=saison.id)
    adversaire = EquipeDB(nom="Equipe Adverse", club_id=club.id, saison_id=saison.id)
    session.add_all([equipe, adversaire])
    session.flush()

    # Match joué normalement
    match_joue = MatchDB(
        code_match="TEST01",
        date_match=date(2025, 2, 1),
        saison_id=saison.id,
        competition_id=competition.id,
        equipe_a_id=equipe.id,
        equipe_b_id=adversaire.id,
        sets_equipe_a=3,
        sets_equipe_b=1,
        match_joue=True,
    )
    # Match non joué ou à venir (sets_equipe_a et b sont None)
    match_a_venir = MatchDB(
        code_match="TEST02",
        date_match=date(2025, 3, 1),
        saison_id=saison.id,
        competition_id=competition.id,
        equipe_a_id=adversaire.id,
        equipe_b_id=equipe.id,
        sets_equipe_a=None,
        sets_equipe_b=None,
        match_joue=False,
    )
    session.add_all([match_joue, match_a_venir])
    session.flush()

    # Stats saison calculées (auparavant renvoyait une liste faisant crasher equipe_detail)
    eq_stats = EquipeSaisonStatsDB(
        equipe_id=equipe.id,
        saison_id=saison.id,
        competition_id=competition.id,
        matchs_joues=1,
        victoires=1,
        defaites=0,
        sets_pour=3,
        sets_contre=1,
    )
    session.add(eq_stats)
    session.commit()

    def override_get_session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_web_app()
    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app, raise_server_exceptions=True)

    # 1. Test du rendu de la page équipe (ne doit pas lever d'erreur interne 500)
    response = client.get(f"/equipes/{equipe.id}")
    assert response.status_code == 200
    assert "Equipe 1" in response.text
    assert "Carte des déplacements" in response.text

    # 2. Test de l'API cartographique pour cette équipe
    map_resp = client.get(f"/api/map/locations?equipe_id={equipe.id}")
    assert map_resp.status_code == 200
    data = map_resp.json()
    assert "markers" in data
