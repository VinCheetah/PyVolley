"""Tests de rendu pour toutes les pages principales de l'interface PyVolley."""

from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from pyvolley.web.app import create_web_app
from pyvolley.api.dependencies import get_session
from pyvolley.database.models import (
    Base,
    EquipeDB,
    ClubDB,
    CompetitionDB,
    SaisonDB,
    MatchDB,
    ArbitreDB,
    JoueurDB,
)


@pytest.fixture
def client_with_db():
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

    competition = CompetitionDB(nom="Nationale 3 Test", niveau="NATIONALE", saison_id=saison.id)
    comp_jeunes = CompetitionDB(nom="Coupe de France M15 Masculine", niveau="JEUNES", categorie="M15", genre="MASCULIN", saison_id=saison.id)
    session.add_all([competition, comp_jeunes])
    session.flush()

    from pyvolley.database.models import PouleDB
    poule = PouleDB(code="EMA", nom="Poule A", competition_id=competition.id, tour=1)
    poule_jeunes = PouleDB(code="J1A", nom="Poule J1A", competition_id=comp_jeunes.id, tour=1)
    session.add_all([poule, poule_jeunes])
    session.flush()

    equipe_a = EquipeDB(nom="Équipe Alpha", club_id=club.id, competition_id=competition.id, saison_id=saison.id)
    equipe_b = EquipeDB(nom="Équipe Beta", club_id=club.id, competition_id=competition.id, saison_id=saison.id)
    session.add_all([equipe_a, equipe_b])
    session.flush()

    match = MatchDB(
        code_match="M001",
        equipe_a_id=equipe_a.id,
        equipe_b_id=equipe_b.id,
        competition_id=competition.id,
        poule_id=poule.id,
        saison_id=saison.id,
        sets_equipe_a=3,
        sets_equipe_b=1,
    )
    arbitre = ArbitreDB(nom="Dupont", prenom="Jean", licence="123456")
    joueur = JoueurDB(nom="Martin", prenom="Paul", licence="987654")
    session.add_all([match, arbitre, joueur])
    session.commit()

    app = create_web_app()

    def override_get_session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        yield client
    finally:
        from pyvolley.web.helpers.cache import stats_cache
        stats_cache.clear()
        app.dependency_overrides.clear()
        session.close()


def test_pages_render_successfully(client_with_db):
    pages = [
        "/",
        "/matchs",
        "/joueurs",
        "/equipes",
        "/clubs",
        "/competitions",
        "/competitions?saison_id=1",
        "/competitions?saison_id=all",
        "/competitions?echelon=national",
        "/competitions?echelon=coupe_de_france",
        "/competitions?view=table",
        "/competitions?view=grid",
        "/competitions?q=Nationale",
        "/competitions?genre=MASCULIN",
        "/arbitres",
        "/entraineurs",
        "/statistiques",
        "/palmares",
        "/palmares?genre=MASCULIN&niveau_echelon=REGIONAL",
        "/palmares?force_refresh=true",
        "/search?q=test",
    ]
    for path in pages:
        response = client_with_db.get(path)
        assert response.status_code == 200, f"Page {path} failed with status {response.status_code}"


def test_detail_pages_render_successfully(client_with_db):
    detail_pages = [
        "/matchs/1",
        "/joueurs/1",
        "/equipes/1",
        "/clubs/1",
        "/competitions/1",
        "/competitions/2",
        "/poules/1",
        "/arbitres/1",
    ]
    for path in detail_pages:
        response = client_with_db.get(path)
        assert response.status_code == 200, f"Detail page {path} failed with status {response.status_code}"
