"""
Tests unitaires pour CompetitionViewService et la hiérarchie des compétitions.

Vérifie :
1. La classification précise par échelon (National, Régional, Départemental, Coupe, Loisir).
2. L'ordre de tri strict par niveau sportif décroissant (Elite > N2 > N3 > Prénat > R1 > D1...).
3. Le regroupement et le calcul des KPIs.
4. Les filtres par genre, catégorie, échelon et recherche textuelle.
"""

import pytest

from pyvolley.shared.niveau import (
    classify_level,
    resolve_competition_echelon,
    ECHELON_METADATA,
)
from pyvolley.web.services.competition_view_service import (
    CompetitionViewService,
    CompetitionCardDTO,
)


class TestEchelonResolution:
    """Vérification de la détection d'échelon territorial."""

    @pytest.mark.parametrize(
        "nom,niveau,entite_type,expected",
        [
            ("ELITE MASCULINE - POULE A", "ELITE", "nationale", "national"),
            ("NATIONALE 2 FEMININE", "NATIONALE", "nationale", "national"),
            ("NATIONALE 3 MASCULINE", None, None, "national"),
            ("PRO A MASCULINE", "PRO", "nationale", "national"),
            ("PRENATIONAL MASCULINS", "PRE_NATIONALE", "ligue", "regional"),
            ("REGIONAL FEMININS", "REGIONALE", "ligue", "regional"),
            ("CHAMPIONNAT REGIONAL M13 FEMININS", "REGIONALE", "ligue", "regional"),
            ("CHAMPIONNAT REGIONAL ELITE M13 FEMININS", "REGIONALE", "ligue", "regional"),
            ("DEPARTEMENTAL SENIOR MASCULIN", "DEPARTEMENTALE", "comite", "departemental"),
            ("PRE-REGIONAL FEMININ", "PRE_REGIONALE", "comite", "departemental"),
            ("D1 MASCULINE", None, "comite", "departemental"),
            ("COUPE DE FRANCE M15 FEMININ", "COUPE_DE_FRANCE", None, "coupe_de_france"),
            ("COUPE DE FRANCE SENIOR MASCULIN", None, None, "coupe_de_france"),
            ("LOISIR MIXTE CONFIRME", "LOISIR", None, "loisir"),
            ("COMPET FUN 6X6", None, None, "loisir"),
        ],
    )
    def test_echelon_resolution_rules(self, nom, niveau, entite_type, expected):
        ech = resolve_competition_echelon(
            nom=nom,
            niveau=niveau,
            entite_type=entite_type,
        )
        assert ech == expected


class TestLevelOrderingAndGrouping:
    """Vérification de l'ordonnancement par niveau et du groupement."""

    def test_level_rank_order(self):
        """Vérifie que Elite > N2 > N3 > Prénat > R1 > D1."""
        elite = classify_level("ELITE MASCULINE")
        n2 = classify_level("NATIONALE 2 FEMININE")
        n3 = classify_level("NATIONALE 3 MASCULINE")
        prenat = classify_level("PRENATIONAL MASCULINS")
        r1 = classify_level("REGIONALE 1 MASCULINE")
        d1 = classify_level("DEPARTEMENTALE 1 MASCULINE")

        assert elite.rank > n2.rank
        assert n2.rank > n3.rank
        assert n3.rank > prenat.rank
        assert prenat.rank > r1.rank
        assert r1.rank > d1.rank

    def test_competition_view_service_page_preparation(self):
        """Teste la structuration complète d'une liste hétérogène de compétitions."""
        dummy_comps = [
            {
                "id": 1,
                "nom": "NATIONALE 3 MASCULINE POULE A",
                "code_competition": "3MAA",
                "genre": "MASCULIN",
                "categorie": "SENIOR",
                "saison_id": 1,
                "saison_code": "2025-2026",
                "entite_type": "nationale",
                "poules_count": 1,
                "matchs_count": 22,
            },
            {
                "id": 2,
                "nom": "ELITE MASCULINE POULE A",
                "code_competition": "EMA",
                "genre": "MASCULIN",
                "categorie": "SENIOR",
                "saison_id": 1,
                "saison_code": "2025-2026",
                "entite_type": "nationale",
                "poules_count": 2,
                "matchs_count": 28,
            },
            {
                "id": 3,
                "nom": "NATIONALE 2 FEMININE POULE B",
                "code_competition": "2FB",
                "genre": "FEMININ",
                "categorie": "SENIOR",
                "saison_id": 1,
                "saison_code": "2025-2026",
                "entite_type": "nationale",
                "poules_count": 1,
                "matchs_count": 20,
            },
            {
                "id": 4,
                "nom": "PRENATIONAL MASCULINS",
                "code_competition": "PMAA",
                "genre": "MASCULIN",
                "categorie": "SENIOR",
                "saison_id": 1,
                "saison_code": "2025-2026",
                "entite_type": "ligue",
                "poules_count": 2,
                "matchs_count": 40,
            },
            {
                "id": 5,
                "nom": "REGIONAL FEMININS",
                "code_competition": "RFCA",
                "genre": "FEMININ",
                "categorie": "SENIOR",
                "saison_id": 1,
                "saison_code": "2025-2026",
                "entite_type": "ligue",
                "poules_count": 3,
                "matchs_count": 50,
            },
            {
                "id": 6,
                "nom": "D1 MASCULIN POULE A",
                "code_competition": "D1MA",
                "genre": "MASCULIN",
                "categorie": "SENIOR",
                "saison_id": 1,
                "saison_code": "2025-2026",
                "entite_type": "comite",
                "poules_count": 1,
                "matchs_count": 14,
            },
        ]

        dummy_saisons = [{"id": 1, "code": "2025-2026"}, {"id": 2, "code": "2024-2025"}]

        page = CompetitionViewService.prepare_competitions_page(
            competitions=dummy_comps,
            saisons=dummy_saisons,
            current_saison_id=1,
        )

        assert page.total_competitions == 6
        assert page.total_national == 3
        assert page.total_regional == 2
        assert page.total_departemental == 1
        assert page.total_matches == 174
        assert page.total_poules == 10

        # Vérifier l'ordre des échelons
        echelon_keys = [e.key for e in page.echelons]
        assert echelon_keys == ["national", "regional", "departemental"]

        # Échelon National : Vérifier que le tri par niveau est bien Elite > N2 > N3
        nat_echelon = page.echelons[0]
        assert nat_echelon.total_competitions == 3
        nat_levels = [g.level_label for g in nat_echelon.level_groups]
        assert nat_levels == ["Elite", "N2", "N3"]

        # Échelon Régional : Vérifier que Prénat vient avant Régional
        reg_echelon = page.echelons[1]
        assert reg_echelon.total_competitions == 2
        reg_levels = [g.level_label for g in reg_echelon.level_groups]
        assert reg_levels == ["Prénat", "Régional"]

    def test_filters_preservation(self):
        """Vérifie le filtrage par genre, catégorie ou échelon."""
        dummy_comps = [
            {
                "id": 1,
                "nom": "NATIONALE 2 MASCULINE",
                "code_competition": "2MA",
                "genre": "MASCULIN",
                "categorie": "SENIOR",
                "entite_type": "nationale",
            },
            {
                "id": 2,
                "nom": "NATIONALE 2 FEMININE",
                "code_competition": "2FA",
                "genre": "FEMININ",
                "categorie": "SENIOR",
                "entite_type": "nationale",
            },
        ]
        page = CompetitionViewService.prepare_competitions_page(
            competitions=dummy_comps,
            saisons=[],
            active_genre="FEMININ",
        )
        assert page.total_competitions == 2
        assert len(page.all_competitions) == 1
        assert page.all_competitions[0].genre == "FEMININ"
        assert page.filter_applied is True
