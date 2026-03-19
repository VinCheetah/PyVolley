"""Tests ciblés pour le fallback géographique de la carte interactive."""

from pyvolley.api.routes.map import _resolve_marker_coords


def test_resolve_marker_coords_keeps_exact_coordinates() -> None:
    coords = _resolve_marker_coords(
        latitude=45.7578,
        longitude=4.8320,
        ville="Lyon",
        departement="69",
        entity_id=42,
    )

    assert coords == (45.7578, 4.8320)


def test_resolve_marker_coords_uses_department_centroid_with_jitter() -> None:
    coords = _resolve_marker_coords(
        latitude=None,
        longitude=None,
        ville=None,
        departement="69",
        entity_id=10,
    )

    assert coords is not None
    lat, lng = coords
    assert 45.5 < lat < 46.0
    assert 4.6 < lng < 5.1


def test_resolve_marker_coords_infers_department_from_city() -> None:
    coords = _resolve_marker_coords(
        latitude=None,
        longitude=None,
        ville="Lyon",
        departement=None,
        entity_id=11,
    )

    assert coords is not None


def test_resolve_marker_coords_returns_none_when_no_fallback_available() -> None:
    coords = _resolve_marker_coords(
        latitude=None,
        longitude=None,
        ville="Ville Inconnue",
        departement=None,
        entity_id=1,
    )

    assert coords is None
