"""Tests des métriques side-out / break côté vue match."""

from types import SimpleNamespace
from typing import cast

from pyvolley.database.models import MatchDB
from pyvolley.core.models import Equipe, Match, Set, SetTeamData
from pyvolley.web.routes.matchs import _compute_team_phase_metrics, _summarize_team_players


def test_compute_team_phase_metrics_from_service_timeline():
    """Calcule les ratios side-out / break sur une timeline simple et cohérente."""
    match_core = Match(
        code_match="PHASE-001",
        equipe_a=Equipe(nom="Equipe A"),
        equipe_b=Equipe(nom="Equipe B"),
        sets=[
            Set(
                numero=1,
                score_a=6,
                score_b=4,
                service_initial="A",
                equipe_a=SetTeamData(services={1: [2, 4, 6]}),  # type: ignore[call-arg]
                equipe_b=SetTeamData(services={2: [2, 4]}),  # type: ignore[call-arg]
            )
        ],
    )

    metrics = _compute_team_phase_metrics(match_core)
    a = metrics["A"]
    b = metrics["B"]

    assert a["sets_total"] == 1
    assert a["sets_with_timeline"] == 1
    assert a["phase_coverage_pct"] == 100.0

    # Team A: break points/opportunités selon la timeline reconstruite.
    assert a["break_points"] == 4
    assert a["break_opportunities"] == 6
    assert a["break_point_ratio_pct"] == 66.7

    # Team A side-out on B serve turns: 2 succès sur 4 tentatives
    assert a["sideout_successes"] == 2
    assert a["sideout_attempts"] == 4
    assert a["sideout_efficacite_pct"] == 50.0

    # Team B: break points = 1 + 1, opportunities = 2 + 2
    assert b["break_points"] == 2
    assert b["break_opportunities"] == 4
    assert b["break_point_ratio_pct"] == 50.0

    # Team B side-out on A serve turns: 2 succès sur 6 tentatives
    assert b["sideout_successes"] == 2
    assert b["sideout_attempts"] == 6
    assert b["sideout_efficacite_pct"] == 33.3

    # Aucun first side-out immédiat dans ce scénario.
    assert a["first_sideout_efficacite_pct"] == 0.0
    assert b["first_sideout_efficacite_pct"] == 0.0


def test_summarize_team_players_uses_set_level_substitution_count_for_team_side():
    """Le total changements équipe doit refléter les événements de set, sans inflation joueur."""
    match = SimpleNamespace(
        sets=[
            SimpleNamespace(
                score_a=25,
                score_b=21,
                changements=[
                    SimpleNamespace(equipe="A"),
                    SimpleNamespace(equipe="A"),
                    SimpleNamespace(equipe="B"),
                ],
            ),
            SimpleNamespace(
                score_a=25,
                score_b=23,
                changements=[SimpleNamespace(equipe="A")],
            ),
        ],
        sanctions=[SimpleNamespace(equipe="A"), SimpleNamespace(equipe="B")],
    )

    items = [
        {
            "stats": {
                "nb_changements_total": 8,  # ne doit pas être utilisé pour l'équipe
                "services": 12,
                "max_serie": 3,
            }
        },
        {
            "stats": {
                "nb_changements_total": 7,  # ne doit pas être utilisé pour l'équipe
                "services": 10,
                "max_serie": 4,
            }
        },
    ]

    summary = _summarize_team_players(items, match=cast(MatchDB, match), side="A")

    assert summary["points_gagnes"] == 50
    assert summary["points_perdus"] == 44
    assert summary["points_joues"] == 94
    assert summary["changements"] == 3
    assert summary["sanctions"] == 1
