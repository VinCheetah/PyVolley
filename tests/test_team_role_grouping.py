"""Tests for team roster role grouping on team detail page."""

from types import SimpleNamespace

from pyvolley.web.routes.equipes import (
    ROLE_LIBERO,
    ROLE_MULTI,
    ROLE_SETTER,
    _build_roster_role_groups,
)


def _roster_entry(
    joueur_id: int,
    nom: str,
    prenom: str,
    matchs_joues: int,
    libero_count: int = 0,
) -> dict:
    return {
        "joueur": SimpleNamespace(id=joueur_id, nom=nom, prenom=prenom),
        "matchs_joues": matchs_joues,
        "capitaine_count": 0,
        "libero_count": libero_count,
        "numero_maillot": str(joueur_id),
    }


def test_build_roster_role_groups_marks_polyvalent_when_two_roles_are_close():
    roster = [
        _roster_entry(1, "ALPHA", "A", matchs_joues=10),
        _roster_entry(2, "BETA", "B", matchs_joues=9),
    ]

    role_samples = {
        1: [
            {
                "role_principal": "PASSEUR",
                "role_confiance": 0.72,
                "role_scores": {"PASSEUR": 0.82, "POINTU": 0.18},
            },
            {
                "role_principal": "PASSEUR",
                "role_confiance": 0.69,
                "role_scores": {"PASSEUR": 0.79, "POINTU": 0.21},
            },
        ],
        2: [
            {
                "role_principal": "PASSEUR",
                "role_confiance": 0.58,
                "role_scores": {"PASSEUR": 0.53, "POINTU": 0.47},
            },
            {
                "role_principal": "POINTU",
                "role_confiance": 0.61,
                "role_scores": {"PASSEUR": 0.49, "POINTU": 0.51},
            },
            {
                "role_principal": "PASSEUR",
                "role_confiance": 0.57,
                "role_scores": {"PASSEUR": 0.52, "POINTU": 0.48},
            },
            {
                "role_principal": "POINTU",
                "role_confiance": 0.6,
                "role_scores": {"PASSEUR": 0.48, "POINTU": 0.52},
            },
        ],
    }

    enriched_roster, grouped = _build_roster_role_groups(roster, role_samples)

    by_player = {entry["joueur"].id: entry["role_profile"] for entry in enriched_roster}
    assert by_player[1]["group_code"] == ROLE_SETTER
    assert by_player[2]["group_code"] == ROLE_MULTI
    assert len(by_player[2]["plausible_labels"]) >= 2

    group_codes = [group["code"] for group in grouped]
    assert ROLE_SETTER in group_codes
    assert ROLE_MULTI in group_codes


def test_build_roster_role_groups_falls_back_to_libero_without_stats():
    roster = [_roster_entry(9, "LIB", "L", matchs_joues=6, libero_count=4)]

    enriched_roster, grouped = _build_roster_role_groups(roster, role_samples_by_player={})

    profile = enriched_roster[0]["role_profile"]
    assert profile["group_code"] == ROLE_LIBERO
    assert profile["primary_code"] == ROLE_LIBERO
    assert grouped[0]["code"] == ROLE_LIBERO


def test_build_roster_role_groups_sorts_players_by_participation_inside_group():
    roster = [
        _roster_entry(11, "ONE", "A", matchs_joues=4),
        _roster_entry(12, "TWO", "B", matchs_joues=8),
    ]
    role_samples = {
        11: [
            {
                "role_principal": "PASSEUR",
                "role_confiance": 0.55,
                "role_scores": {"PASSEUR": 0.7, "POINTU": 0.3},
            }
        ],
        12: [
            {
                "role_principal": "PASSEUR",
                "role_confiance": 0.6,
                "role_scores": {"PASSEUR": 0.76, "POINTU": 0.24},
            }
        ],
    }

    _, grouped = _build_roster_role_groups(roster, role_samples)
    setter_group = next(group for group in grouped if group["code"] == ROLE_SETTER)

    assert [player["joueur"].id for player in setter_group["players"]] == [12, 11]
