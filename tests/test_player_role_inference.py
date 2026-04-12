"""Tests for heuristic player role inference."""

from pyvolley.analysis.joueur_stats import analyze_joueur_match
from pyvolley.analysis.role_inference import (
    ROLE_LIBERO,
    ROLE_OPPOSITE,
    ROLE_SETTER,
    infer_team_roles,
)
from pyvolley.core.models import (
    Changement,
    Equipe,
    Formation,
    Joueur,
    Match,
    Set,
    SetTeamData,
)


def _build_passe_pointe_match() -> Match:
    team_a_players = [
        Joueur(numero="1", nom="SETTER_A", prenom="A", licence="100001"),
        Joueur(numero="2", nom="OUT_A", prenom="A", licence="100002"),
        Joueur(numero="3", nom="MID_A", prenom="A", licence="100003"),
        Joueur(numero="4", nom="OPP_A", prenom="A", licence="100004"),
        Joueur(numero="5", nom="OUT_B", prenom="A", licence="100005"),
        Joueur(numero="6", nom="MID_B", prenom="A", licence="100006"),
        Joueur(numero="7", nom="SETTER_B", prenom="A", licence="100007"),
        Joueur(numero="8", nom="OPP_B", prenom="A", licence="100008"),
        Joueur(
            numero="9",
            nom="LIB",
            prenom="A",
            licence="100009",
            est_libero=True,
        ),
    ]

    team_b_players = [
        Joueur(numero="11", nom="B1", prenom="B", licence="200001"),
        Joueur(numero="12", nom="B2", prenom="B", licence="200002"),
        Joueur(numero="13", nom="B3", prenom="B", licence="200003"),
        Joueur(numero="14", nom="B4", prenom="B", licence="200004"),
        Joueur(numero="15", nom="B5", prenom="B", licence="200005"),
        Joueur(numero="16", nom="B6", prenom="B", licence="200006"),
    ]

    set_one = Set(
        numero=1,
        score_a=25,
        score_b=20,
        service_initial="A",
        equipe_a=SetTeamData(
            formation=Formation(
                position_1="1",
                position_2="2",
                position_3="3",
                position_4="4",
                position_5="5",
                position_6="6",
            ),
            changements=[
                # Inversion passe-pointe.
                Changement(
                    joueur_entrant="8",
                    joueur_sortant="1",
                    position=2,
                    score_a=8,
                    score_b=6,
                ),
                Changement(
                    joueur_entrant="7",
                    joueur_sortant="4",
                    position=5,
                    score_a=8,
                    score_b=6,
                ),
                # Reverse inversion later in the set.
                Changement(
                    joueur_entrant="1",
                    joueur_sortant="8",
                    position=2,
                    score_a=12,
                    score_b=10,
                ),
                Changement(
                    joueur_entrant="4",
                    joueur_sortant="7",
                    position=5,
                    score_a=12,
                    score_b=10,
                ),
                # Libero pattern for a middle.
                Changement(
                    joueur_entrant="9",
                    joueur_sortant="6",
                    position=6,
                    score_a=14,
                    score_b=12,
                ),
                Changement(
                    joueur_entrant="6",
                    joueur_sortant="9",
                    position=3,
                    score_a=18,
                    score_b=16,
                ),
            ],
        ),
        equipe_b=SetTeamData(
            formation=Formation(
                position_1="11",
                position_2="12",
                position_3="13",
                position_4="14",
                position_5="15",
                position_6="16",
            ),
        ),
    )

    return Match(
        code_match="ROLE-PP-001",
        equipe_a=Equipe(
            nom="Equipe A",
            joueurs=team_a_players,
            liberos=[team_a_players[-1]],
        ),
        equipe_b=Equipe(nom="Equipe B", joueurs=team_b_players, liberos=[]),
        sets=[set_one],
        sets_a=1,
        sets_b=0,
        match_joue=True,
        has_details=True,
    )


def _build_noisy_match() -> Match:
    team_a_players = [
        Joueur(numero="1", nom="P1", prenom="A", licence="300001"),
        Joueur(numero="2", nom="P2", prenom="A", licence="300002"),
        Joueur(numero="3", nom="P3", prenom="A", licence="300003"),
        Joueur(numero="4", nom="P4", prenom="A", licence="300004"),
        Joueur(numero="5", nom="P5", prenom="A", licence="300005"),
        Joueur(numero="6", nom="P6", prenom="A", licence="300006"),
        Joueur(numero="7", nom="LIB", prenom="A", licence="300007", est_libero=True),
        Joueur(numero="8", nom="SUB", prenom="A", licence="300008"),
    ]
    team_b_players = [
        Joueur(numero="21", nom="Q1", prenom="B", licence="400001"),
        Joueur(numero="22", nom="Q2", prenom="B", licence="400002"),
        Joueur(numero="23", nom="Q3", prenom="B", licence="400003"),
        Joueur(numero="24", nom="Q4", prenom="B", licence="400004"),
        Joueur(numero="25", nom="Q5", prenom="B", licence="400005"),
        Joueur(numero="26", nom="Q6", prenom="B", licence="400006"),
    ]

    set_one = Set(
        numero=1,
        score_a=25,
        score_b=23,
        service_initial="A",
        equipe_a=SetTeamData(
            formation=Formation(
                position_1="1",
                position_2="2",
                position_3="3",
                position_4="4",
                position_5="5",
                position_6="6",
            ),
            changements=[
                Changement(
                    joueur_entrant="7",
                    joueur_sortant="6",
                    position=6,
                    score_a=9,
                    score_b=8,
                ),
                Changement(
                    joueur_entrant="6",
                    joueur_sortant="7",
                    position=3,
                    score_a=14,
                    score_b=12,
                ),
                Changement(
                    joueur_entrant="8",
                    joueur_sortant="2",
                    position=4,
                    score_a=16,
                    score_b=15,
                ),
            ],
        ),
        equipe_b=SetTeamData(
            formation=Formation(
                position_1="21",
                position_2="22",
                position_3="23",
                position_4="24",
                position_5="25",
                position_6="26",
            ),
        ),
    )

    return Match(
        code_match="ROLE-NOISE-001",
        equipe_a=Equipe(
            nom="Equipe A",
            joueurs=team_a_players,
            liberos=[team_a_players[6]],
        ),
        equipe_b=Equipe(nom="Equipe B", joueurs=team_b_players, liberos=[]),
        sets=[set_one],
        sets_a=1,
        sets_b=0,
        match_joue=True,
        has_details=True,
    )


def test_infer_team_roles_detects_passe_pointe_pattern():
    match = _build_passe_pointe_match()

    roles = infer_team_roles(match, "A")

    assert roles["1"].role_principal == ROLE_SETTER
    assert roles["7"].role_principal == ROLE_SETTER
    assert roles["4"].role_principal == ROLE_OPPOSITE
    assert roles["8"].role_principal == ROLE_OPPOSITE
    assert roles["9"].role_principal == ROLE_LIBERO

    assert roles["1"].role_confiance > 0.52
    assert roles["4"].role_confiance > 0.52
    assert roles["9"].role_confiance > 0.60


def test_infer_team_roles_separates_setter_and_opposite_scores():
    match = _build_passe_pointe_match()

    roles = infer_team_roles(match, "A")

    setter_a = roles["1"].role_scores
    opposite_a = roles["4"].role_scores

    assert setter_a.get(ROLE_SETTER, 0.0) >= 0.55
    assert setter_a.get(ROLE_OPPOSITE, 0.0) <= 0.30

    assert opposite_a.get(ROLE_OPPOSITE, 0.0) >= 0.55
    assert opposite_a.get(ROLE_SETTER, 0.0) <= 0.30


def test_analyze_joueur_match_exposes_inferred_role_fields():
    match = _build_passe_pointe_match()

    stats = analyze_joueur_match(match, "100001")

    assert stats is not None
    assert stats.role_principal == ROLE_SETTER
    assert ROLE_SETTER in stats.roles_possibles
    assert stats.role_scores.get(ROLE_SETTER, 0.0) > stats.role_scores.get(ROLE_OPPOSITE, 0.0)
    assert stats.indices_roles


def test_infer_team_roles_stays_cautious_on_noisy_data():
    match = _build_noisy_match()

    roles = infer_team_roles(match, "A")

    assert roles["7"].role_principal == ROLE_LIBERO
    assert roles["1"].role_confiance < 0.60
