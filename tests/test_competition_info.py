"""
Tests pour le module competition_info.

Tests unitaires pour :
- parse_competition_name : analyse statique des noms de compétitions FFVB
- enrich_competition_meta_from_code : déduction de métadonnées depuis un code
- Détection de genre, catégorie, niveau, division, type, phase, poule_lettre
"""

import pytest

from pyvolley.scrapers.ffvb.competition_info import (
    CompetitionMeta,
    parse_competition_name,
    enrich_competition_meta_from_code,
)


# =====================================================================
# parse_competition_name — Genre
# =====================================================================


class TestParseCompetitionNameGenre:
    """Tests de détection du genre."""

    @pytest.mark.parametrize("nom,expected", [
        ("ELITE MASCULINE - POULE A", "MASCULIN"),
        ("NATIONALE 2 FEMININE - POULE A", "FEMININ"),
        ("NATIONALE 3 MASCULINE POULE F", "MASCULIN"),
        ("TOURNOI REGIONAL M13 FEMININS POULE A", "FEMININ"),
        ("CHAMPIONNAT REGIONAL SENIOR MASCULIN : POULE A", "MASCULIN"),
        ("LOISIR MIXTE ARGENT", "MIXTE"),
        ("PRENATIONAL MASCULINS POULE A", "MASCULIN"),
        ("ACCESSION REGIONALE SENIOR FEM POULE A", "FEMININ"),
        ("DÉPARTEMENTAL SENIOR FEMININ POULE A", "FEMININ"),
        ("PRÉ-RÉGIONAL ACCESSION FEMININ POULE B", "FEMININ"),
    ])
    def test_genre_from_name(self, nom, expected):
        meta = parse_competition_name(nom)
        assert meta.genre == expected

    def test_genre_from_code_masculine(self):
        """Code EMA → genre MASCULIN."""
        meta = parse_competition_name("ELITE - POULE A", poule_code="EMA")
        assert meta.genre == "MASCULIN"

    def test_genre_from_code_feminine(self):
        """Code 2FA → genre FEMININ."""
        meta = parse_competition_name("NATIONALE 2 - POULE A", poule_code="2FA")
        assert meta.genre == "FEMININ"

    def test_genre_from_code_ambiguous_no_name(self):
        """Code seul PMA → genre MASCULIN."""
        meta = parse_competition_name("POULE A", poule_code="PMA")
        assert meta.genre == "MASCULIN"


# =====================================================================
# parse_competition_name — Catégorie d'âge
# =====================================================================


class TestParseCompetitionNameCategorie:
    """Tests de détection de la catégorie d'âge."""

    @pytest.mark.parametrize("nom,expected", [
        ("ELITE MASCULINE - POULE A", "SENIOR"),
        ("NATIONALE 2 FEMININE - POULE A", "SENIOR"),
        ("TOURNOI REGIONAL M13 FEMININS POULE A", "M13"),
        ("CHAMPIONNAT REGIONAL M18 MASCULINS POULE A", "M18"),
        ("M15 6X6 75 POULE B", "M15"),
        ("COUPE DE FRANCE M13 FEMININ POULE A", "M13"),
        ("LOISIR MIXTE ARGENT", "SENIOR"),
    ])
    def test_categorie_from_name(self, nom, expected):
        meta = parse_competition_name(nom)
        assert meta.categorie_age == expected

    def test_senior_default_for_elite(self):
        meta = parse_competition_name("ELITE MASCULINE - POULE A")
        assert meta.categorie_age == "SENIOR"

    def test_senior_default_for_nationale(self):
        meta = parse_competition_name("NATIONALE 2 FEMININE - POULE A")
        assert meta.categorie_age == "SENIOR"


# =====================================================================
# parse_competition_name — Niveau
# =====================================================================


class TestParseCompetitionNameNiveau:
    """Tests de détection du niveau de compétition."""

    @pytest.mark.parametrize("nom,expected", [
        ("ELITE MASCULINE - POULE A", "ELITE"),
        ("ELITE FEMININE - POULE A", "ELITE"),
        ("ELITE AVENIR MASCULIN - POULE A", "ELITE"),
        ("NATIONALE 2 FEMININE - POULE A", "NATIONALE"),
        ("NATIONALE 3 MASCULINE POULE F", "NATIONALE"),
        ("COUPE DE FRANCE M13 FEMININ POULE A", "NATIONALE"),
        ("PRENATIONAL MASCULINS POULE A", "PRE_NATIONALE"),
        ("CHAMPIONNAT PRE-NATIONAL SENIOR FEMININ : POULE A", "PRE_NATIONALE"),
        ("ACCESSION REGIONALE SENIOR FEM POULE A", "PRE_NATIONALE"),
        ("PRÉ-RÉGIONAL ACCESSION FEMININ POULE B", "PRE_NATIONALE"),
        ("CHAMPIONNAT REGIONAL 1 SENIOR FEMININ : POULE A", "REGIONALE"),
        ("REGIONAL MASCULINS POULE A", "REGIONALE"),
        ("TOURNOI REGIONAL M13 FEMININS POULE A", "REGIONALE"),
        ("DÉPARTEMENTAL SENIOR FEMININ POULE A", "DEPARTEMENTALE"),
        ("LOISIR MIXTE ARGENT", "LOISIR"),
        ("COMPETFUN 6X6 CONFIRME 2 POULE F", "LOISIR"),
    ])
    def test_niveau_from_name(self, nom, expected):
        meta = parse_competition_name(nom)
        assert meta.niveau == expected

    def test_niveau_fallback_entite_type_nationale(self):
        meta = parse_competition_name("XYZ POULE A", entite_type="nationale")
        assert meta.niveau == "NATIONALE"

    def test_niveau_fallback_entite_type_ligue(self):
        meta = parse_competition_name("XYZ POULE A", entite_type="ligue")
        assert meta.niveau == "REGIONALE"

    def test_niveau_fallback_entite_type_comite(self):
        meta = parse_competition_name("XYZ POULE A", entite_type="comite")
        assert meta.niveau == "DEPARTEMENTALE"


# =====================================================================
# parse_competition_name — Division
# =====================================================================


class TestParseCompetitionNameDivision:
    """Tests de détection de la division."""

    @pytest.mark.parametrize("nom,poule_code,expected", [
        ("NATIONALE 2 FEMININE - POULE A", "2FA", "2"),
        ("NATIONALE 3 MASCULINE POULE F", "3MF", "3"),
        ("REGIONALE 1 FEMININES POULE A", None, "1"),
        ("ELITE MASCULINE - POULE A", "EMA", None),
        ("LOISIR MIXTE ARGENT", None, None),
    ])
    def test_division(self, nom, poule_code, expected):
        meta = parse_competition_name(nom, poule_code=poule_code)
        assert meta.division == expected

    def test_division_from_code_prefix(self):
        """Code 2FA → division 2 même si le nom ne le dit pas."""
        meta = parse_competition_name("POULE A", poule_code="2FA")
        assert meta.division == "2"


# =====================================================================
# parse_competition_name — Type de compétition
# =====================================================================


class TestParseCompetitionNameType:
    """Tests de détection du type de compétition."""

    @pytest.mark.parametrize("nom,expected", [
        ("CHAMPIONNAT REGIONAL 1 SENIOR FEMININ", "CHAMPIONNAT"),
        ("COUPE DE FRANCE M13 FEMININ POULE A", "COUPE"),
        ("TOURNOI REGIONAL M13 FEMININS POULE A", "TOURNOI"),
        # Default = CHAMPIONNAT
        ("ELITE MASCULINE - POULE A", "CHAMPIONNAT"),
        ("NATIONALE 2 FEMININE - POULE A", "CHAMPIONNAT"),
    ])
    def test_type(self, nom, expected):
        meta = parse_competition_name(nom)
        assert meta.type_competition == expected


# =====================================================================
# parse_competition_name — Phase
# =====================================================================


class TestParseCompetitionNamePhase:
    """Tests de détection de la phase."""

    @pytest.mark.parametrize("nom,expected", [
        ("ELITE MASCULINE - POULE A", "POULE"),
        ("PLAY-OFF NATIONALE 2 FEMININE", "PLAY_OFF"),
        ("PLAY DOWN MASCULINE", "PLAY_DOWN"),
        ("PHASE FINALE NATIONALE 3", "PHASE_FINALE"),
        ("BARRAGES NATIONALE 2 FEMININE", "BARRAGE"),
        ("LOISIR MIXTE CUIVRE - POULE HAUTE", "POULE_HAUTE"),
    ])
    def test_phase(self, nom, expected):
        meta = parse_competition_name(nom)
        assert meta.phase == expected


# =====================================================================
# parse_competition_name — Lettre de poule
# =====================================================================


class TestParseCompetitionNamePouleLettre:
    """Tests de détection de la lettre de poule."""

    @pytest.mark.parametrize("nom,poule_code,expected", [
        ("ELITE MASCULINE - POULE A", "EMA", "A"),
        ("NATIONALE 3 MASCULINE POULE F", "3MF", "F"),
        ("NATIONALE 2 FEMININE - POULE B", "2FB", "B"),
        ("REGIONALE 1 FEMININES POULE C", None, "C"),
    ])
    def test_poule_lettre(self, nom, poule_code, expected):
        meta = parse_competition_name(nom, poule_code=poule_code)
        assert meta.poule_lettre == expected


# =====================================================================
# parse_competition_name — Résultat complet
# =====================================================================


class TestParseCompetitionNameFullResult:
    """Tests d'intégration avec vérification de tous les champs."""

    def test_elite_masculine(self):
        meta = parse_competition_name(
            "ELITE MASCULINE - POULE A",
            poule_code="EMA",
            categorie_groupe="ELITE MASCULINE",
        )
        assert meta.poule_code == "EMA"
        assert meta.nom_complet == "ELITE MASCULINE - POULE A"
        assert meta.categorie_groupe == "ELITE MASCULINE"
        assert meta.genre == "MASCULIN"
        assert meta.categorie_age == "SENIOR"
        assert meta.niveau == "ELITE"
        assert meta.division is None
        assert meta.type_competition == "CHAMPIONNAT"
        assert meta.phase == "POULE"
        assert meta.poule_lettre == "A"

    def test_nationale_2_feminine(self):
        meta = parse_competition_name(
            "NATIONALE 2 FÉMININE - POULE A",
            poule_code="2FA",
            categorie_groupe="NATIONALE 2 FÉMININE",
        )
        assert meta.genre == "FEMININ"
        assert meta.categorie_age == "SENIOR"
        assert meta.niveau == "NATIONALE"
        assert meta.division == "2"
        assert meta.poule_lettre == "A"

    def test_tournoi_regional_m13(self):
        meta = parse_competition_name(
            "TOURNOI REGIONAL M13 FEMININS POULE A",
            poule_code="BFA",
        )
        assert meta.genre == "FEMININ"
        assert meta.categorie_age == "M13"
        assert meta.niveau == "REGIONALE"
        assert meta.type_competition == "TOURNOI"
        assert meta.phase == "POULE"
        assert meta.poule_lettre == "A"

    def test_prenational_masculin(self):
        meta = parse_competition_name(
            "PRENATIONAL MASCULINS POULE A",
            poule_code="PMA",
        )
        assert meta.genre == "MASCULIN"
        assert meta.categorie_age == "SENIOR"
        assert meta.niveau == "PRE_NATIONALE"

    def test_departemental_senior_feminin(self):
        meta = parse_competition_name(
            "DÉPARTEMENTAL SENIOR FEMININ POULE A",
            poule_code="DSF",
        )
        assert meta.genre == "FEMININ"
        assert meta.categorie_age == "SENIOR"
        assert meta.niveau == "DEPARTEMENTALE"
        assert meta.poule_lettre == "A"  # From "POULE A" in name

    def test_loisir_mixte(self):
        meta = parse_competition_name(
            "LOISIR MIXTE ARGENT",
        )
        assert meta.genre == "MIXTE"
        assert meta.niveau == "LOISIR"
        assert meta.categorie_age == "SENIOR"

    def test_accession_regionale(self):
        meta = parse_competition_name(
            "ACCESSION REGIONALE SENIOR FEM POULE A",
        )
        assert meta.genre == "FEMININ"
        assert meta.categorie_age == "SENIOR"
        assert meta.niveau == "PRE_NATIONALE"

    def test_coupe_de_france_m13(self):
        meta = parse_competition_name(
            "COUPE DE FRANCE M13 FEMININ POULE A",
        )
        assert meta.genre == "FEMININ"
        assert meta.categorie_age == "M13"
        assert meta.niveau == "NATIONALE"
        assert meta.type_competition == "COUPE"

    def test_categorie_groupe_enriches(self):
        """Le heading parent enrichit l'analyse quand le nom est ambigu."""
        meta = parse_competition_name(
            "POULE A",
            poule_code="EMA",
            categorie_groupe="ELITE MASCULINE",
        )
        assert meta.genre == "MASCULIN"
        assert meta.niveau == "ELITE"
        assert meta.categorie_age == "SENIOR"


# =====================================================================
# enrich_competition_meta_from_code
# =====================================================================


class TestEnrichCompetitionMetaFromCode:
    """Tests pour la déduction de métadonnées depuis le code seul."""

    def test_ema(self):
        meta = enrich_competition_meta_from_code("EMA")
        assert meta.poule_code == "EMA"
        assert meta.genre == "MASCULIN"
        assert meta.niveau == "ELITE"
        assert meta.categorie_age == "SENIOR"
        assert meta.poule_lettre == "A"

    def test_2fa(self):
        meta = enrich_competition_meta_from_code("2FA")
        assert meta.genre == "FEMININ"
        assert meta.niveau == "NATIONALE"
        assert meta.division == "2"
        assert meta.poule_lettre == "A"

    def test_pma(self):
        meta = enrich_competition_meta_from_code("PMA")
        assert meta.genre == "MASCULIN"
        assert meta.niveau == "PRE_NATIONALE"
        assert meta.poule_lettre == "A"

    def test_rfc(self):
        meta = enrich_competition_meta_from_code("RFC")
        assert meta.genre == "FEMININ"
        assert meta.niveau == "REGIONALE"
        assert meta.poule_lettre == "C"

    def test_dma(self):
        meta = enrich_competition_meta_from_code("DMA")
        assert meta.genre == "MASCULIN"
        assert meta.niveau == "DEPARTEMENTALE"
        assert meta.poule_lettre == "A"

    def test_entite_type_fallback(self):
        meta = enrich_competition_meta_from_code("XYZ", entite_type="ligue")
        assert meta.niveau == "REGIONALE"

    def test_empty_code(self):
        meta = enrich_competition_meta_from_code("")
        assert meta.poule_code == ""
        assert meta.genre is None
        assert meta.niveau is None

    def test_short_code(self):
        meta = enrich_competition_meta_from_code("A")
        assert meta.genre is None

    def test_3mf(self):
        meta = enrich_competition_meta_from_code("3MF")
        assert meta.genre == "MASCULIN"
        assert meta.niveau == "NATIONALE"
        assert meta.division == "3"
        # Dernière lettre F, mais F est exclue (marqueur genre)
        assert meta.poule_lettre is None


# =====================================================================
# extract_header — enrichissement
# =====================================================================

from pyvolley.parsers.extractors.header import extract_header


class TestExtractHeaderEnrichment:
    """Tests que extract_header utilise bien competition_info."""

    def test_header_extracts_division_type_phase(self):
        """Les nouveaux champs sont bien présents dans le résultat."""
        lines = [
            "EMA - ELITE MASCULINE - POULE A Match: EMA001 - Jour: 01",
            "Ville: SAINT MARTIN D'HÈRES Samedi 20 Septembre 2025 à 20h30",
            "Salle: CSU - GRAND GYMNASE SENIOR | MASCULIN",
            "Compétitions Nationales SENIORS GRENOBLE V.UNIVERSITE CLUB",
        ]
        h = extract_header(lines)
        assert "division" in h
        assert "type_competition" in h
        assert "phase" in h

    def test_header_genre_from_salle(self):
        """Genre depuis la ligne Salle n'est pas écrasé."""
        lines = [
            "XYZ - TRUC Match: XYZ001 - Jour: 01",
            "Ville: PARIS Samedi 20 Septembre 2025 à 20h30",
            "Salle: GYMNASE CENTRAL SENIOR | MASCULIN",
            "Compétitions Nationales SENIORS PARIS UC",
        ]
        h = extract_header(lines)
        assert h["genre"] == "MASCULIN"

    def test_header_niveau_from_elite(self):
        """ELITE dans le nom de la compétition → niveau ELITE."""
        lines = [
            "EMA - ELITE MASCULINE - POULE A Match: EMA001 - Jour: 01",
            "Ville: PARIS Samedi 20 Septembre 2025 à 20h30",
            "Salle: GYMNASE CENTRAL SENIOR | MASCULIN",
            "Compétitions Nationales SENIORS PARIS UC",
        ]
        h = extract_header(lines)
        assert h["niveau"] == "ELITE"

    def test_header_categorie_from_competition(self):
        """Catégorie d'âge M13 depuis le nom de compétition."""
        lines = [
            "BFA - TOURNOI REGIONAL M13 FEMININS POULE A Match: BFA001 - Jour: 01",
            "Ville: LYON Samedi 20 Septembre 2025 à 14h00",
            "Salle: GYMNASE M13 | FEMININ",
            "Ligue AUVERGNE-RHÔNE-ALPES EQUIPE A EQUIPE B",
        ]
        h = extract_header(lines)
        assert h["categorie"] == "M13"

    def test_header_nationale_2(self):
        """NATIONALE 2 → niveau NATIONALE, division 2."""
        lines = [
            "2FA - NATIONALE 2 FEMININE - POULE A Match: 2FA001 - Jour: 01",
            "Ville: LYON Samedi 20 Septembre 2025 à 20h30",
            "Salle: GYMNASE SENIOR | FEMININ",
            "Compétitions Nationales SENIORS EQUIPE A EQUIPE B",
        ]
        h = extract_header(lines)
        assert h["niveau"] == "NATIONALE"
        assert h["division"] == "2"
        assert h["phase"] == "POULE"
