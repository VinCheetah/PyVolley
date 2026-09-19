"""Tests pour le moteur de géocodage haute précision avec contraintes départementales."""

import pytest
from unittest.mock import MagicMock

from pyvolley.core.geo_data import (
    DEPARTMENT_CENTROIDS,
    DEPARTMENT_NAMES,
    haversine_distance_km,
    is_coordinate_in_department,
)
from pyvolley.core.geocoding import (
    GeocodingCache,
    GeocodingResult,
    audit_geocoding_consistency,
    clean_street_address,
    extract_postal_and_city,
    geocode_address,
)


def test_haversine_distance():
    """Vérifie le calcul de distance entre Paris et Lyon (~390 km)."""
    paris = (48.8566, 2.3522)
    lyon = (45.7640, 4.8357)
    dist = haversine_distance_km(paris[0], paris[1], lyon[0], lyon[1])
    assert 385 < dist < 400


def test_is_coordinate_in_department():
    """Vérifie la détection de position dans ou hors d'un département."""
    # Lyon dans le Rhône (69)
    in_dept, dist = is_coordinate_in_department(45.7640, 4.8357, "69")
    assert in_dept is True
    assert dist < 50.0

    # Lyon n'est pas dans les Bouches-du-Rhône (13) (~250 km de Marseille)
    in_dept, dist = is_coordinate_in_department(45.7640, 4.8357, "13")
    assert in_dept is False
    assert dist > 200.0

    # Aucun département fourni
    in_dept, dist = is_coordinate_in_department(45.7640, 4.8357, None)
    assert in_dept is True


def test_geocode_address_dept_correction():
    """Vérifie que la salle de Guipel (35) avec CP erroné (33113) est bien localisée en Ille-et-Vilaine."""
    # Guipel est en Ille-et-Vilaine (35), mais l'adresse FFVB contenait 33113 Saint-Symphorien
    res = geocode_address(
        adresse="LA FRETAIS",
        ville="33113 ST SYMPHORIEN",
        nom="SALLE ONYX",
        departement="35",
        ligue="BRETAGNE",
        use_cache=False,
    )
    assert res is not None
    # Doit être en Bretagne / Ille-et-Vilaine, pas en Gironde (33)
    assert res.latitude > 47.5
    assert res.longitude < -1.0
    in_35, dist = is_coordinate_in_department(res.latitude, res.longitude, "35")
    assert in_35 is True


def test_geocode_address_fallback_dept_centroid():
    """Vérifie qu'une commune introuvable (sans adresse de voirie) retombe sur le centroïde de son département."""
    res = geocode_address(
        adresse=None,
        ville="COMMUNE IMAGINAIRE",
        departement="42",
        use_cache=False,
    )
    assert res is not None
    assert res.match_type == "dept_centroid"
    assert res.departement == "42"
    centroid_42 = DEPARTMENT_CENTROIDS["42"]
    assert abs(res.latitude - centroid_42[0]) < 0.1
    assert abs(res.longitude - centroid_42[1]) < 0.1


def test_geocoding_cache_dept_validation(tmp_path):
    """Vérifie que le cache invalide un ancien résultat qui ne correspond pas au département."""
    cache_file = tmp_path / "test_cache.json"
    cache = GeocodingCache(cache_file=cache_file)

    # Enregistrer un résultat en Gironde (33)
    gironde_res = GeocodingResult(
        latitude=44.432,
        longitude=-0.494,
        label="La Forêt 33113 Saint-Symphorien",
        score=0.6,
        match_type="housenumber",
        city="Saint-Symphorien",
        postcode="33113",
        departement="33",
    )
    cache.set("la fretais st symphorien", "33113", gironde_res)

    # Récupération sans département : renvoie le résultat en cache
    assert cache.get("la fretais st symphorien", "33113") is not None

    # Récupération avec département attendu 35 : doit rejeter le cache invalide
    assert cache.get("la fretais st symphorien", "33113", departement="35") is None


def test_audit_consistency_mock():
    """Vérifie la fonction d'audit avec session SQLAlchemy mockée."""
    mock_session = MagicMock()

    # Salle valide
    mock_salle_ok = MagicMock()
    mock_salle_ok.id = 1
    mock_salle_ok.nom = "Salle 1"
    mock_salle_ok.latitude = 45.7640
    mock_salle_ok.longitude = 4.8357
    mock_salle_ok.club.departement = "69"
    mock_salle_ok.club.code_ffvb = "0690001"

    # Salle aberrante
    mock_salle_bad = MagicMock()
    mock_salle_bad.id = 2
    mock_salle_bad.nom = "Salle Onyx"
    mock_salle_bad.adresse = "La Fretais"
    mock_salle_bad.ville = "33113 ST SYMPHORIEN"
    mock_salle_bad.latitude = 44.432  # En Gironde
    mock_salle_bad.longitude = -0.494
    mock_salle_bad.club.departement = "35"  # Club d'Ille-et-Vilaine
    mock_salle_bad.club.code_ffvb = "0351502"

    mock_session.query.return_value.all.side_effect = [
        [mock_salle_ok, mock_salle_bad],  # Salles
        [],  # Clubs
    ]

    stats = audit_geocoding_consistency(mock_session, max_distance_km=120.0)
    assert stats["salles_total"] == 2
    assert stats["salles_geocoded"] == 2
    assert len(stats["salle_outliers"]) == 1
    assert stats["salle_outliers"][0]["id"] == 2
    assert stats["salle_outliers"][0]["expected_dept"] == "35"
