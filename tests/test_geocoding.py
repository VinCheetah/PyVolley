"""
Tests unitaires pour le moteur de géocodage haute précision.

Couvre :
- Extraction code postal et commune
- Nettoyage des libellés de voirie FFVB
- Cache de géocodage persistant
- Stratégie de repli en cascade (cascade fallback)
- Géocodage des entités SalleClubDB et ClubDB
"""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pyvolley.core.geocoding import (
    GeocodingCache,
    GeocodingResult,
    clean_street_address,
    extract_postal_and_city,
    geocode_address,
    geocode_club_entity,
    geocode_salle_entity,
)
from pyvolley.database.models import Base, ClubDB, SalleClubDB


# ── Utilitaires de test ─────────────────────────────────────────────

class TestAddressCleaning:
    """Tests du nettoyage des adresses et communes."""

    def test_extract_postal_and_city_standard(self):
        pc, city = extract_postal_and_city("42480 LA FOUILLOUSE")
        assert pc == "42480"
        assert city == "LA FOUILLOUSE"

    def test_extract_postal_and_city_with_dash(self):
        pc, city = extract_postal_and_city("69110 SAINTE-FOY-LES-LYON")
        assert pc == "69110"
        assert city == "SAINTE-FOY-LES-LYON"

    def test_extract_postal_and_city_no_postcode(self):
        pc, city = extract_postal_and_city("GRENOBLE")
        assert pc is None
        assert city == "GRENOBLE"

    def test_extract_postal_and_city_empty(self):
        pc, city = extract_postal_and_city("")
        assert pc is None
        assert city is None
        pc, city = extract_postal_and_city(None)
        assert pc is None
        assert city is None

    def test_clean_street_address_noise_removal(self):
        assert clean_street_address("15 RUE PAUL LAPIE, PETITE SALLE 1") == "15 RUE PAUL LAPIE"
        assert clean_street_address("ALLEE DE GEVE, ZI L'ARGENTIERE") == "ALLEE DE GEVE"
        assert clean_street_address("9 IMP. GEORGES CLEMENCEAU,") == "9 IMP. GEORGES CLEMENCEAU"
        assert clean_street_address("AVENUE DE LA COISE,") == "AVENUE DE LA COISE"

    def test_clean_street_address_empty(self):
        assert clean_street_address("") is None
        assert clean_street_address(None) is None


class TestGeocodingCache:
    """Tests du cache disque/mémoire."""

    def test_cache_set_and_get(self, tmp_path):
        cache_file = tmp_path / "test_cache.json"
        cache = GeocodingCache(cache_file=cache_file)

        res = GeocodingResult(
            latitude=45.50,
            longitude=4.31,
            label="33 Rue Saint Just",
            score=0.9,
            match_type="housenumber",
            city="La Fouillouse",
            postcode="42480",
        )

        cache.set("33 Rue Saint Just La Fouillouse", "42480", res)
        cached = cache.get("33 Rue Saint Just La Fouillouse", "42480")
        assert cached is not None
        assert cached.latitude == 45.50
        assert cached.longitude == 4.31

        # Test persistance sur disque
        cache.save()
        assert cache_file.exists()

        # Nouveau cache qui recharge depuis le fichier
        new_cache = GeocodingCache(cache_file=cache_file)
        reloaded = new_cache.get("33 Rue Saint Just La Fouillouse", "42480")
        assert reloaded is not None
        assert reloaded.score == 0.9

    def test_cache_negative_entry_and_persistence(self, tmp_path):
        cache_file = tmp_path / "test_neg_cache.json"
        cache = GeocodingCache(cache_file=cache_file)

        # Enregistrer un résultat introuvable
        cache.set_not_found("Adresse Introuvable Inexistante", "99999")
        assert cache.is_not_found("Adresse Introuvable Inexistante", "99999") is True
        assert cache.get("Adresse Introuvable Inexistante", "99999") is None

        cache.save()
        new_cache = GeocodingCache(cache_file=cache_file)
        assert new_cache.is_not_found("Adresse Introuvable Inexistante", "99999") is True
        assert new_cache.get("Adresse Introuvable Inexistante", "99999") is None


class TestGeocodingCascade:
    """Tests de la logique en cascade avec API BAN mockée."""

    @patch("pyvolley.core.geocoding._call_ban_api")
    def test_direct_match(self, mock_ban):
        mock_ban.return_value = GeocodingResult(
            latitude=45.5022,
            longitude=4.3119,
            label="33 Rue Saint Just 42480 La Fouillouse",
            score=0.95,
            match_type="housenumber",
            city="La Fouillouse",
            postcode="42480",
        )

        res = geocode_address(
            adresse="33 RUE DE ST-JUST",
            ville="42480 LA FOUILLOUSE",
            use_cache=False,
        )
        assert res is not None
        assert res.latitude == 45.5022
        assert res.longitude == 4.3119
        assert res.match_type == "housenumber"

    @patch("pyvolley.core.geocoding._call_ban_api")
    def test_fallback_without_postcode_on_mistyped_cp(self, mock_ban):
        """Simule un premier échec avec code postal erroné, puis succès sans code postal."""
        def side_effect(query, postcode=None, city=None, result_type=None, timeout=6.0):
            if postcode == "63140":
                return None
            if postcode is None and "chamalieres" in query.lower():
                return GeocodingResult(
                    latitude=45.7694,
                    longitude=3.0676,
                    label="15 Rue Paul Lapie 63400 Chamalières",
                    score=0.92,
                    match_type="housenumber",
                    city="Chamalières",
                    postcode="63400",
                )
            return None

        mock_ban.side_effect = side_effect

        res = geocode_address(
            adresse="15 RUE PAUL LAPIE",
            ville="63140 CHAMALIERES",
            use_cache=False,
        )
        assert res is not None
        assert res.latitude == 45.7694
        assert res.postcode == "63400"

    @patch("pyvolley.core.geocoding._call_ban_api")
    def test_fallback_with_nom_salle(self, mock_ban):
        """Si l'adresse seule ne donne rien, le nom de la salle permet de trouver."""
        def side_effect(query, postcode=None, city=None, result_type=None, timeout=6.0):
            if "clemenceau" in query.lower():
                return GeocodingResult(
                    latitude=45.4278,
                    longitude=4.4115,
                    label="Gymnase Clémenceau 42100 Saint-Étienne",
                    score=0.88,
                    match_type="street",
                    city="Saint-Étienne",
                    postcode="42100",
                )
            return None

        mock_ban.side_effect = side_effect

        res = geocode_address(
            adresse="Lieu-dit Inconnu",
            ville="42100 SAINT-ETIENNE",
            nom="GYMNASE CLEMENCEAU",
            use_cache=False,
        )
        assert res is not None
        assert res.latitude == 45.4278

    @patch("pyvolley.core.geocoding._call_ban_api")
    def test_negative_cache_skips_network(self, mock_ban, tmp_path, monkeypatch):
        """Vérifie qu'une adresse introuvable est mise en cache négatif et ne rappelle plus l'API."""
        cache_file = tmp_path / "neg_test_cache.json"
        cache = GeocodingCache(cache_file)
        monkeypatch.setattr("pyvolley.core.geocoding.get_geocoding_cache", lambda: cache)

        mock_ban.return_value = None

        # 1er appel : tente la BAN, échoue, enregistre dans le cache négatif
        res1 = geocode_address("Rue Totalement Inexistante", "00000 Ville Inconnue", use_cache=True)
        assert res1 is None
        assert mock_ban.call_count > 0

        # 2e appel : consulte le cache négatif, ne fait aucun appel réseau BAN
        mock_ban.reset_mock()
        res2 = geocode_address("Rue Totalement Inexistante", "00000 Ville Inconnue", use_cache=True)
        assert res2 is None
        assert mock_ban.call_count == 0

    @patch("pyvolley.core.geocoding._call_nominatim_api")
    @patch("pyvolley.core.geocoding._call_ban_api")
    def test_nominatim_disabled_by_default(self, mock_ban, mock_nom):
        """Vérifie que Nominatim n'est PAS appelé quand allow_nominatim=False."""
        mock_ban.return_value = None
        mock_nom.return_value = GeocodingResult(
            latitude=48.8566,
            longitude=2.3522,
            label="Paris OSM",
            score=0.7,
            match_type="fallback",
            provider="nominatim",
        )

        res = geocode_address("Adresse Introuvable", "Paris", use_cache=False, allow_nominatim=False)
        assert res is None
        assert mock_nom.call_count == 0

        # Avec allow_nominatim=True, Nominatim doit être appelé en repli
        res_nom = geocode_address("Adresse Introuvable", "Paris", use_cache=False, allow_nominatim=True)
        assert res_nom is not None
        assert res_nom.provider == "nominatim"
        assert mock_nom.call_count == 1


class TestEntityGeocoding:
    """Tests de mise à jour des entités SQLAlchemy."""

    @pytest.fixture
    def session(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        s = Session()
        yield s
        s.close()

    @patch("pyvolley.core.geocoding.geocode_address")
    def test_geocode_salle_updates_lat_lng(self, mock_geo, session):
        mock_geo.return_value = GeocodingResult(
            latitude=45.1202,
            longitude=5.6925,
            label="5 Avenue de la Ridelet 38640 Claix",
            score=0.95,
            match_type="housenumber",
        )

        club = ClubDB(nom="CLAIX VOLLEY", code_ffvb="0380001", ville="CLAIX")
        session.add(club)
        session.flush()

        salle = SalleClubDB(
            club_id=club.id,
            numero=1,
            nom="POMPIDOU",
            adresse="5 AVENUE DE LA RIDELET",
            ville="38640 CLAIX",
        )
        session.add(salle)
        session.flush()

        res = geocode_salle_entity(salle, session=session, commit=True)
        assert res is not None
        assert salle.latitude == 45.1202
        assert salle.longitude == 5.6925

    @patch("pyvolley.core.geocoding.geocode_address")
    def test_geocode_club_uses_main_venue_not_correspondant(self, mock_geo, session):
        """Vérifie qu'un club prend strictement les coordonnées de sa salle principale et ne géocode pas le correspondant."""
        mock_geo.return_value = GeocodingResult(
            latitude=45.4336,
            longitude=4.3957,
            label="7 Allée Shakespeare 42100 Saint-Étienne",
            score=0.97,
            match_type="housenumber",
        )

        club = ClubDB(
            nom="CASE VOLLEY",
            code_ffvb="0420002",
            ville="SAINT-ETIENNE",
            correspondant_adresse="780 CHEMIN DE PLANTOU",
            correspondant_ville="42660 PLANFOY",
        )
        session.add(club)
        session.flush()

        salle1 = SalleClubDB(
            club_id=club.id,
            numero=1,
            nom="POURTIER VILLEBOEUF",
            adresse="7 ALLEE SHAKESPEARE",
            ville="42100 SAINT-ETIENNE",
        )
        session.add(salle1)
        session.flush()

        res = geocode_club_entity(club, session=session, commit=True)
        assert res is not None
        assert res.match_type == "main_venue"
        assert club.latitude == 45.4336
        assert club.longitude == 4.3957

        # S'assurer que geocode_address n'a JAMAIS été appelé avec l'adresse du correspondant
        for call in mock_geo.call_args_list:
            args, kwargs = call
            assert "780 CHEMIN DE PLANTOU" not in str(args) and "780 CHEMIN DE PLANTOU" not in str(kwargs)
            assert "PLANFOY" not in str(args) and "PLANFOY" not in str(kwargs)

    @patch("pyvolley.core.geocoding.geocode_address")
    def test_geocode_club_without_salle_uses_city_not_correspondant(self, mock_geo, session):
        """Sans salle déclarée, le club se replie sur sa commune (club.ville) et jamais sur le correspondant."""
        mock_geo.return_value = GeocodingResult(
            latitude=45.4397,
            longitude=4.3872,
            label="Saint-Étienne",
            score=0.85,
            match_type="municipality",
        )

        club = ClubDB(
            nom="CLUB SANS SALLE",
            code_ffvb="0429999",
            ville="SAINT-ETIENNE",
            correspondant_adresse="10 RUE PRIVEE",
            correspondant_ville="42000 SAINT-ETIENNE",
        )
        session.add(club)
        session.flush()

        res = geocode_club_entity(club, session=session, commit=True)
        assert res is not None
        assert club.latitude == 45.4397
        mock_geo.assert_called_once_with(adresse=None, ville="SAINT-ETIENNE", nom="CLUB SANS SALLE")

