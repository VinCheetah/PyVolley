"""Tests ciblés pour l'analyse détaillée des stats joueur."""

from pyvolley.analysis.joueur_stats import analyze_joueur_match, aggregate_joueur_stats
from pyvolley.analysis.models import JoueurMatchDetailedStats
from pyvolley.core.models import Match, Equipe, Joueur, Set, SetTeamData, Formation


def test_points_gagnes_are_on_court_points():
    """points_gagnes doit compter les points de l'équipe pendant la présence."""
    joueur_a = Joueur(numero="1", nom="ALPHA", prenom="A", licence="123456")
    joueur_b = Joueur(numero="2", nom="BETA", prenom="B", licence="654321")

    match = Match(
        code_match="ANL-001",
        equipe_a=Equipe(nom="Equipe A", joueurs=[joueur_a], liberos=[]),
        equipe_b=Equipe(nom="Equipe B", joueurs=[joueur_b], liberos=[]),
        sets=[
            Set(
                numero=1,
                score_a=25,
                score_b=20,
                service_initial="A",
                equipe_a=SetTeamData(formation=Formation(position_1="1")),
                equipe_b=SetTeamData(formation=Formation(position_1="2")),
            )
        ],
        vainqueur="A",
        score_sets="1-0",
    )

    stats = analyze_joueur_match(match, "123456")
    assert stats is not None
    assert stats.points_gagnes == 25
    assert stats.points_perdus == 20
    assert stats.points_joues == 45
    assert stats.points_gagnes_service == 0


def test_service_series_metrics_are_exposed_with_clear_names():
    """Les métriques services/séries/max série sont calculées et cohérentes."""
    joueur_a = Joueur(numero="1", nom="ALPHA", prenom="A", licence="123456")
    joueur_b = Joueur(numero="2", nom="BETA", prenom="B", licence="654321")

    match = Match(
        code_match="ANL-002",
        equipe_a=Equipe(nom="Equipe A", joueurs=[joueur_a], liberos=[]),
        equipe_b=Equipe(nom="Equipe B", joueurs=[joueur_b], liberos=[]),
        sets=[
            Set(
                numero=1,
                score_a=25,
                score_b=20,
                service_initial="A",
                equipe_a=SetTeamData(
                    formation=Formation(position_1="1"),
                    services={1: [3, 8, 25]},
                ),
                equipe_b=SetTeamData(
                    formation=Formation(position_1="2"),
                    services={2: [4, 10, 15, 20]},
                ),
            )
        ],
        vainqueur="A",
        score_sets="1-0",
    )

    stats = analyze_joueur_match(match, "123456")
    assert stats is not None
    assert stats.services >= stats.serie
    assert stats.max_serie >= 1
    assert stats.moyenne_services_par_serie == round(stats.services / stats.serie, 2)

    # Champs de compatibilité
    assert stats.nb_services == stats.services
    assert stats.meilleure_serie == stats.max_serie

    # Nouveaux indicateurs côté service/side-out
    assert stats.points_gagnes_sideout == max(0, stats.points_gagnes - stats.points_gagnes_service)
    if stats.services > 0:
        assert stats.break_point_ratio == round(stats.points_gagnes_service / stats.services, 3)
    if stats.points_gagnes > 0:
        assert stats.sideout_contribution_ratio == round(stats.points_gagnes_sideout / stats.points_gagnes, 3)

    aggregated = aggregate_joueur_stats([stats])
    assert aggregated is not None
    assert aggregated.total_points_gagnes_sideout == stats.points_gagnes_sideout
    if aggregated.total_services > 0:
        assert aggregated.break_point_ratio_global == round(
            aggregated.total_points_gagnes_service / aggregated.total_services,
            3,
        )
    if aggregated.total_points_gagnes > 0:
        assert aggregated.ratio_points_gagnes_sideout_global == round(
            aggregated.total_points_gagnes_sideout / aggregated.total_points_gagnes,
            3,
        )


def test_aggregate_joueur_stats_includes_role_distribution():
    stats_setter = JoueurMatchDetailedStats(
        numero="1",
        nom="ALPHA",
        prenom="A",
        licence="123456",
        equipe="Equipe A",
        side="A",
        role_principal="PASSEUR",
        roles_possibles=["PASSEUR", "POINTU"],
        role_scores={"PASSEUR": 0.7, "POINTU": 0.3},
        role_confiance=0.66,
    )
    stats_opposite = JoueurMatchDetailedStats(
        numero="1",
        nom="ALPHA",
        prenom="A",
        licence="123456",
        equipe="Equipe B",
        side="B",
        role_principal="POINTU",
        roles_possibles=["POINTU", "PASSEUR"],
        role_scores={"POINTU": 0.8, "PASSEUR": 0.2},
        role_confiance=0.71,
    )

    aggregated = aggregate_joueur_stats([stats_setter, stats_opposite])
    assert aggregated is not None
    assert aggregated.role_distribution_matchs == {"PASSEUR": 1, "POINTU": 1}
    assert aggregated.role_principal_global in {"PASSEUR", "POINTU"}
    assert "PASSEUR" in aggregated.role_scores_moyens
    assert "POINTU" in aggregated.role_scores_moyens
    assert aggregated.roles_possibles_global
