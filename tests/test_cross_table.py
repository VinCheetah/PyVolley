"""
Tests pour le helper build_cross_table (matrice aller-retour des confrontations).
"""

from types import SimpleNamespace
from datetime import date
import pytest

from pyvolley.web.helpers.cross_table import build_cross_table, _generate_short_team_name
from pyvolley.analysis.classement import LigneClassement


def test_generate_short_team_name():
    assert _generate_short_team_name("PARIS VOLLEY CLUB") == "PAR"
    assert _generate_short_team_name("TOURS VOLLEY-BALL") == "TOU"
    assert _generate_short_team_name("AS MONACO") == "MON"
    assert _generate_short_team_name("") == "EQ"


def test_build_cross_table_empty():
    res = build_cross_table([], [])
    assert res["nb_equipes"] == 0
    assert res["has_matches"] is False
    assert res["rows"] == []


def test_build_cross_table_aller_retour():
    # 3 équipes classées : Team 1 (6 pts), Team 2 (3 pts), Team 3 (0 pt)
    classement = [
        LigneClassement(rang=1, equipe_id=1, equipe_nom="Team Alpha", points=6),
        LigneClassement(rang=2, equipe_id=2, equipe_nom="Team Beta", points=3),
        LigneClassement(rang=3, equipe_id=3, equipe_nom="Team Gamma", points=0),
    ]

    # Matchs :
    # 1 vs 2 : 1 gagne 3-1 à domicile
    # 2 vs 1 : 2 perd 2-3 à domicile (1 gagne 3-2)
    # 1 vs 3 : 1 gagne 3-0 à domicile
    # 3 vs 1 : match non joué (prévu J5)
    # 2 vs 3 : 2 gagne 3-0 à domicile
    # 3 vs 2 : 3 perd 0-3 par forfait
    matchs = [
        SimpleNamespace(
            id=101,
            code_match="M1",
            date_match=date(2025, 10, 1),
            journee="1",
            equipe_a_id=1,
            equipe_b_id=2,
            sets_equipe_a=3,
            sets_equipe_b=1,
            match_joue=True,
            is_played=True,
            forfait=False,
            statut="joué",
            sets=[SimpleNamespace(numero=1, score_a=25, score_b=20), SimpleNamespace(numero=2, score_a=25, score_b=22)],
        ),
        SimpleNamespace(
            id=102,
            code_match="M2",
            date_match=date(2025, 11, 1),
            journee="4",
            equipe_a_id=2,
            equipe_b_id=1,
            sets_equipe_a=2,
            sets_equipe_b=3,
            match_joue=True,
            is_played=True,
            forfait=False,
            statut="joué",
            sets=[],
        ),
        SimpleNamespace(
            id=103,
            code_match="M3",
            date_match=date(2025, 10, 8),
            journee="2",
            equipe_a_id=1,
            equipe_b_id=3,
            sets_equipe_a=3,
            sets_equipe_b=0,
            match_joue=True,
            is_played=True,
            forfait=False,
            statut="joué",
            sets=[],
        ),
        SimpleNamespace(
            id=104,
            code_match="M4",
            date_match=date(2025, 12, 1),
            journee="5",
            equipe_a_id=3,
            equipe_b_id=1,
            sets_equipe_a=0,
            sets_equipe_b=0,
            match_joue=False,
            is_played=False,
            forfait=False,
            statut="à_venir",
            sets=[],
        ),
        SimpleNamespace(
            id=105,
            code_match="M5",
            date_match=date(2025, 10, 15),
            journee="3",
            equipe_a_id=2,
            equipe_b_id=3,
            sets_equipe_a=3,
            sets_equipe_b=0,
            match_joue=True,
            is_played=True,
            forfait=False,
            statut="joué",
            sets=[],
        ),
        SimpleNamespace(
            id=106,
            code_match="M6",
            date_match=date(2025, 12, 8),
            journee="6",
            equipe_a_id=3,
            equipe_b_id=2,
            sets_equipe_a=0,
            sets_equipe_b=3,
            match_joue=True,
            is_played=True,
            forfait=True,
            statut="forfait",
            sets=[],
        ),
    ]

    res = build_cross_table(classement, matchs)

    assert res["nb_equipes"] == 3
    assert len(res["rows"]) == 3
    assert res["nb_matchs_joues"] == 5
    assert res["nb_matchs_total"] == 6

    # ── Vérifier les diagonales ──
    for i in range(3):
        diag_cell = res["rows"][i]["cells"][i]
        assert diag_cell["is_diagonal"] is True
        assert diag_cell["css_class"] == "matrix-cell-diagonal"

    # ── Ligne 0 : Team Alpha (hôte) ──
    row0 = res["rows"][0]
    assert row0["hote"]["id"] == 1

    # Cellule (1, 2) : 1 reçoit 2, score 3-1
    cell_1_2 = row0["cells"][1]
    assert cell_1_2["has_match"] is True
    assert cell_1_2["is_played"] is True
    assert cell_1_2["score_display"] == "3-1"
    assert cell_1_2["victoire_hote"] is True
    assert cell_1_2["css_class"] == "matrix-cell-win-3-1"
    assert cell_1_2["points_hote"] == 3
    assert cell_1_2["sets_detail_str"] == "25-20, 25-22"

    # Cellule (1, 3) : 1 reçoit 3, score 3-0
    cell_1_3 = row0["cells"][2]
    assert cell_1_3["score_display"] == "3-0"
    assert cell_1_3["victoire_hote"] is True
    assert cell_1_3["css_class"] == "matrix-cell-win-3-0"
    assert cell_1_3["points_hote"] == 3

    # ── Ligne 1 : Team Beta (hôte) ──
    row1 = res["rows"][1]
    # Cellule (2, 1) : 2 reçoit 1, score 2-3 (défaite hôte au tie-break)
    cell_2_1 = row1["cells"][0]
    assert cell_2_1["score_display"] == "2-3"
    assert cell_2_1["victoire_hote"] is False
    assert cell_2_1["css_class"] == "matrix-cell-loss-2-3"
    assert cell_2_1["points_hote"] == 1  # 1 point gagné au tie-break

    # ── Ligne 2 : Team Gamma (hôte) ──
    row2 = res["rows"][2]
    # Cellule (3, 1) : 3 reçoit 1, match à venir J5
    cell_3_1 = row2["cells"][0]
    assert cell_3_1["is_played"] is False
    assert cell_3_1["css_class"] == "matrix-cell-upcoming"
    assert "J5" in cell_3_1["score_display"]

    # Cellule (3, 2) : 3 reçoit 2, défaite par forfait
    cell_3_2 = row2["cells"][1]
    assert cell_3_2["is_forfait"] is True
    assert cell_3_2["victoire_hote"] is False
    assert cell_3_2["css_class"] == "matrix-cell-forfait-loss"

    # ── Statistiques de victoires à domicile ──
    # Victoires hôtes : (1,2)->V, (1,3)->V, (2,3)->V => 3 victoires dom
    # Défaites hôtes : (2,1)->D (2-3), (3,2)->D (forfait) => 2 défaites dom
    assert res["victoires_domicile"] == 3
    assert res["victoires_exterieur"] == 2
    assert res["pct_victoires_domicile"] == 60.0


def test_build_cross_table_with_matchdb_and_no_classement():
    """Vérifie que les matchs MatchDB sans classement préalable extraient correctement les équipes et scores."""
    matchs = [
        SimpleNamespace(
            id=201,
            code_match="M201",
            date_match=date(2025, 10, 1),
            journee="1",
            equipe_a_id=10,
            equipe_b_id=20,
            equipe_a=SimpleNamespace(nom="Lyon Volley"),
            equipe_b=SimpleNamespace(nom="Nice Volley"),
            sets_equipe_a=3,
            sets_equipe_b=1,
            match_joue=True,
            forfait=False,
            score_sets="25/20 25/22 20/25 25/18",
            sets=[],
        ),
    ]

    res = build_cross_table([], matchs)

    assert res["nb_equipes"] == 2
    assert res["nb_matchs_joues"] == 1
    assert res["nb_matchs_total"] == 1
    assert res["victoires_domicile"] == 1
    assert len(res["rows"]) == 2

    # L'équipe hôte 10 doit avoir le match contre l'équipe 20
    row_lyon = [r for r in res["rows"] if r["hote"]["id"] == 10][0]
    cell_vs_nice = [c for c in row_lyon["cells"] if c.get("guest_id") == 20][0]
    assert cell_vs_nice["has_match"] is True
    assert cell_vs_nice["is_played"] is True
    assert cell_vs_nice["score_display"] == "3-1"
    assert cell_vs_nice["css_class"] == "matrix-cell-win-3-1"
    assert cell_vs_nice["sets_detail_str"] == "25-20, 25-22, 20-25, 25-18"


def test_build_cross_table_with_equipes_disponibles():
    """Vérifie que des équipes inscrites sans classement ni matchs apparaissent dans la matrice."""
    equipes = [
        SimpleNamespace(id=1, nom="Toulouse VB"),
        SimpleNamespace(id=2, nom="Cannes VB"),
        SimpleNamespace(id=3, nom="Rennes VB"),
    ]

    res = build_cross_table([], [], equipes_disponibles=equipes)

    assert res["nb_equipes"] == 3
    assert len(res["rows"]) == 3
    assert res["nb_matchs_joues"] == 0
    assert res["nb_matchs_total"] == 0
    for r in res["rows"]:
        assert len(r["cells"]) == 3


def test_build_cross_table_double_forfait():
    """Vérifie le traitement d'un double forfait dans la matrice."""
    classement = [
        LigneClassement(rang=1, equipe_id=1, equipe_nom="Equipe A", points=0),
        LigneClassement(rang=2, equipe_id=2, equipe_nom="Equipe B", points=0),
    ]
    matchs = [
        SimpleNamespace(
            id=301,
            code_match="M301",
            date_match=date(2025, 10, 1),
            journee="1",
            equipe_a_id=1,
            equipe_b_id=2,
            sets_equipe_a=0,
            sets_equipe_b=0,
            score_sets="P-P",
            forfait=True,
            is_double_forfait=True,
            statut="forfait",
            match_joue=True,
            is_played=True,
            sets=[],
        )
    ]

    res = build_cross_table(classement, matchs)

    assert res["nb_matchs_joues"] == 1
    assert res["scores_distribution"]["forfait"] == 1

    cell = res["rows"][0]["cells"][1]
    assert cell["has_match"] is True
    assert cell["is_played"] is True
    assert cell["is_forfait"] is True
    assert cell["score_display"] == "P-P"
    assert cell["badge_label"] == "2F"
    assert cell["css_class"] == "matrix-cell-forfait-double"
    assert cell["points_hote"] == -1
    assert cell["points_visiteur"] == -1
    assert cell["victoire_hote"] is False


def test_build_cross_table_single_forfait_penalite():
    """Vérifie les points (-1 pour l'équipe forfaite, +3 pour l'autre) dans la matrice."""
    classement = [
        LigneClassement(rang=1, equipe_id=1, equipe_nom="Equipe A", points=3),
        LigneClassement(rang=2, equipe_id=2, equipe_nom="Equipe B", points=-1),
    ]
    # Match où l'équipe B déclare forfait chez l'équipe A
    matchs = [
        SimpleNamespace(
            id=401,
            code_match="M401",
            date_match=date(2025, 10, 1),
            journee="1",
            equipe_a_id=1,
            equipe_b_id=2,
            sets_equipe_a=3,
            sets_equipe_b=0,
            score_sets="3-P",
            forfait=True,
            is_double_forfait=False,
            statut="forfait",
            match_joue=True,
            is_played=True,
            sets=[],
        )
    ]

    res = build_cross_table(classement, matchs)
    cell = res["rows"][0]["cells"][1]
    assert cell["score_display"] == "3-0"
    assert cell["badge_label"] == "F"
    assert cell["css_class"] == "matrix-cell-forfait-win"
    assert cell["points_hote"] == 3
    assert cell["points_visiteur"] == -1

