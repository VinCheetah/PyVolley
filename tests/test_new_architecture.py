"""
Tests unitaires pour la nouvelle architecture de données, classements et analyses territoriales.
"""

import pytest
from starlette.testclient import TestClient

from pyvolley.web.app import create_web_app
from pyvolley.database.models import (
    ClubDB, EquipeDB, JoueurDB, SaisonDB, CompetitionDB, MatchDB,
    ClubStatsDB, GeoStatsDB, JoueurLicenceHistoryDB,
)
from pyvolley.database.repositories import (
    ClubStatsRepository, GeoStatsRepository, JoueurLicenceHistoryRepository,
)
from pyvolley.database.ranking_service import (
    RankingService, RankingFilters,
)
from pyvolley.database.geographic_service import GeographicStatsService
from pyvolley.database.licence_analysis_service import LicenceAnalysisService


def test_models_and_repositories(test_session):
    """Vérifie le fonctionnement CRUD des nouveaux modèles et repositories."""
    club_repo = ClubStatsRepository(test_session)
    geo_repo = GeoStatsRepository(test_session)
    lic_repo = JoueurLicenceHistoryRepository(test_session)

    # 1. ClubStats
    club = ClubDB(nom="Club Test Rollup", departement="75", ligue="IDF")
    test_session.add(club)
    test_session.flush()

    cs = club_repo.upsert({
        "club_id": club.id,
        "saison_id": None,
        "nb_equipes_engagees": 3,
        "nb_matchs_joues": 30,
        "nb_victoires": 20,
        "nb_defaites": 10,
        "ratio_victoires": 0.667,
    })
    assert cs.id is not None
    assert cs.nb_victoires == 20

    retrieved_cs = club_repo.get_by_key(club.id, None)
    assert retrieved_cs is not None
    assert retrieved_cs.ratio_victoires == 0.667

    # 2. GeoStats
    gs = geo_repo.upsert({
        "saison_id": None,
        "echelon": "region",
        "code_territoire": "IDF",
        "nom_territoire": "Île-de-France",
        "nb_clubs": 150,
        "nb_equipes": 400,
        "nb_joueurs_actifs": 3500,
        "nb_matchs_joues": 1200,
    })
    assert gs.id is not None
    assert gs.code_territoire == "IDF"

    by_echelon = geo_repo.get_by_echelon("region")
    assert any(r.code_territoire == "IDF" for r in by_echelon)

    # 3. JoueurLicenceHistory
    joueur = JoueurDB(nom="Volleyeur", prenom="Test", licence="1234567")
    saison = SaisonDB(code="2025-2026", nom="Saison Test")
    test_session.add_all([joueur, saison])
    test_session.flush()

    jlh = lic_repo.upsert({
        "joueur_id": joueur.id,
        "saison_id": saison.id,
        "type_licence": "nouvelle",
        "premiere_saison_id": saison.id,
        "nb_saisons_absence": 0,
    })
    assert jlh.id is not None
    assert jlh.type_licence == "nouvelle"

    summary = lic_repo.get_summary_by_saison(saison.id)
    assert summary.get("nouvelle") == 1


def test_ranking_service(test_session):
    """Vérifie le calcul et le filtrage des classements universels."""
    service = RankingService(test_session)

    # Classement des clubs
    club_repo = ClubStatsRepository(test_session)
    c1 = ClubDB(nom="Amiens VB", departement="80", ligue="HDF")
    c2 = ClubDB(nom="Paris Volley", departement="75", ligue="IDF")
    test_session.add_all([c1, c2])
    test_session.flush()

    club_repo.upsert({"club_id": c1.id, "saison_id": None, "nb_victoires": 15, "nb_matchs_joues": 20})
    club_repo.upsert({"club_id": c2.id, "saison_id": None, "nb_victoires": 25, "nb_matchs_joues": 30})
    test_session.commit()

    res = service.get_ranking(
        RankingFilters(entity_type="clubs", metric="nb_victoires", saison_id=None),
        use_cache=False,
    )
    assert res.total_count >= 2
    assert res.items[0].entity_id == c2.id
    assert res.items[0].metrique_valeur == 25
    assert res.items[0].rank == 1


@pytest.fixture
def new_arch_client():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from pyvolley.api.dependencies import get_session
    from pyvolley.database.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()

    s = SaisonDB(code="2025-2026", nom="Saison Test")
    c = ClubDB(nom="Paris Volley", departement="75", ligue="IDF")
    session.add_all([s, c])
    session.commit()

    app = create_web_app()

    def override_get_session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    session.close()


def test_web_routes_render(new_arch_client):
    """Vérifie que les nouvelles routes /classements et /territoire répondent en HTTP 200."""
    client = new_arch_client

    # 1. Route /classements
    response = client.get("/classements")
    assert response.status_code == 200
    assert "Classements Universels" in response.text
    assert "Joueurs" in response.text
    assert "Équipes" in response.text
    assert "Clubs" in response.text

    # Test avec filtres
    r_clubs = client.get("/classements?entity_type=clubs")
    assert r_clubs.status_code == 200

    r_equipes = client.get("/classements?entity_type=equipes")
    assert r_equipes.status_code == 200

    # 2. Route /territoire
    r_territoire = client.get("/territoire")
    assert r_territoire.status_code == 200
    assert "Volley Français : Territoire &amp; Licences" in response.text or "Territoire" in r_territoire.text
    assert "Origine des licenciés" in r_territoire.text


def test_typer_unwrap_and_compute_all_options():
    """Vérifie que les options Typer par défaut ne provoquent pas d'AttributeError (OptionInfo object has no attribute strip)."""
    import typer
    from pyvolley.cli.commands.compute_cmd import _unwrap

    opt_none = typer.Option(None)
    opt_false = typer.Option(False)
    opt_true = typer.Option(True)
    opt_val = typer.Option("2025-2026")

    assert _unwrap(opt_none) is None
    assert _unwrap(opt_false) is False
    assert _unwrap(opt_true) is True
    assert _unwrap(opt_val) == "2025-2026"
    assert _unwrap(None) is None
    assert _unwrap(False) is False
    assert _unwrap("custom") == "custom"


def test_db_explorer_table_aliases():
    """Vérifie que les nouvelles tables statistiques sont bien résolues par l'explorateur DB."""
    from pyvolley.cli.db_explorer import _resolve_table, _model_map

    models = _model_map()
    assert "stats_club" in models
    assert "stats_geographiques" in models
    assert "joueur_licence_history" in models

    assert _resolve_table("geo") == "stats_geographiques"
    assert _resolve_table("stats_geo") == "stats_geographiques"
    assert _resolve_table("club_stats") == "stats_club"
    assert _resolve_table("licences") == "joueur_licence_history"
    assert _resolve_table("jms") == "joueur_match_stats"

