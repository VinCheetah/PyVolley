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
