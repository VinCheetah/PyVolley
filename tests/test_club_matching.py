"""Tests du module partagé club_matching — normalisation et matching de noms de clubs."""

import pytest

from pyvolley.database.club_matching import (
    normalize_club_name,
    extract_club_core_name,
    levenshtein,
    club_names_match,
)


# ============== normalize_club_name ==============


class TestNormalizeClubName:
    """Tests de normalisation des noms de clubs."""

    def test_uppercases(self):
        assert normalize_club_name("as volley paris") == "AS VOLLEY PARIS"

    def test_strips_whitespace(self):
        assert normalize_club_name("  Club  Test  ") == "CLUB TEST"

    def test_removes_accents(self):
        result = normalize_club_name("Béziers Volley-Ball")
        assert "E" in result  # é → E
        assert "é" not in result

    def test_dash_to_space(self):
        result = normalize_club_name("Saint-Maur")
        # SAINT → ST via normalization
        assert "ST" in result
        assert "MAUR" in result

    def test_empty_returns_empty(self):
        assert normalize_club_name("") == ""

    def test_normalizes_saint(self):
        """SAINT/SAINTE → ST."""
        assert "ST " in normalize_club_name("Saint-Brieuc")
        assert "ST " in normalize_club_name("Sainte-Marie")

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("A.S. Paris", "A S PARIS"),
            ("CLUB DE VOLLEY", "CLUB DE VOLLEY"),
        ],
    )
    def test_various_inputs(self, input_name, expected):
        assert normalize_club_name(input_name) == expected


# ============== extract_club_core_name ==============


class TestExtractClubCoreName:
    """Tests d'extraction du noyau significatif d'un nom de club."""

    def test_removes_volleyball_suffix(self):
        """Le suffixe 'volleyball' est retiré."""
        result = extract_club_core_name("Paris Volley-Ball")
        assert "volley" not in result.lower()

    def test_removes_volley_suffix(self):
        """Le suffixe 'volley' seul est retiré."""
        result = extract_club_core_name("Stade Poitevin Volley")
        assert "volley" not in result.lower()

    def test_removes_vb_suffix(self):
        """L'abréviation VB est retirée."""
        result = extract_club_core_name("Tours VB")
        assert "vb" not in result.lower()

    def test_keeps_city_name(self):
        """Le nom de la ville est conservé."""
        result = extract_club_core_name("AS Cannes Volley-Ball")
        assert "cannes" in result.lower()

    def test_only_volley_word(self):
        """Si le nom ne contient que des mots sans suffixe à retirer, retourne normalisé."""
        # 'VOLLEY' seul n'est pas un suffixe (il faut un espace avant)
        result = extract_club_core_name("Volley")
        assert result == "VOLLEY"


# ============== levenshtein ==============


class TestLevenshtein:
    """Tests de la distance de Levenshtein."""

    def test_identical_strings(self):
        assert levenshtein("paris", "paris") == 0

    def test_one_insertion(self):
        assert levenshtein("pari", "paris") == 1

    def test_one_deletion(self):
        assert levenshtein("paris", "pari") == 1

    def test_one_substitution(self):
        assert levenshtein("paris", "paras") == 1

    def test_completely_different(self):
        assert levenshtein("abc", "xyz") == 3

    def test_empty_strings(self):
        assert levenshtein("", "") == 0

    def test_one_empty(self):
        assert levenshtein("abc", "") == 3
        assert levenshtein("", "abc") == 3


# ============== club_names_match ==============


class TestClubNamesMatch:
    """Tests du matching intelligent de noms de clubs."""

    def test_exact_match(self):
        assert club_names_match("Paris Volley", "Paris Volley") is True

    def test_case_insensitive(self):
        assert club_names_match("PARIS VOLLEY", "paris volley") is True

    def test_with_suffix_difference(self):
        """Un club avec/sans 'Volley-Ball' est reconnu comme le même."""
        assert club_names_match("Paris Volley-Ball", "Paris Volley") is True

    def test_different_clubs(self):
        """Deux clubs différents ne sont pas confondus."""
        assert club_names_match("Paris Volley", "Lyon Volley") is False

    def test_with_accents(self):
        """Les accents ne bloquent pas le matching."""
        assert club_names_match("Béziers Volley", "Beziers Volley") is True

    def test_abbreviation_vs_full(self):
        """Un club abrégé matche avec le nom complet si assez similaire."""
        assert club_names_match("AS Cannes", "AS Cannes Volley-Ball") is True

    def test_empty_inputs(self):
        assert club_names_match("", "Paris") is False
        assert club_names_match("Paris", "") is False

    def test_very_similar_names(self):
        """Des noms très similaires (1 ou 2 caractères de différence) matchent."""
        assert club_names_match("Stade Poitevin", "Stade Poitierin") is True

    def test_completely_different(self):
        """Des noms totalement différents ne matchent pas."""
        assert club_names_match("XYZ Basketball", "ABC Football") is False
