"""
Tests pour la vue cartographique dédiée (/carte) et l'API des marqueurs.
"""

from starlette.testclient import TestClient
from pyvolley.web.app import create_web_app


def test_carte_web_route():
    app = create_web_app()
    client = TestClient(app)

    response = client.get("/carte")
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


def test_carte_web_route_with_filters():
    app = create_web_app()
    client = TestClient(app)

    response = client.get("/carte?entity_type=club&departement=69")
    assert response.status_code == 200
    assert "carte-container" in response.text


def test_api_map_locations_ligue_filter():
    app = create_web_app()
    client = TestClient(app)

    # Test avec la ligue Occitanie
    response = client.get("/api/map/locations?ligue=Ligue+OCCITANIE&limit=50")
    assert response.status_code == 200
    data = response.json()
    assert "markers" in data
    assert "center_lat" in data
    assert "center_lng" in data


def test_api_map_locations_entity_types():
    app = create_web_app()
    client = TestClient(app)

    for entity_type in ["club", "salle"]:
        response = client.get(f"/api/map/locations?entity_type={entity_type}&limit=20")
        assert response.status_code == 200
        data = response.json()
        for marker in data["markers"]:
            assert marker["entity_type"] == entity_type
