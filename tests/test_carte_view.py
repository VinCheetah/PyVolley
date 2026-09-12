"""
Tests pour la vue cartographique dédiée (/carte) et l'API des marqueurs.
"""

import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pyvolley.web.app import create_web_app
from pyvolley.api.dependencies import get_session
from pyvolley.database.models import Base, ClubDB, SalleClubDB


@pytest.fixture(scope="module")
def carte_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()

    club = ClubDB(
        nom="Saint-Chamond Volley",
        code_ffvb="0420001",
        departement="42",
        ligue="Ligue OCCITANIE",
        latitude=45.47,
        longitude=4.51,
    )
    session.add(club)
    session.flush()

    salle = SalleClubDB(
        club_id=club.id,
        numero=1,
        nom="Gymnase Boulloche",
        adresse="Rue de la Paix",
        ville="Saint-Chamond",
        latitude=45.471,
        longitude=4.512,
    )
    session.add(salle)
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


def test_carte_web_route(carte_client):
    response = carte_client.get("/carte")
    assert response.status_code == 200
    assert "Carte Interactive du Volleyball" in response.text
    assert "carteView" in response.text
    assert "carte-filter-bar" in response.text
    assert "Points répertoriés" in response.text
    # Vérifie que les clubs sont sélectionnés par défaut
    assert "entityType:     'club'" in response.text or 'entityType:     "club"' in response.text or "pill-club" in response.text
    # Vérifie que les matchs ne sont plus dans les options
    assert 'pill-match' not in response.text
    # Vérifie les zones géographiques
    assert "Métropole" in response.text
    assert "Corse" in response.text
    assert "Guyane" in response.text


def test_carte_web_route_with_filters(carte_client):
    response = carte_client.get("/carte?entity_type=club&departement=42")
    assert response.status_code == 200
    assert "carte-container" in response.text


def test_api_map_locations_ligue_filter(carte_client):
    # Test avec la ligue Occitanie
    response = carte_client.get("/api/map/locations?ligue=Ligue+OCCITANIE&limit=50")
    assert response.status_code == 200
    data = response.json()
    assert "markers" in data
    assert "center_lat" in data
    assert "center_lng" in data


def test_api_map_locations_entity_types(carte_client):
    for entity_type in ["club", "salle"]:
        response = carte_client.get(f"/api/map/locations?entity_type={entity_type}&limit=20")
        assert response.status_code == 200
        assert "public, max-age=60" in response.headers.get("cache-control", "")
        data = response.json()
        for marker in data["markers"]:
            assert marker["entity_type"] == entity_type


def test_api_map_locations_multi_entities(carte_client):
    response = carte_client.get("/api/map/locations?entity_type=club,salle&limit=50")
    assert response.status_code == 200
    data = response.json()
    types = {m["entity_type"] for m in data["markers"]}
    assert "club" in types or "salle" in types
    assert "match" not in types


def test_overseas_ligue_departments():
    from pyvolley.core.geo_data import get_departments_for_entite

    assert get_departments_for_entite("LIGU") == ["971"]
    assert get_departments_for_entite("LIMART") == ["972"]
    assert get_departments_for_entite("LIGY") == ["973"]
    assert get_departments_for_entite("LIRE") == ["974"]
    assert get_departments_for_entite("LIMY") == ["976"]


def test_department_names_mapping():
    from pyvolley.core.geo_data import DEPARTMENT_NAMES

    assert DEPARTMENT_NAMES["42"] == "Loire"
    assert DEPARTMENT_NAMES["69"] == "Rhône"
    assert DEPARTMENT_NAMES["38"] == "Isère"
    assert DEPARTMENT_NAMES["75"] == "Paris"
    assert DEPARTMENT_NAMES["971"] == "Guadeloupe"


def test_carte_without_season_filters(carte_client):
    response = carte_client.get("/carte")
    assert response.status_code == 200
    # Vérifie que le sélecteur de saison n'est plus présent
    assert "Saison sportive" not in response.text
    assert "Toutes saisons" not in response.text
    assert "saisonId" not in response.text
    # Vérifie que les départements ont leur nom dans le dropdown
    assert "42 - Loire" in response.text or "Loire" in response.text


def test_tile_layers_harmonization():
    from pathlib import Path
    static_js_dir = Path(__file__).parent.parent / "src" / "pyvolley" / "web" / "static" / "js"
    carte_js = (static_js_dir / "carte-view.js").read_text(encoding="utf-8")
    interactive_js = (static_js_dir / "interactive-map.js").read_text(encoding="utf-8")

    # Vérifie que "dark" et "light"/"voyager" sont absents des TILE_LAYERS
    assert "cartocdn" not in carte_js
    assert "cartocdn" not in interactive_js

    # Vérifie que "satellite" et "osm" sont présents
    assert "satellite:" in carte_js
    assert "osm:" in carte_js
    assert "satellite:" in interactive_js
    assert "osm:" in interactive_js

    # Vérifie la vue par défaut
    assert "currentTileKey:      'satellite'" in carte_js
    assert "currentTileKey:      'satellite'" in interactive_js

    # Vérifie la présence du calque actif et du dictionnaire départements
    assert "activePinLayer" in carte_js
    assert "activePinLayer" in interactive_js
    assert "DEPT_NAMES" in carte_js
    assert "DEPT_NAMES" in interactive_js


def test_map_zoom_and_movement_limits():
    from pathlib import Path
    static_js_dir = Path(__file__).parent.parent / "src" / "pyvolley" / "web" / "static" / "js"
    carte_js = (static_js_dir / "carte-view.js").read_text(encoding="utf-8")
    interactive_js = (static_js_dir / "interactive-map.js").read_text(encoding="utf-8")

    # Vérifie minZoom et maxBounds dans carte-view.js
    assert "minZoom:" in carte_js
    assert "maxBounds:" in carte_js
    assert "maxBoundsViscosity:" in carte_js
    assert "DEFAULT_MAP_BOUNDS" in interactive_js or "bounds:" in carte_js

    # Vérifie minZoom et maxBounds dans interactive-map.js
    assert "minZoom: 5" in interactive_js
    assert "maxBounds: DEFAULT_MAP_BOUNDS" in interactive_js
    assert "maxBoundsViscosity: 0.85" in interactive_js



