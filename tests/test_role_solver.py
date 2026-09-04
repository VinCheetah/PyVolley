"""Tests complets pour le solveur compositionnel de rôles (TeamRoleSolver)."""

import pytest
from pyvolley.analysis.role_solver import (
    ROLE_SETTER,
    ROLE_OPPOSITE,
    ROLE_MIDDLE,
    ROLE_OUTSIDE,
    ROLE_LIBERO,
    TeamMatchContext,
    PlayerLocalEvidence,
    TeamRoleSolver,
    extract_team_context,
)
from pyvolley.core.models import (
    Match,
    Equipe,
    Joueur,
    Set,
    SetTeamData,
    Formation,
    Changement,
)


def _create_mock_6_player_set(set_num: int = 1) -> Set:
    """Crée un set avec formation 1 à 6 standard."""
    return Set(
        numero=set_num,
        score_a=25,
        score_b=20,
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
                # Remplacement libéro #7 pour le central #2 en zone arrière
                Changement(
                    joueur_entrant="7",
                    joueur_sortant="2",
                    position=5,
                    score_a=10,
                    score_b=8,
                ),
            ],
        ),
    )


def test_solver_rotation_pairs_and_triplets():
    """Vérifie que les triplets opposés (1,4), (2,5), (3,6) déduisent P, O, C, RA."""
    s1 = _create_mock_6_player_set(1)
    s2 = _create_mock_6_player_set(2)

    team_players = [
        Joueur(numero="1", nom="Passeur", prenom="A", licence="101"),
        Joueur(numero="2", nom="Central1", prenom="A", licence="102"),
        Joueur(numero="3", nom="RA1", prenom="A", licence="103"),
        Joueur(numero="4", nom="Pointu", prenom="A", licence="104"),
        Joueur(numero="5", nom="Central2", prenom="A", licence="105"),
        Joueur(numero="6", nom="RA2", prenom="A", licence="106"),
        Joueur(numero="7", nom="Libero", prenom="A", licence="107", est_libero=True),
    ]

    match = Match(
        code_match="TEST-SOLVER-01",
        equipe_a=Equipe(nom="Team A", joueurs=team_players, liberos=[team_players[-1]]),
        equipe_b=Equipe(nom="Team B", joueurs=[], liberos=[]),
        sets=[s1, s2],
        sets_a=2,
        sets_b=0,
        match_joue=True,
        has_details=True,
    )

    ctx = extract_team_context(match, "A")
    assert len(ctx.set_triplets) == 2
    assert ctx.players["7"].is_explicit_libero

    solver = TeamRoleSolver(ctx)
    results = solver.solve()

    # Le joueur 1 commence en P1 (serveur de départ) -> Passeur
    assert results["1"].role_principal == ROLE_SETTER
    # Le joueur 4 est diamétralement opposé en rotation au passeur -> Pointu
    assert results["4"].role_principal == ROLE_OPPOSITE
    # Le joueur 2 est remplacé par le libéro -> Central
    assert results["2"].role_principal == ROLE_MIDDLE
    # Le joueur 5 est opposé au central #2 -> Central
    assert results["5"].role_principal == ROLE_MIDDLE
    # Le 3e binôme #3 et #6 est déduit comme Réceptionneurs-Attaquants
    assert results["3"].role_principal == ROLE_OUTSIDE
    assert results["6"].role_principal == ROLE_OUTSIDE
    # Le libéro explicite
    assert results["7"].role_principal == ROLE_LIBERO
    assert results["7"].role_confiance >= 0.95


def test_solver_double_sub_passe_pointe_orientation():
    """Vérifie l'orientation correcte du double remplacement synchronisé."""
    set_one = Set(
        numero=1,
        score_a=25,
        score_b=22,
        equipe_a=SetTeamData(
            formation=Formation(
                position_1="10",
                position_2="20",
                position_3="30",
                position_4="40",
                position_5="50",
                position_6="60",
            ),
            changements=[
                # Double remplacement à 16-14 :
                # Pos 2 (avant) : 80 remplace 10 (qui a servi en P1)
                Changement(joueur_entrant="80", joueur_sortant="10", position=2, score_a=16, score_b=14),
                # Pos 5 (arrière) : 90 remplace 40
                Changement(joueur_entrant="90", joueur_sortant="40", position=5, score_a=16, score_b=14),
            ],
        ),
    )

    team_players = [
        Joueur(numero="10", nom="StartSetter", prenom="A", licence="110"),
        Joueur(numero="20", nom="Player20", prenom="A", licence="120"),
        Joueur(numero="30", nom="Player30", prenom="A", licence="130"),
        Joueur(numero="40", nom="StartOpp", prenom="A", licence="140"),
        Joueur(numero="50", nom="Player50", prenom="A", licence="150"),
        Joueur(numero="60", nom="Player60", prenom="A", licence="160"),
        Joueur(numero="80", nom="SubOpp", prenom="A", licence="180"),
        Joueur(numero="90", nom="SubSetter", prenom="A", licence="190"),
    ]

    match = Match(
        code_match="TEST-SOLVER-PP",
        equipe_a=Equipe(nom="Team A", joueurs=team_players, liberos=[]),
        equipe_b=Equipe(nom="Team B", joueurs=[], liberos=[]),
        sets=[set_one],
        sets_a=1,
        sets_b=0,
        match_joue=True,
        has_details=True,
    )

    ctx = extract_team_context(match, "A")
    solver = TeamRoleSolver(ctx)
    results = solver.solve()

    assert results["10"].role_principal == ROLE_SETTER
    assert results["40"].role_principal == ROLE_OPPOSITE


def test_solver_atypical_role_detection_with_priors():
    """Vérifie qu'un joueur avec un prior établi est détecté comme atypique s'il change de poste."""
    ctx = TeamMatchContext(side="A")
    # Joueur #1 joue exceptionnellement Libéro sur ce match
    p1 = PlayerLocalEvidence(numero="1", is_explicit_libero=True)
    ctx.players["1"] = p1

    # Mais son prior de carrière / saison est Passeur à 90%
    priors = {"1": {ROLE_SETTER: 0.90, ROLE_LIBERO: 0.10}}

    solver = TeamRoleSolver(ctx, player_priors=priors)
    results = solver.solve()

    assert results["1"].role_principal == ROLE_LIBERO
    assert results["1"].role_atypique is True
