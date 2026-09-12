"""Tests for canonical FFVB URLs across web routes and templates."""

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
    PouleDB,
    SaisonDB,
    MatchDB,
    ArbitreDB,
    ArbitreMatchDB,
    ParticipationMatchDB,
    JoueurMatchStatsDB,
)
from pyvolley.web.templateconfig import path_for_entity


def test_path_for_entity_uses_canonical_identifiers():
    """Verify path_for_entity generates business FFVB URLs."""
    joueur = JoueurDB(id=42, licence="2014856", nom="TEST", prenom="Player")
    assert path_for_entity("joueur", joueur) == "/joueurs/2014856"

    club = ClubDB(id=10, code_ffvb="0948201", nom="VBC Test")
    assert path_for_entity("club", club) == "/clubs/0948201"

    match = MatchDB(id=99, code_match="EMA012")
    assert path_for_entity("match", match) == "/matchs/EMA012"

    arbitre = ArbitreDB(id=5, licence="ARB9876", nom="Ref", prenom="Official")
    assert path_for_entity("arbitre", arbitre) == "/arbitres/ARB9876"

    competition = CompetitionDB(id=7, code_competition="N2M_A", nom="Nationale 2 M")
    assert path_for_entity("competition", competition) == "/competitions/N2M_A"

    poule = PouleDB(id=3, code="EMA", nom="Poule A")
    assert path_for_entity("poule", poule) == "/poules/EMA"


def test_web_routes_render_with_canonical_urls():
    """Verify HTTP GET /joueurs/{licence}, /clubs/{code_ffvb}, /matchs/{code_match}, /arbitres/{licence} work."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()

    saison = SaisonDB(code="2024-2025", nom="Saison 2024-2025")
    club = ClubDB(nom="Volley Club Paris", code_ffvb="0750001", ville="Paris")
    session.add_all([saison, club])
    session.flush()

    competition = CompetitionDB(
        nom="Nationale 2",
        code_competition="NAT2M",
        niveau="NATIONALE_2",
        saison_id=saison.id,
    )
    session.add(competition)
    session.flush()

    poule = PouleDB(code="EMA", nom="Poule A", competition_id=competition.id)
    session.add(poule)
    session.flush()

    equipe = EquipeDB(nom="Paris Volley 1", club_id=club.id)
    adversaire = EquipeDB(nom="Lyon Volley", club_id=club.id)
    joueur = JoueurDB(nom="DUPONT", prenom="Jean", licence="0987654")
    arbitre = ArbitreDB(nom="MARTIN", prenom="Claire", licence="ARB12345")
    session.add_all([equipe, adversaire, joueur, arbitre])
    session.flush()

    match = MatchDB(
        code_match="NAT042",
        date_match=date(2025, 3, 15),
        saison_id=saison.id,
        competition_id=competition.id,
        poule_id=poule.id,
        equipe_a_id=equipe.id,
        equipe_b_id=adversaire.id,
        sets_equipe_a=3,
        sets_equipe_b=2,
        match_joue=True,
    )
    session.add(match)
    session.flush()

    part = ParticipationMatchDB(
        match_id=match.id,
        joueur_id=joueur.id,
        equipe_id=equipe.id,
        numero_maillot="10",
    )
    stats = JoueurMatchStatsDB(
        match_id=match.id,
        joueur_id=joueur.id,
        equipe_id=equipe.id,
        points_gagnes=18,
        sets_joues=5,
    )
    arb_match = ArbitreMatchDB(
        match_id=match.id,
        arbitre_id=arbitre.id,
        role="1er Arbitre",
    )
    session.add_all([part, stats, arb_match])
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

    # 1. Player route by licence
    res_joueur = client.get(f"/joueurs/{joueur.licence}")
    assert res_joueur.status_code == 200
    assert "DUPONT" in res_joueur.text
    assert "Jean" in res_joueur.text

    # 2. Club route by code_ffvb
    res_club = client.get(f"/clubs/{club.code_ffvb}")
    assert res_club.status_code == 200
    assert "Volley Club Paris" in res_club.text

    # 3. Match route by code_match
    res_match = client.get(f"/matchs/{match.code_match}")
    assert res_match.status_code == 200
    assert "NAT042" in res_match.text

    # 4. Arbitre route by licence
    res_arb = client.get(f"/arbitres/{arbitre.licence}")
    assert res_arb.status_code == 200
    assert "MARTIN" in res_arb.text

    # 5. Competition route by code_competition
    res_comp = client.get(f"/competitions/{competition.code_competition}")
    assert res_comp.status_code == 200
    assert "Nationale 2" in res_comp.text

    # 6. Poule route by code
    res_poule = client.get(f"/poules/{poule.code}")
    assert res_poule.status_code == 200
    assert "EMA" in res_poule.text
