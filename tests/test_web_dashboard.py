"""Tests pour la route web du tableau de bord (page d'accueil)."""

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
    SetDB,
)


def test_web_dashboard_renders_successfully():
    from pyvolley.web.helpers.cache import stats_cache
    stats_cache.clear()

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    session = TestingSessionLocal()

    saison = SaisonDB(code="2024-2025", nom="Saison 2024-2025")
    club = ClubDB(nom="Volley Club Dashboard")
    session.add_all([saison, club])
    session.flush()

    competition = CompetitionDB(nom="Nationale 3", niveau="NATIONALE", saison_id=saison.id)
    session.add(competition)
    session.flush()

    eq_a = EquipeDB(nom="Équipe Alpha", club_id=club.id, competition_id=competition.id, saison_id=saison.id)
    eq_b = EquipeDB(nom="Équipe Bêta", club_id=club.id, competition_id=competition.id, saison_id=saison.id)
    session.add_all([eq_a, eq_b])
    session.flush()

    match = MatchDB(
        code_match="DASH001",
        date_match=date(2025, 2, 1),
        saison_id=saison.id,
        competition_id=competition.id,
        equipe_a_id=eq_a.id,
        equipe_b_id=eq_b.id,
        sets_equipe_a=3,
        sets_equipe_b=1,
        score_sets="3/1",
    )
    session.add(match)
    session.flush()

    set1 = SetDB(match_id=match.id, numero=1, score_a=25, score_b=21)
    set2 = SetDB(match_id=match.id, numero=2, score_a=23, score_b=25)
    set3 = SetDB(match_id=match.id, numero=3, score_a=25, score_b=18)
    set4 = SetDB(match_id=match.id, numero=4, score_a=25, score_b=20)
    session.add_all([set1, set2, set3, set4])
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
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "PyVolley" in html
    assert "Tableau de bord" in html
    assert "Équipe Alpha" in html
    assert "Équipe Bêta" in html
    assert "25-21" in html
    assert "Nationale 3" in html
