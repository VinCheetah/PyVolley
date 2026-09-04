"""Tests pour la route web de détail joueur."""

from datetime import date
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pyvolley.web.app import create_web_app
from pyvolley.api.dependencies import get_session
from pyvolley.database.models import (
    Base,
    JoueurDB,
    EquipeDB,
    ClubDB,
    CompetitionDB,
    SaisonDB,
    MatchDB,
    ParticipationMatchDB,
    JoueurMatchStatsDB,
)


def test_web_joueur_detail_page_renders_successfully():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    session = TestingSessionLocal()

    saison = SaisonDB(code="2024-2025", nom="Saison 2024-2025")
    club = ClubDB(nom="Volley Club Test")
    session.add_all([saison, club])
    session.flush()

    competition = CompetitionDB(nom="Régionale Masculine", niveau="REGIONALE", saison_id=saison.id)
    session.add(competition)
    session.flush()

    equipe = EquipeDB(nom="Equipe 1", club_id=club.id)
    adversaire = EquipeDB(nom="Equipe Adverse", club_id=club.id)
    joueur = JoueurDB(nom="GARDIES", prenom="Paul", licence="1234567")
    session.add_all([equipe, adversaire, joueur])
    session.flush()

    match = MatchDB(
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
    session.add(match)
    session.flush()

    part = ParticipationMatchDB(
        match_id=match.id,
        joueur_id=joueur.id,
        equipe_id=equipe.id,
        numero_maillot="7",
    )
    stats = JoueurMatchStatsDB(
        match_id=match.id,
        joueur_id=joueur.id,
        equipe_id=equipe.id,
        points_gagnes=12,
        points_perdus=5,
        points_joues=40,
        services=15,
        sets_joues=4,
        role_principal="RECEPTIONNEUR_ATTAQUANT",
    )
    session.add_all([part, stats])
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

    response = client.get(f"/joueurs/{joueur.id}")
    assert response.status_code == 200
    assert "GARDIES" in response.text
    assert "Paul" in response.text
