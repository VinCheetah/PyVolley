"""
Tests pour les améliorations du parser : niveau, organisateur, noms de clubs.
"""

import pytest

from pyvolley.parsers.utils import (
    detect_niveau,
    extract_organisateur,
    extract_club_info,
    normalize_club_name,
    extract_competition_code,
)
from pyvolley.parsers.extractors.header import extract_header
from pyvolley.core.models import Match, Niveau


# =====================================================================
# detect_niveau
# =====================================================================


class TestDetectNiveau:
    """Tests pour la détection du niveau de compétition."""

    @pytest.mark.parametrize("competition,expected", [
        ("EMA - ELITE MASCULINE - POULE A", "ELITE"),
        ("EFA - ELITE FEMININE - POULE A", "ELITE"),
        ("BFC - M13F - ELITE - PHASE 2 - POULE C", "ELITE"),
    ])
    def test_elite(self, competition, expected):
        assert detect_niveau(competition) == expected

    @pytest.mark.parametrize("competition,expected", [
        ("2FA - NATIONALE 2 FEMININE - POULE A", "NATIONALE"),
        ("3FF - NATIONALE 3 FEMININE POULE F", "NATIONALE"),
        ("BFA - COUPE DE FRANCE M13 FEMININ POULE A", "NATIONALE"),
    ])
    def test_nationale(self, competition, expected):
        assert detect_niveau(competition) == expected

    @pytest.mark.parametrize("competition,expected", [
        ("PFA - CHAMPIONNAT PRE-NATIONAL SENIOR FEMININ : POULE A", "PRE_NATIONALE"),
        ("AFA - ACCESSION REGIONALE SENIOR FEM POULE A", "PRE_NATIONALE"),
        ("AFA - Accession Régionale Féminines Poule A", "PRE_NATIONALE"),
    ])
    def test_pre_nationale(self, competition, expected):
        assert detect_niveau(competition) == expected

    @pytest.mark.parametrize("competition,expected", [
        ("1FA - CHAMPIONNAT REGIONAL 1 SENIOR FEMININ : POULE A", "REGIONALE"),
        ("1FA - REGIONALE 1 FEMININES HDF POULE A", "REGIONALE"),
        ("BFA - TOURNOI REGIONAL M13 FEMININS POULE A", "REGIONALE"),
        ("RMA - CHAMPIONNAT REGIONAL SENIOR MASCULIN : POULE A", "REGIONALE"),
    ])
    def test_regionale(self, competition, expected):
        assert detect_niveau(competition) == expected

    @pytest.mark.parametrize("competition,expected", [
        ("2CF - 2EME PHASE COMPETFUN 6X6 CONFIRME 2 POULE F", "LOISIR"),
        ("LAR - LOISIR MIXTE ARGENT", "LOISIR"),
        ("LCA - LOISIR MIXTE CUIVRE - POULE HAUTE", "LOISIR"),
    ])
    def test_loisir(self, competition, expected):
        assert detect_niveau(competition) == expected

    def test_fallback_organisation_nationale(self):
        """Compétition sans mot-clé + organisateur national → NATIONALE."""
        assert detect_niveau("XYZ - TRUC", "Compétitions Nationales") == "NATIONALE"

    def test_fallback_organisation_ligue(self):
        """Compétition sans mot-clé + ligue → REGIONALE."""
        assert detect_niveau("XYZ - TRUC", "Ligue ILE-DE-FRANCE") == "REGIONALE"

    def test_fallback_organisation_comite(self):
        """Compétition sans mot-clé + comité → DEPARTEMENTALE."""
        assert detect_niveau("18F - M18F 6x6 75", "Comité Seine Paris") == "DEPARTEMENTALE"

    def test_none_when_unknown(self):
        assert detect_niveau(None) is None
        assert detect_niveau("") is None


# =====================================================================
# extract_organisateur
# =====================================================================


class TestExtractOrganisateur:
    """Tests pour l'extraction de l'organisateur."""

    def test_competitions_nationales_seniors(self):
        line = "Compétitions Nationales SENIORS VENELLES PROVENCE VOLLEY MARSEILLE"
        assert extract_organisateur(line) == "Compétitions Nationales SENIORS"

    def test_competitions_nationales_jeunes(self):
        line = "Compétitions Nationales JEUNES AS SP ENTREMONT RIXHEIM"
        assert extract_organisateur(line) == "Compétitions Nationales JEUNES"

    def test_comite_seine_paris(self):
        line = "Comité Seine Paris SCUF2 SCNP2"
        assert extract_organisateur(line) == "Comité Seine Paris"

    def test_comite_hauts_de_seine(self):
        line = "Comité des Hauts-de-Seine ACBB 3 ANTONY VOLLEY 3"
        assert extract_organisateur(line) == "Comité des Hauts-de-Seine"

    def test_comite_nord(self):
        line = "Comité Nord CAMBRAI 2 CYSOING 3"
        assert extract_organisateur(line) == "Comité Nord"

    def test_comite_rhone_metropole(self):
        line = "Comité du Rhône Métropole de Lyon CISGO 1 CRAPONNE TEAM"
        assert extract_organisateur(line) == "Comité du Rhône Métropole de Lyon"

    def test_ligue_ile_de_france(self):
        line = "Ligue ILE-DE-FRANCE JEANNE D ARC DE ROSNY US LOGNES"
        assert extract_organisateur(line) == "Ligue ILE-DE-FRANCE"

    def test_ligue_hauts_de_france(self):
        line = "Ligue HAUTS-DE-FRANCE HALLUIN VM 2 LYS LEZ LANNOY 2"
        assert extract_organisateur(line) == "Ligue HAUTS-DE-FRANCE"

    def test_ligue_auvergne_rhone_alpes(self):
        line = "Ligue AUVERGNE-RHÔNE-ALPES VB VILLEFRANCHE VC MEXIMIEUX"
        assert extract_organisateur(line) == "Ligue AUVERGNE-RHÔNE-ALPES"

    def test_ligue_nouvelle_aquitaine(self):
        line = "Ligue NOUVELLE AQUITAINE CEP POITIERS/ST BENOIT V.B."
        assert extract_organisateur(line) == "Ligue NOUVELLE AQUITAINE"

    def test_none_for_empty(self):
        assert extract_organisateur("") is None
        assert extract_organisateur(None) is None


# =====================================================================
# normalize_club_name
# =====================================================================


class TestNormalizeClubName:
    """Tests pour la normalisation des noms de clubs."""

    def test_volley_ball_with_hyphen(self):
        assert normalize_club_name("SURESNES VOLLEY-BALL CLUB") == "SURESNES VB CLUB"

    def test_volley_ball_without_hyphen(self):
        assert normalize_club_name("LA ROCHELLE VOLLEY BALL") == "LA ROCHELLE VB"

    def test_vb_dot_trailing(self):
        assert normalize_club_name("AMICALE VILLENEUVE LA GARENNE V.B.") == "AMICALE VILLENEUVE LA GARENNE VB"

    def test_vb_dot_inside(self):
        assert normalize_club_name("CEP POITIERS/ST BENOIT V.B.") == "CEP POITIERS/ST BENOIT VB"

    def test_already_vb(self):
        assert normalize_club_name("VB VILLEFRANCHE") == "VB VILLEFRANCHE"

    def test_no_change_needed(self):
        assert normalize_club_name("ACBB") == "ACBB"

    def test_empty(self):
        assert normalize_club_name("") == ""


# =====================================================================
# extract_club_info
# =====================================================================


class TestExtractClubInfo:
    """Tests pour l'extraction du nom de club et numéro d'équipe."""

    def test_team_number_simple(self):
        club, num = extract_club_info("ANTONY VOLLEY 3")
        assert club == "ANTONY VOLLEY"
        assert num == 3

    def test_team_number_with_zero(self):
        club, num = extract_club_info("PARIS UC 02")
        assert club == "PARIS UC"
        assert num == 2

    def test_team_number_one(self):
        club, num = extract_club_info("CISGO 1")
        assert club == "CISGO"
        assert num == 1

    def test_department_code_not_team_number(self):
        """Les numéros >= 10 sont des codes départementaux."""
        club, num = extract_club_info("ASNIERES VOLLEY 92")
        assert club == "ASNIERES VOLLEY 92"
        assert num is None

    def test_department_code_13(self):
        club, num = extract_club_info("MARSEILLE VOLLEY 13")
        assert club == "MARSEILLE VOLLEY 13"
        assert num is None

    def test_no_number(self):
        club, num = extract_club_info("RUEIL AC")
        assert club == "RUEIL AC"
        assert num is None

    def test_vb_normalization_applied(self):
        club, num = extract_club_info("US LOGNES VOLLEY-BALL 2")
        assert club == "US LOGNES VB"
        assert num == 2

    def test_vb_in_name_no_number(self):
        club, num = extract_club_info("SURESNES VOLLEY-BALL CLUB")
        assert club == "SURESNES VB CLUB"
        assert num is None

    def test_glued_number(self):
        """Numéro collé au nom (ex: VB14) → pas de numéro."""
        club, num = extract_club_info("VB14")
        assert club == "VB14"
        assert num is None

    def test_empty(self):
        club, num = extract_club_info("")
        assert club == ""
        assert num is None


# =====================================================================
# extract_header (intégration)
# =====================================================================


class TestExtractHeader:
    """Tests d'intégration pour l'extraction du header."""

    def test_nationale_header(self):
        lines = [
            "2FA - NATIONALE 2 FEMININE - POULE A Match: 2FA002 - Jour: 01",
            "Ville: VENELLES Samedi 27 Septembre 2025 à 19h30",
            "Salle: HALLE POLYVALENTE SENIOR | FEMININE",
            "Compétitions Nationales SENIORS VENELLES PROVENCE VOLLEY",
        ]
        h = extract_header(lines)
        assert h["competition"] == "2FA - NATIONALE 2 FEMININE - POULE A"
        assert h["niveau"] == "NATIONALE"
        assert h["organisateur"] == "Compétitions Nationales SENIORS"
        assert h["code_match"] == "2FA002"
        assert h["genre"] == "FEMININ"
        assert h["categorie"] == "SENIOR"

    def test_regionale_header(self):
        lines = [
            "1FA - CHAMPIONNAT REGIONAL 1 SENIOR FEMININ : POULE A Match: 1FAA001 - Jour: 01",
            "Ville: ROSNY SOUS BOIS Samedi 04 Octobre 2025 à 20h00",
            "Salle: GABRIEL THIBAULT SENIOR | FEMININE",
            "Ligue ILE-DE-FRANCE JEANNE D ARC DE ROSNY US LOGNES VOLLEY-BALL 2",
        ]
        h = extract_header(lines)
        assert h["niveau"] == "REGIONALE"
        assert h["organisateur"] == "Ligue ILE-DE-FRANCE"
        assert h["ligue"] == "Ligue ILE-DE-FRANCE"

    def test_departementale_header(self):
        lines = [
            "18F - M18F 6x6 75 Match: 18FA001 - Jour: 01",
            "Ville: Samedi 29 Novembre 2025 à 14h30",
            "Salle: HENRY DE MONTHERLANT M18 | FEMININE",
            "Comité Seine Paris SCUF2 SCNP2",
        ]
        h = extract_header(lines)
        assert h["niveau"] == "DEPARTEMENTALE"
        assert h["organisateur"] == "Comité Seine Paris"

    def test_loisir_header(self):
        lines = [
            "2CF - 2EME PHASE COMPETFUN 6X6 CONFIRME 2 POULE F Match: 2CFA015 - Jour: 04",
            "Ville: OULLINS Lundi 02 Février 2026",
            "Salle: GYMNASE DU PARC CHABRIERES SENIOR | MIXTE",
            "Comité du Rhône Métropole de Lyon CISGO 1 CRAPONNE TEAM AMELINE",
        ]
        h = extract_header(lines)
        assert h["niveau"] == "LOISIR"
        assert h["organisateur"] == "Comité du Rhône Métropole de Lyon"


# =====================================================================
# Niveau Enum sur Match
# =====================================================================


class TestMatchNiveauField:
    """Tests que le niveau est correctement porté dans le modèle Match."""

    def test_match_with_niveau(self):
        m = Match(
            code_match="TEST001",
            niveau=Niveau.REGIONALE,
            organisateur="Ligue ILE-DE-FRANCE",
        )
        assert m.niveau == Niveau.REGIONALE
        assert m.organisateur == "Ligue ILE-DE-FRANCE"

    def test_match_without_niveau(self):
        m = Match(code_match="TEST002")
        assert m.niveau is None
        assert m.organisateur is None

    def test_all_niveaux(self):
        for niv in Niveau:
            m = Match(code_match="T001", niveau=niv)
            assert m.niveau == niv
