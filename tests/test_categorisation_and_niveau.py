import pytest
from datetime import date as dt_date
from pyvolley.shared.categorisation import (
    normalize_categorie,
    normalize_genre,
    extract_division_number,
    category_age_limit,
    estimate_birth_year_min,
    is_youth_category,
)
from pyvolley.shared.niveau import (
    classify_level,
    resolve_niveau_badge,
    niveau_sort_rank,
    niveau_sort_key,
    niveau_reference_labels,
    LevelClassification,
)


class TestCategorisation:
    def test_normalize_categorie_youth(self):
        assert normalize_categorie("M15") == "M15"
        assert normalize_categorie("U15") == "M15"
        assert normalize_categorie("Minimes") == "M15"
        assert normalize_categorie("M18") == "M18"
        assert normalize_categorie("Cadets") == "M18"
        assert normalize_categorie("M13") == "M13"
        assert normalize_categorie("Benjamins") == "M13"
        assert normalize_categorie("M11") == "M11"
        assert normalize_categorie("Poussins") == "M11"
        assert normalize_categorie("M9") == "M9"
        assert normalize_categorie("M21") == "M21"
        assert normalize_categorie("Juniors") == "M21"

    def test_normalize_categorie_seniors(self):
        assert normalize_categorie("SENIOR") == "SENIOR"
        assert normalize_categorie("Séniors Masculins") == "SENIOR"
        assert normalize_categorie("Vétérans") == "VETERAN"

    def test_normalize_genre(self):
        assert normalize_genre("Masculin") == "MASCULIN"
        assert normalize_genre("Féminin") == "FEMININ"
        assert normalize_genre("Féminine") == "FEMININ"
        assert normalize_genre("Mixte") == "MIXTE"
        assert normalize_genre("Masculin", as_short=True) == "M"
        assert normalize_genre("Féminin", as_short=True) == "F"

    def test_extract_division_number(self):
        assert extract_division_number("Régionale 1") == "1"
        assert extract_division_number("R2") == "2"
        assert extract_division_number("Nationale 3") == "3"
        assert extract_division_number("Départementale 4") == "4"
        assert extract_division_number("Sans division") is None

    def test_age_limits_and_birth_year(self):
        assert is_youth_category("M15") is True
        assert is_youth_category("SENIOR") is False
        assert category_age_limit("M15") == 15
        assert category_age_limit("M18") == 18
        assert category_age_limit("SENIOR") is None

        # Si un joueur joue en M15 durant la saison 2023-2024 (fin 2024)
        # Né au plus tôt en 2024 - 15 = 2009
        b_min = estimate_birth_year_min("M15", 2024)
        assert b_min == 2009


class TestNiveauClassification:
    def test_professional_levels(self):
        c_pro_a = classify_level(competition_name="Ligue A Masculine", niveau="PRO")
        assert c_pro_a.label == "Pro A"
        assert c_pro_a.rank == 17
        assert c_pro_a.categorie_principale == "PRO"

        c_pro_b = classify_level(competition_name="Ligue B Masculine")
        assert c_pro_b.label == "Pro B"
        assert c_pro_b.rank == 16

    def test_national_elite(self):
        c_elite = classify_level(competition_name="CHAMPIONNAT DE FRANCE ELITE", categorie="SENIOR")
        assert c_elite.label == "Elite"
        assert c_elite.rank == 15
        assert c_elite.categorie_principale == "ELITE"

        c_elite_avenir = classify_level(competition_name="CHAMPIONNAT ELITE AVENIR")
        assert c_elite_avenir.label == "Elite Avenir"
        assert c_elite_avenir.rank == 14

    def test_regional_elite_youth_guard(self):
        # Ne doit JAMAIS être classé en Elite nationale !
        c_reg_elite = classify_level(competition_name="CHAMPIONNAT REGIONAL ELITE M15", categorie="M15")
        assert c_reg_elite.categorie_principale == "REGIONALE"
        assert "Elite" not in c_reg_elite.label or c_reg_elite.is_youth
        assert c_reg_elite.rank < 11  # Inférieur à N3

    def test_national_divisions(self):
        c_n1 = classify_level(competition_name="Nationale 1 Masculine", niveau="NATIONALE")
        assert c_n1.label == "N1"
        assert c_n1.division == "1"
        assert c_n1.rank == 13

        c_n2 = classify_level(competition_name="Nationale 2 Féminine")
        assert c_n2.label == "N2"
        assert c_n2.division == "2"
        assert c_n2.rank == 12

        c_n3 = classify_level(competition_name="Nationale 3")
        assert c_n3.label == "N3"
        assert c_n3.division == "3"
        assert c_n3.rank == 11

    def test_prenationale(self):
        c_prenat = classify_level(competition_name="CHAMPIONNAT REGIONAL PRENATIONALE")
        assert c_prenat.label == "Prénat"
        assert c_prenat.categorie_principale == "PRE_NATIONALE"
        assert c_prenat.rank == 10

    def test_regional_divisions(self):
        c_r1 = classify_level(competition_name="Régionale 1 Féminine")
        assert c_r1.label == "R1"
        assert c_r1.division == "1"
        assert c_r1.rank == 9

        c_r2 = classify_level(competition_name="Régionale 2 Masculine")
        assert c_r2.label == "R2"
        assert c_r2.division == "2"
        assert c_r2.rank == 8

        c_r3 = classify_level(competition_name="Régionale 3")
        assert c_r3.label == "R3"
        assert c_r3.division == "3"
        assert c_r3.rank == 7

        c_r4 = classify_level(competition_name="Régionale 4")
        assert c_r4.label == "R4"
        assert c_r4.division == "4"
        assert c_r4.rank == 7

    def test_preregionale(self):
        c_prereg = classify_level(competition_name="Pré-régionale Masculine")
        assert c_prereg.label == "Préreg"
        assert c_prereg.categorie_principale == "PRE_REGIONALE"
        assert c_prereg.rank == 6

    def test_departmental_divisions(self):
        c_d1 = classify_level(competition_name="Départementale 1 Masculine")
        assert c_d1.label == "D1"
        assert c_d1.division == "1"
        assert c_d1.rank == 4

        c_d2 = classify_level(competition_name="Départementale 2 Féminine")
        assert c_d2.label == "D2"
        assert c_d2.division == "2"
        assert c_d2.rank == 3

        c_d3 = classify_level(competition_name="Départementale 3")
        assert c_d3.label == "D3"
        assert c_d3.division == "3"
        assert c_d3.rank == 2

        c_d4 = classify_level(competition_name="Départementale 4")
        assert c_d4.label == "D4"
        assert c_d4.division == "4"
        assert c_d4.rank == 1

    def test_coupes_de_france(self):
        c_senior_cdf = classify_level(competition_name="Coupe de France Senior Masculine", categorie="SENIOR")
        assert c_senior_cdf.label == "CdF"
        assert c_senior_cdf.rank == 18
        assert c_senior_cdf.is_youth is False

        c_youth_cdf = classify_level(competition_name="Coupe de France M15 Féminine", categorie="M15")
        assert c_youth_cdf.label == "Jeunes CdF"
        assert c_youth_cdf.rank == 5
        assert c_youth_cdf.is_youth is True

    def test_loisir(self):
        c_loisir = classify_level(competition_name="CHAMPIONNAT LOISIR MIXTE")
        assert c_loisir.label == "Loisir"
        assert c_loisir.rank == 0

    def test_seniors_always_have_clean_classification(self):
        # Vérifie que les matchs seniors ont tous une classification propre et ordinale
        levels = [
            ("LIGUE A MASCULINE", 17),
            ("LIGUE B MASCULINE", 16),
            ("CHAMPIONNAT DE FRANCE ELITE", 15),
            ("NATIONALE 1", 13),
            ("NATIONALE 2", 12),
            ("NATIONALE 3", 11),
            ("PRENATIONALE", 10),
            ("REGIONALE 1", 9),
            ("REGIONALE 2", 8),
            ("PRE REGIONALE", 6),
            ("DEPARTEMENTALE 1", 4),
            ("DEPARTEMENTALE 2", 3),
            ("LOISIR", 0),
        ]
        for name, expected_rank in levels:
            res = classify_level(competition_name=name, categorie="SENIOR")
            assert res.rank == expected_rank, f"Failed for {name}: got {res.rank}, expected {expected_rank}"
            assert res.is_youth is False
            assert res.label is not None
