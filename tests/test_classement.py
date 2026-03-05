"""
Tests pour le service de classement de compétitions.
"""

import pytest
from datetime import date

from pyvolley.analysis.classement import (
    MatchData,
    LigneClassement,
    ClassementComplet,
    EvolutionJournee,
    calculer_classement,
    calculer_classement_complet,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def matchs_simple() -> list[MatchData]:
    """4 équipes, 3 journées, 6 matchs."""
    return [
        # J1: A bat B 3-0, C bat D 3-2
        MatchData(match_id=1, equipe_a_id=1, equipe_a_nom="Club A",
                  equipe_b_id=2, equipe_b_nom="Club B",
                  sets_a=3, sets_b=0, points_a=75, points_b=55,
                  journee="J1", date_match=date(2025, 10, 5)),
        MatchData(match_id=2, equipe_a_id=3, equipe_a_nom="Club C",
                  equipe_b_id=4, equipe_b_nom="Club D",
                  sets_a=3, sets_b=2, points_a=110, points_b=105,
                  journee="J1", date_match=date(2025, 10, 5)),
        # J2: A bat C 3-1, B bat D 3-1
        MatchData(match_id=3, equipe_a_id=1, equipe_a_nom="Club A",
                  equipe_b_id=3, equipe_b_nom="Club C",
                  sets_a=3, sets_b=1, points_a=95, points_b=80,
                  journee="J2", date_match=date(2025, 10, 12)),
        MatchData(match_id=4, equipe_a_id=4, equipe_a_nom="Club D",
                  equipe_b_id=2, equipe_b_nom="Club B",
                  sets_a=1, sets_b=3, points_a=80, points_b=95,
                  journee="J2", date_match=date(2025, 10, 12)),
        # J3: B bat C 3-2, A bat D 3-0
        MatchData(match_id=5, equipe_a_id=2, equipe_a_nom="Club B",
                  equipe_b_id=3, equipe_b_nom="Club C",
                  sets_a=3, sets_b=2, points_a=115, points_b=110,
                  journee="J3", date_match=date(2025, 10, 19)),
        MatchData(match_id=6, equipe_a_id=1, equipe_a_nom="Club A",
                  equipe_b_id=4, equipe_b_nom="Club D",
                  sets_a=3, sets_b=0, points_a=75, points_b=50,
                  journee="J3", date_match=date(2025, 10, 19)),
    ]


# ═══════════════════════════════════════════════════════════════════
# Tests calculer_classement
# ═══════════════════════════════════════════════════════════════════

class TestCalculerClassement:
    """Tests pour la fonction calculer_classement."""

    def test_classement_order(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        noms = [l.equipe_nom for l in classement]
        assert noms == ["Club A", "Club B", "Club C", "Club D"]

    def test_points_ffvb_3_0(self, matchs_simple):
        """Victoire 3-0 = 3 pts, défaite 0-3 = 0 pts."""
        classement = calculer_classement(matchs_simple)
        club_a = next(l for l in classement if l.equipe_nom == "Club A")
        # A: 3-0 (3pts), 3-1 (3pts), 3-0 (3pts) = 9 pts
        assert club_a.points == 9

    def test_points_ffvb_3_2(self, matchs_simple):
        """Victoire 3-2 = 2 pts, défaite 2-3 = 1 pt."""
        classement = calculer_classement(matchs_simple)
        club_c = next(l for l in classement if l.equipe_nom == "Club C")
        # C: victoire 3-2 (2pts), défaite 1-3 (0pts), défaite 2-3 (1pt) = 3 pts
        assert club_c.points == 3

    def test_matchs_joues(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        for l in classement:
            assert l.matchs_joues == 3

    def test_victoires_defaites(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        club_a = next(l for l in classement if l.equipe_nom == "Club A")
        assert club_a.victoires == 3
        assert club_a.defaites == 0

        club_d = next(l for l in classement if l.equipe_nom == "Club D")
        assert club_d.victoires == 0
        assert club_d.defaites == 3

    def test_victoire_detail(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        club_a = next(l for l in classement if l.equipe_nom == "Club A")
        assert club_a.victoires_3_0 == 2
        assert club_a.victoires_3_1 == 1
        assert club_a.victoires_3_2 == 0

    def test_defaite_detail(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        club_d = next(l for l in classement if l.equipe_nom == "Club D")
        # D perd: 2-3 (J1), 1-3 (J2), 0-3 (J3) → 1 de chaque
        assert club_d.defaites_0_3 == 1
        assert club_d.defaites_1_3 == 1
        assert club_d.defaites_2_3 == 1

    def test_sets_stats(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        club_a = next(l for l in classement if l.equipe_nom == "Club A")
        assert club_a.sets_gagnes == 9
        assert club_a.sets_perdus == 1
        assert club_a.diff_sets == 8

    def test_points_marques(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        club_a = next(l for l in classement if l.equipe_nom == "Club A")
        assert club_a.points_marques == 75 + 95 + 75  # 245
        assert club_a.points_encaisses == 55 + 80 + 50  # 185

    def test_serie(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        club_a = next(l for l in classement if l.equipe_nom == "Club A")
        assert club_a.serie == ["V", "V", "V"]

        club_b = next(l for l in classement if l.equipe_nom == "Club B")
        assert club_b.serie == ["D", "V", "V"]

    def test_rangs(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        for i, l in enumerate(classement, start=1):
            assert l.rang == i

    def test_ratio_sets(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        club_a = next(l for l in classement if l.equipe_nom == "Club A")
        assert club_a.ratio_sets == 9.0  # 9/1

    def test_taux_victoire(self, matchs_simple):
        classement = calculer_classement(matchs_simple)
        club_a = next(l for l in classement if l.equipe_nom == "Club A")
        assert club_a.taux_victoire == 100.0

        club_b = next(l for l in classement if l.equipe_nom == "Club B")
        assert abs(club_b.taux_victoire - 66.67) < 1

    def test_empty_matchs(self):
        classement = calculer_classement([])
        assert classement == []

    def test_match_non_joue_ignored(self):
        matchs = [
            MatchData(match_id=1, equipe_a_id=1, equipe_a_nom="A",
                      equipe_b_id=2, equipe_b_nom="B",
                      sets_a=0, sets_b=0, match_joue=False),
        ]
        classement = calculer_classement(matchs)
        assert classement == []

    def test_tiebreaker_sets_ratio(self):
        """Si les points sont égaux, le ratio de sets départage."""
        matchs = [
            MatchData(match_id=1, equipe_a_id=1, equipe_a_nom="A",
                      equipe_b_id=2, equipe_b_nom="B",
                      sets_a=3, sets_b=0, points_a=75, points_b=50),
            MatchData(match_id=2, equipe_a_id=3, equipe_a_nom="C",
                      equipe_b_id=4, equipe_b_nom="D",
                      sets_a=3, sets_b=1, points_a=95, points_b=80),
        ]
        classement = calculer_classement(matchs)
        # A: 3pts, sets 3-0, ratio ∞
        # C: 3pts, sets 3-1, ratio 3.0
        # A should be ranked higher due to better set ratio
        assert classement[0].equipe_nom == "A"
        assert classement[1].equipe_nom == "C"


# ═══════════════════════════════════════════════════════════════════
# Tests calculer_classement_complet
# ═══════════════════════════════════════════════════════════════════

class TestCalculerClassementComplet:
    """Tests pour la fonction calculer_classement_complet."""

    def test_metadata(self, matchs_simple):
        result = calculer_classement_complet(
            matchs_simple, competition_id=1, competition_nom="Test",
            saison="2025-2026", genre="MASCULIN", categorie="SENIOR",
            niveau="REGIONALE",
        )
        assert result.competition_id == 1
        assert result.competition_nom == "Test"
        assert result.saison == "2025-2026"
        assert result.genre == "MASCULIN"
        assert result.categorie == "SENIOR"
        assert result.niveau == "REGIONALE"

    def test_equipes_count(self, matchs_simple):
        result = calculer_classement_complet(
            matchs_simple, competition_id=1, competition_nom="Test",
        )
        assert result.nb_equipes == 4

    def test_matchs_count(self, matchs_simple):
        result = calculer_classement_complet(
            matchs_simple, competition_id=1, competition_nom="Test",
        )
        assert result.nb_matchs_joues == 6
        assert result.nb_matchs_total == 6

    def test_journees(self, matchs_simple):
        result = calculer_classement_complet(
            matchs_simple, competition_id=1, competition_nom="Test",
        )
        assert result.journees == ["J1", "J2", "J3"]

    def test_evolution_length(self, matchs_simple):
        result = calculer_classement_complet(
            matchs_simple, competition_id=1, competition_nom="Test",
        )
        assert len(result.evolution) == 3

    def test_evolution_cumulative(self, matchs_simple):
        result = calculer_classement_complet(
            matchs_simple, competition_id=1, competition_nom="Test",
        )
        # Après J1 : A=3pts, C=2pts, D=1pt, B=0pts
        j1 = result.evolution[0]
        assert j1.journee == "J1"
        a_j1 = next(l for l in j1.classement if l.equipe_nom == "Club A")
        assert a_j1.points == 3
        assert a_j1.rang == 1

        b_j1 = next(l for l in j1.classement if l.equipe_nom == "Club B")
        assert b_j1.points == 0

        # Après J3 : même que classement final
        j3 = result.evolution[2]
        a_j3 = next(l for l in j3.classement if l.equipe_nom == "Club A")
        assert a_j3.points == 9

    def test_evolution_dates(self, matchs_simple):
        result = calculer_classement_complet(
            matchs_simple, competition_id=1, competition_nom="Test",
        )
        assert result.evolution[0].date == "2025-10-05"
        assert result.evolution[1].date == "2025-10-12"
        assert result.evolution[2].date == "2025-10-19"

    def test_classement_actuel_matches_final_evolution(self, matchs_simple):
        result = calculer_classement_complet(
            matchs_simple, competition_id=1, competition_nom="Test",
        )
        final_evo = result.evolution[-1]
        for l_actuel, l_evo in zip(
            result.classement_actuel, final_evo.classement
        ):
            assert l_actuel.equipe_id == l_evo.equipe_id
            assert l_actuel.points == l_evo.points

    def test_with_non_joue_matchs(self, matchs_simple):
        """Les matchs non joués sont comptés dans le total mais pas dans le classement."""
        matchs = matchs_simple + [
            MatchData(match_id=7, equipe_a_id=1, equipe_a_nom="Club A",
                      equipe_b_id=2, equipe_b_nom="Club B",
                      sets_a=0, sets_b=0, match_joue=False, journee="J4"),
        ]
        result = calculer_classement_complet(
            matchs, competition_id=1, competition_nom="Test",
        )
        assert result.nb_matchs_total == 7
        assert result.nb_matchs_joues == 6

    def test_empty_competition(self):
        result = calculer_classement_complet(
            [], competition_id=1, competition_nom="Test Vide",
        )
        assert result.nb_equipes == 0
        assert result.nb_matchs_joues == 0
        assert result.classement_actuel == []
        assert result.evolution == []

    def test_grouper_par_date_sans_journee(self):
        """Quand pas de journée, on groupe par date."""
        matchs = [
            MatchData(match_id=1, equipe_a_id=1, equipe_a_nom="A",
                      equipe_b_id=2, equipe_b_nom="B",
                      sets_a=3, sets_b=0, journee=None,
                      date_match=date(2025, 10, 5)),
            MatchData(match_id=2, equipe_a_id=3, equipe_a_nom="C",
                      equipe_b_id=4, equipe_b_nom="D",
                      sets_a=3, sets_b=1, journee=None,
                      date_match=date(2025, 10, 12)),
        ]
        result = calculer_classement_complet(
            matchs, competition_id=1, competition_nom="Test",
        )
        assert result.journees == ["2025-10-05", "2025-10-12"]
        assert len(result.evolution) == 2


class TestLigneClassementProperties:
    """Tests pour les propriétés calculées de LigneClassement."""

    def test_ratio_sets_zero_perdus(self):
        l = LigneClassement(equipe_id=1, equipe_nom="T", sets_gagnes=9, sets_perdus=0)
        assert l.ratio_sets == 9.0

    def test_ratio_sets_zero_both(self):
        l = LigneClassement(equipe_id=1, equipe_nom="T", sets_gagnes=0, sets_perdus=0)
        assert l.ratio_sets == 0.0

    def test_ratio_points_zero_encaisses(self):
        l = LigneClassement(equipe_id=1, equipe_nom="T", points_marques=100, points_encaisses=0)
        assert l.ratio_points == 100.0

    def test_diff_sets(self):
        l = LigneClassement(equipe_id=1, equipe_nom="T", sets_gagnes=9, sets_perdus=3)
        assert l.diff_sets == 6

    def test_diff_points(self):
        l = LigneClassement(equipe_id=1, equipe_nom="T", points_marques=300, points_encaisses=250)
        assert l.diff_points == 50

    def test_taux_victoire_zero_matchs(self):
        l = LigneClassement(equipe_id=1, equipe_nom="T")
        assert l.taux_victoire == 0.0
