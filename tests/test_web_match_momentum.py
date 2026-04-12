from types import SimpleNamespace

from pyvolley.core.models import Changement, Equipe, Formation, Match, Set, SetTeamData
from pyvolley.web.helpers.match_utils import build_momentum_data


def test_build_momentum_data_exposes_server_identity_and_rotation_updates():
    match_db = SimpleNamespace(
        equipe_a=SimpleNamespace(nom="Team A"),
        equipe_b=SimpleNamespace(nom="Team B"),
        equipe_a_id=1,
        equipe_b_id=2,
        participations=[
            SimpleNamespace(
                equipe_id=1,
                numero_maillot="01",
                joueur=SimpleNamespace(nom="DUPONT", prenom="Leo"),
            ),
            SimpleNamespace(
                equipe_id=1,
                numero_maillot="7",
                joueur=SimpleNamespace(nom="MARTIN", prenom="Max"),
            ),
            SimpleNamespace(
                equipe_id=2,
                numero_maillot="2",
                joueur=SimpleNamespace(nom="BETA", prenom="Bo"),
            ),
        ],
        sets=[
            SimpleNamespace(
                numero=1,
                score_a=25,
                score_b=20,
                timeouts=[],
                changements=[],
            )
        ],
    )

    core_set = Set(
        numero=1,
        score_a=25,
        score_b=20,
        service_initial="A",
        equipe_a=SetTeamData(
            formation=Formation(position_1="1"),
            services={1: [3, 8, 25]},
            changements=[
                Changement(
                    joueur_entrant="7",
                    joueur_sortant="1",
                    position=1,
                    score_a=4,
                    score_b=4,
                )
            ],
        ),
        equipe_b=SetTeamData(
            formation=Formation(position_2="2"),
            services={2: [4, 10, 15, 20]},
        ),
    )
    match_core = Match(
        code_match="MOM-001",
        equipe_a=Equipe(nom="Team A"),
        equipe_b=Equipe(nom="Team B"),
        sets=[core_set],
    )

    payload = build_momentum_data(match_db, match_core)

    points = payload["sets"][0]["points"]

    first_service_point = next(
        point for point in points if point.get("phase") == "service" and point["score_a"] == 1 and point["score_b"] == 0
    )
    assert first_service_point["server"] == {
        "team": "A",
        "numero": "01",
        "nom": "DUPONT",
        "prenom": "Leo",
    }

    after_rotation_service_point = next(
        point for point in points if point.get("phase") == "service" and point["score_a"] == 5 and point["score_b"] == 4
    )
    assert after_rotation_service_point["server"] == {
        "team": "A",
        "numero": "7",
        "nom": "MARTIN",
        "prenom": "Max",
    }

    sideout_point = next(point for point in points if point.get("phase") == "sideout")
    assert sideout_point["server"]["team"] in {"A", "B"}
    assert "set_numero" in sideout_point


def test_build_momentum_data_adds_coach_decision_analysis_with_adaptive_score():
    match_db = SimpleNamespace(
        equipe_a=SimpleNamespace(nom="Team A"),
        equipe_b=SimpleNamespace(nom="Team B"),
        equipe_a_id=1,
        equipe_b_id=2,
        participations=[],
        sets=[
            SimpleNamespace(
                numero=1,
                score_a=25,
                score_b=20,
                timeouts=[SimpleNamespace(equipe="A", score_a=12, score_b=12)],
                changements=[
                    SimpleNamespace(
                        equipe="A",
                        joueur_entrant="7",
                        joueur_sortant="1",
                        score_a=8,
                        score_b=8,
                    )
                ],
            )
        ],
    )

    core_set = Set(
        numero=1,
        score_a=25,
        score_b=20,
        service_initial="A",
        equipe_a=SetTeamData(
            formation=Formation(position_1="1"),
            services={1: [3, 8, 25]},
            changements=[
                Changement(
                    joueur_entrant="7",
                    joueur_sortant="1",
                    position=1,
                    score_a=8,
                    score_b=8,
                )
            ],
        ),
        equipe_b=SetTeamData(
            formation=Formation(position_2="2"),
            services={2: [4, 10, 15, 20]},
        ),
    )
    match_core = Match(
        code_match="MOM-002",
        equipe_a=Equipe(nom="Team A"),
        equipe_b=Equipe(nom="Team B"),
        sets=[core_set],
    )

    payload = build_momentum_data(match_db, match_core)

    analysis = payload.get("coach_analysis")
    assert analysis is not None
    assert analysis["total_decisions"] == 2
    assert analysis["total_substitutions"] == 1
    assert analysis["total_timeouts"] == 1

    sub_decision = next(d for d in analysis["decisions"] if d["type"] == "sub")
    assert sub_decision["id"].startswith("S1-A-SUB-")
    assert -100.0 <= sub_decision["impact_score"] <= 100.0
    assert "trend_delta" in sub_decision
    assert "win_rate_pct" in sub_decision["trend_delta"]
    assert sub_decision["context"]["window_after_points"] > 0

    sub_event = next(e for e in payload["sets"][0]["events"] if e["type"] == "sub")
    assert sub_event["decision_id"] == sub_decision["id"]
    assert isinstance(sub_event["impact_score"], float)


def test_build_momentum_data_keeps_coach_analysis_when_service_timeline_missing():
    """Même sans détails de services, l'analyse coach doit rester exploitable."""
    match_db = SimpleNamespace(
        equipe_a=SimpleNamespace(nom="Team A"),
        equipe_b=SimpleNamespace(nom="Team B"),
        equipe_a_id=1,
        equipe_b_id=2,
        participations=[],
        sets=[
            SimpleNamespace(
                numero=1,
                score_a=25,
                score_b=23,
                timeouts=[SimpleNamespace(equipe="A", score_a=10, score_b=10)],
                changements=[
                    SimpleNamespace(
                        equipe="B",
                        joueur_entrant="9",
                        joueur_sortant="3",
                        score_a=18,
                        score_b=17,
                    )
                ],
            )
        ],
    )

    # Aucune donnée de services: build_set_timeline retourne [] et on bascule en fallback.
    core_set = Set(
        numero=1,
        score_a=25,
        score_b=23,
        service_initial="A",
        equipe_a=SetTeamData(formation=Formation(position_1="1"), services={}),
        equipe_b=SetTeamData(formation=Formation(position_2="2"), services={}),
    )
    match_core = Match(
        code_match="MOM-003",
        equipe_a=Equipe(nom="Team A"),
        equipe_b=Equipe(nom="Team B"),
        sets=[core_set],
    )

    payload = build_momentum_data(match_db, match_core)

    assert payload["sets"]
    fallback_points = payload["sets"][0]["points"]
    assert fallback_points[-1]["score_a"] == 25
    assert fallback_points[-1]["score_b"] == 23

    analysis = payload.get("coach_analysis")
    assert analysis is not None
    assert analysis["total_decisions"] == 2
    assert analysis["total_timeouts"] == 1
    assert analysis["total_substitutions"] == 1
