"""Tests pour la géolocalisation et l'API de carte interactive."""

import pytest
from pyvolley.core.geo_data import (
    resolve_entity_coordinates,
    extract_dept_from_address_or_city,
    extract_dept_from_postal_code,
    DEPARTMENT_CENTROIDS,
    CITY_COORDINATES,
)
from pyvolley.api.routes.map import get_map_locations


def test_resolve_coordinates_keeps_exact() -> None:
    coords = resolve_entity_coordinates(
        latitude=45.7578,
        longitude=4.8320,
        ville="Lyon",
        departement="69",
        entity_id=42,
    )
    assert coords == (45.7578, 4.8320)


def test_resolve_coordinates_known_city() -> None:
    coords = resolve_entity_coordinates(
        latitude=None,
        longitude=None,
        ville="GRENOBLE",
        departement=None,
        entity_id=1,
    )
    assert coords is not None
    # Proche des coordonnées réelles de Grenoble (45.188, 5.724)
    assert abs(coords[0] - 45.188) < 0.05
    assert abs(coords[1] - 5.724) < 0.05


def test_resolve_coordinates_city_with_postal_code() -> None:
    coords = resolve_entity_coordinates(
        latitude=None,
        longitude=None,
        ville="38600 FONTAINE",
        departement=None,
        entity_id=5,
    )
    assert coords is not None
    # Proche des coordonnées de Fontaine (45.193, 5.685)
    assert abs(coords[0] - 45.193) < 0.05
    assert abs(coords[1] - 5.685) < 0.05


def test_extract_dept_from_postal_code() -> None:
    assert extract_dept_from_postal_code("38000") == "38"
    assert extract_dept_from_postal_code("69400") == "69"
    assert extract_dept_from_postal_code("75001") == "75"
    assert extract_dept_from_postal_code("20000") == "2A"
    assert extract_dept_from_postal_code("20200") == "2B"
    assert extract_dept_from_postal_code("97100") == "971"
    assert extract_dept_from_postal_code("97400") == "974"


def test_extract_dept_from_address_or_city() -> None:
    assert extract_dept_from_address_or_city(ville="38600 FONTAINE") == "38"
    assert extract_dept_from_address_or_city(adresse="12 Rue Principale, 69002 Lyon") == "69"
    assert extract_dept_from_address_or_city(ville="GRENOBLE") == "38"
    assert extract_dept_from_address_or_city(ville="Inconnue") is None


def test_all_101_french_departments_have_centroids() -> None:
    # 96 départements métropolitains + 5 DROM = 101
    assert len(DEPARTMENT_CENTROIDS) >= 101
    for dept_code in ["01", "13", "33", "38", "59", "69", "75", "2A", "2B", "971", "974"]:
        assert dept_code in DEPARTMENT_CENTROIDS
        lat, lng = DEPARTMENT_CENTROIDS[dept_code]
        assert -25.0 <= lat <= 52.0
        assert -65.0 <= lng <= 60.0


def test_resolve_coordinates_department_fallback() -> None:
    coords_paris = resolve_entity_coordinates(departement="75", entity_id=10)
    assert coords_paris is not None
    assert abs(coords_paris[0] - 48.8566) < 0.1
    assert abs(coords_paris[1] - 2.3522) < 0.1

    coords_nord = resolve_entity_coordinates(departement="59", entity_id=20)
    assert coords_nord is not None
    assert abs(coords_nord[0] - 50.50) < 0.1


def test_get_map_locations_endpoint_scoping(test_session) -> None:
    import asyncio
    # Test scoping avec session SQLite
    res_all = asyncio.run(get_map_locations(session=test_session))
    assert res_all is not None
    assert isinstance(res_all.markers, list)

    # Test avec filtre departement
    res_dept = asyncio.run(get_map_locations(departement="38", session=test_session))
    assert res_dept is not None
    assert isinstance(res_dept.markers, list)

    # Test avec filtre multi-départements
    res_multi = asyncio.run(get_map_locations(departements="38,69", session=test_session))
    assert res_multi is not None
    assert len(res_multi.markers) >= len(res_dept.markers)

