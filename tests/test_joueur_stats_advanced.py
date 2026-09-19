"""Tests complets pour les nouvelles statistiques avancées des joueurs.

Valide :
- Volume & Participation (sets joués, gagnés, perdus, commencés, terminés, match complet, DNP, présence relative)
- Substitutions avancées (in-out et out-in)
- On/Off Net Impact & Plus/Minus (différentiel de points gagnés avec vs sans le joueur)
- Rotations P1 à P6 (points joués, gagnés, win rate par zone)
- Situations de Score & Clutch (égalité, en tête, menée, money time >= 20, balles de set/match sauvées/converties)
- Temps de jeu estimé (somme des ratios x durées de set)
"""

from pyvolley.analysis.joueur_stats import analyze_joueur_match, aggregate_joueur_stats
from pyvolley.core.models import Match, Equipe, Joueur, Set, SetTeamData, Formation, Changement


def test_participation_and_substitutions():
    """Vérifie sets commencés/terminés, titularisation set 1, entrées-sorties et sorties-entrées."""
    j1 = Joueur(numero="10", nom="DUPONT", prenom="Jean", licence="100010")
    j2 = Joueur(numero="5", nom="DURAND", prenom="Paul", licence="100005")
    j_bench = Joueur(numero="99", nom="BENCH", prenom="Bob", licence="100099")

    # Match de 2 sets
    # Set 1: J10 titulaire en P1, sorti à 10-10 (J5 entre), puis ré-entre à 15-15 (J5 sort). J10 termine le set.
    # Set 2: J10 sur le banc au début. Entre à 5-5 (sort à 8-8). Puis re-rentre à 20-20 et termine le set.
    match = Match(
        code_match="TEST-ADV-01",
        equipe_a=Equipe(nom="Team A", joueurs=[j1, j2, j_bench], liberos=[]),
        equipe_b=Equipe(nom="Team B", joueurs=[Joueur(numero="1", nom="ADV", prenom="A", licence="200001")], liberos=[]),
        sets_a=2,
        sets_b=0,
        sets=[
            Set(
                numero=1,
                score_a=25,
                score_b=20,
                service_initial="A",
                duree_minutes=25,
                equipe_a=SetTeamData(
                    formation=Formation(position_1="10", position_2="2", position_3="3", position_4="4", position_5="5", position_6="6"),
                    changements=[
                        Changement(joueur_entrant="5", joueur_sortant="10", position=1, score_a=10, score_b=10),
                        Changement(joueur_entrant="10", joueur_sortant="5", position=1, score_a=15, score_b=15),
                    ],
                ),
                equipe_b=SetTeamData(
                    formation=Formation(position_1="1"),
                ),
            ),
            Set(
                numero=2,
                score_a=25,
                score_b=18,
                service_initial="B",
                duree_minutes=20,
                equipe_a=SetTeamData(
                    formation=Formation(position_1="5", position_2="2", position_3="3", position_4="4", position_5="7", position_6="6"),
                    changements=[
                        Changement(joueur_entrant="10", joueur_sortant="5", position=1, score_a=5, score_b=5),
                        Changement(joueur_entrant="5", joueur_sortant="10", position=1, score_a=8, score_b=8),
                        Changement(joueur_entrant="10", joueur_sortant="5", position=1, score_a=20, score_b=20),
                    ],
                ),
                equipe_b=SetTeamData(
                    formation=Formation(position_1="1"),
                ),
            ),
        ],
        vainqueur="A",
        score_sets="2-0",
    )

    stats10 = analyze_joueur_match(match, "100010")
    assert stats10 is not None

    # Set 1: titulaire, sorti puis ré-entré -> 1 sortie-entrée
    # Set 2: non titulaire, entré puis sorti -> 1 entrée-sortie, puis re-entré
    assert stats10.sets_joues == 2
    assert stats10.sets_gagnes == 2
    assert stats10.sets_perdus == 0
    assert stats10.sets_commences == 1
    assert stats10.sets_titulaire == 1
    assert stats10.titulaire_set_1 is True
    assert stats10.sets_termines == 2  # terminé sur le terrain les 2 sets
    assert stats10.match_complet is False  # a passé du temps sur le banc
    assert stats10.match_non_joue is False
    assert stats10.nb_sorties_entrees >= 1
    assert stats10.nb_entrees_sorties >= 1

    # Joueur de banc jamais entré
    stats_bench = analyze_joueur_match(match, "100099")
    assert stats_bench is not None
    assert stats_bench.sets_joues == 0
    assert stats_bench.match_non_joue is True
    assert stats_bench.presence_relative == 0.0


def test_on_off_net_impact_and_time():
    """Vérifie le calcul On/Off, plus/minus, différentiel et temps de jeu estimé."""
    j1 = Joueur(numero="10", nom="STAR", prenom="S", licence="100010")
    j_opp = Joueur(numero="1", nom="OPP", prenom="O", licence="200001")

    # Set de 25-20 (total 45 points), durée 20 min.
    # Star joue de 0-0 à 10-5 (+5 en 15 pts), banc de 10-5 à 15-15 (5-10 = -5 pour team en 15 pts),
    # puis re-joue de 15-15 à 25-20 (10-5 = +5 en 15 pts).
    # Sur le terrain (ON) : points joués = 30, points gagnés = 20, points perdus = 10 -> ratio_on = 20/30 = 0.667.
    # Sur le banc (OFF) : points joués = 15, points gagnés = 5, points perdus = 10 -> ratio_off = 5/15 = 0.333.
    # Différentiel On/Off = 0.667 - 0.333 = +0.334 (+33.4% avec le joueur sur le terrain !).
    # Temps de jeu : ratio = 30/45 = 0.667 * 20 min = 13.3 min.
    match = Match(
        code_match="TEST-ADV-02",
        equipe_a=Equipe(nom="Team A", joueurs=[j1], liberos=[]),
        equipe_b=Equipe(nom="Team B", joueurs=[j_opp], liberos=[]),
        sets=[
            Set(
                numero=1,
                score_a=25,
                score_b=20,
                service_initial="A",
                duree_minutes=20,
                equipe_a=SetTeamData(
                    formation=Formation(position_1="10"),
                    changements=[
                        Changement(joueur_entrant="2", joueur_sortant="10", position=1, score_a=10, score_b=5),
                        Changement(joueur_entrant="10", joueur_sortant="2", position=1, score_a=15, score_b=15),
                    ],
                ),
                equipe_b=SetTeamData(
                    formation=Formation(position_1="1"),
                ),
            )
        ],
        vainqueur="A",
        score_sets="1-0",
    )

    stats = analyze_joueur_match(match, "100010")
    assert stats is not None

    assert stats.points_joues == 30
    assert stats.points_gagnes == 20
    assert stats.points_perdus == 10
    assert stats.plus_minus == 10
    assert stats.ratio_points_gagnes == 0.667

    assert stats.points_joues_off == 15
    assert stats.points_gagnes_off == 5
    assert stats.ratio_points_gagnes_off == 0.333
    assert stats.differentiel_points_gagnes == round(0.667 - 0.333, 3)

    assert stats.presence_relative == round(30 / 45, 3)
    assert stats.temps_jeu_estime == 13.3


def test_clutch_and_rotations():
    """Vérifie le calcul point par point des rotations P1-P6 et des situations de clutch."""
    j_srv = Joueur(numero="7", nom="CLUTCH", prenom="C", licence="100007")
    j_adv = Joueur(numero="1", nom="ADV", prenom="A", licence="200001")

    # Set 1 où Team A est menée 20-24 (balles de set adverse !).
    # Joueur 7 est au service en position 1.
    # Il marque 4 points consécutifs au service : 21-24, 22-24, 23-24, 24-24 (4 balles de set sauvées !).
    # Puis 25-24 (balle de set équipe), et 26-24 (victoire set).
    # Tous ces points au service ont été joués en P1 !
    match = Match(
        code_match="TEST-ADV-03",
        equipe_a=Equipe(nom="Team A", joueurs=[j_srv], liberos=[]),
        equipe_b=Equipe(nom="Team B", joueurs=[j_adv], liberos=[]),
        sets_a=1,
        sets_b=0,
        sets=[
            Set(
                numero=1,
                score_a=26,
                score_b=24,
                service_initial="A",
                duree_minutes=30,
                equipe_a=SetTeamData(
                    formation=Formation(position_1="7", position_2="2", position_3="3", position_4="4", position_5="5", position_6="6"),
                    services={
                        1: [20, 26],  # Tour 0: score 20, puis dernier tour: remonte de 20 à 26 !
                    },
                ),
                equipe_b=SetTeamData(
                    formation=Formation(position_1="1"),
                    services={
                        1: [24],
                    },
                ),
            )
        ],
        vainqueur="A",
        score_sets="1-0",
    )

    stats = analyze_joueur_match(match, "100007")
    assert stats is not None

    # Rotations : P1 a joué et gagné des points au service
    assert stats.rotations.p1.points_joues > 0
    assert stats.rotations.p1.points_gagnes > 0
    assert stats.rotations.p1.win_rate > 0.0

    # Clutch : a affronté et sauvé des balles de set adverses
    assert stats.clutch.balles_de_set_adverse_total >= 4
    assert stats.clutch.balles_de_set_adverse_sauvees >= 4
    assert stats.clutch.win_rate_sauve_balle_set == 1.0
    assert stats.clutch.max_serie_sauve_balle_set >= 3

    # Money time (score >= 20)
    assert stats.clutch.points_money_time > 0
    assert stats.clutch.points_gagnes_money_time > 0

    # Agrégation multi-matchs
    aggregated = aggregate_joueur_stats([stats])
    assert aggregated is not None
    assert aggregated.total_sets_gagnes == 1
    assert aggregated.total_sets_joues == 1
    assert aggregated.rotations_globales.p1.points_gagnes == stats.rotations.p1.points_gagnes
    assert aggregated.clutch_global.balles_de_set_adverse_sauvees >= 4
    assert aggregated.clutch_global.max_serie_sauve_balle_set >= 3


def test_db_persistence_and_joueur_report():
    """Vérifie la persistance en base SQL et la génération du rapport CLI JoueurReport."""
    from datetime import date
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from pyvolley.database.models import (
        Base, JoueurDB, EquipeDB, ClubDB, CompetitionDB, SaisonDB, MatchDB, ParticipationMatchDB, JoueurMatchStatsDB
    )
    from pyvolley.database.repositories import JoueurMatchStatsRepository
    from pyvolley.reports.joueur import JoueurReport

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()

    saison = SaisonDB(code="2024-2025", nom="2024-2025")
    club = ClubDB(nom="Club Test")
    session.add_all([saison, club])
    session.flush()

    comp = CompetitionDB(nom="Nationale", niveau="NATIONALE", saison_id=saison.id)
    session.add(comp)
    session.flush()

    eq_a = EquipeDB(nom="Equipe A", club_id=club.id)
    eq_b = EquipeDB(nom="Equipe B", club_id=club.id)
    j = JoueurDB(nom="HEROIQUE", prenom="Lucas", licence="100077")
    session.add_all([eq_a, eq_b, j])
    session.flush()

    match = MatchDB(
        code_match="MATCH-77",
        date_match=date(2025, 3, 10),
        saison_id=saison.id,
        competition_id=comp.id,
        equipe_a_id=eq_a.id,
        equipe_b_id=eq_b.id,
        sets_equipe_a=3,
        sets_equipe_b=2,
        vainqueur="Equipe A",
        match_joue=True,
    )
    session.add(match)
    session.flush()

    part = ParticipationMatchDB(
        match_id=match.id,
        joueur_id=j.id,
        equipe_id=eq_a.id,
        numero_maillot="12",
    )
    session.add(part)
    session.flush()

    repo = JoueurMatchStatsRepository(session)
    stats_data = [
        {
            "joueur_id": j.id,
            "equipe_id": eq_a.id,
            "numero": "12",
            "victoire": True,
            "points_joues": 85,
            "points_gagnes": 48,
            "points_perdus": 37,
            "points_gagnes_service": 8,
            "points_gagnes_sideout": 40,
            "plus_minus": 11,
            "differentiel_points_gagnes": 0.082,
            "services": 22,
            "max_serie": 5,
            "max_services_set": 10,
            "sets_joues": 5,
            "sets_gagnes": 3,
            "sets_perdus": 2,
            "sets_commences": 5,
            "sets_titulaire": 5,
            "sets_termines": 5,
            "titulaire_set_1": True,
            "match_complet": True,
            "match_non_joue": False,
            "presence_relative": 0.88,
            "temps_jeu_estime": 105.5,
            "nb_entrees": 0,
            "nb_sorties": 0,
            "nb_entrees_sorties": 0,
            "nb_sorties_entrees": 0,
            "rotations": {
                "p1": {"points_joues": 15, "points_gagnes": 10, "points_perdus": 5, "win_rate": 0.667},
                "p2": {"points_joues": 12, "points_gagnes": 7, "points_perdus": 5, "win_rate": 0.583},
                "p3": {"points_joues": 14, "points_gagnes": 8, "points_perdus": 6, "win_rate": 0.571},
                "p4": {"points_joues": 16, "points_gagnes": 9, "points_perdus": 7, "win_rate": 0.562},
                "p5": {"points_joues": 13, "points_gagnes": 7, "points_perdus": 6, "win_rate": 0.538},
                "p6": {"points_joues": 15, "points_gagnes": 7, "points_perdus": 8, "win_rate": 0.467},
            },
            "clutch": {
                "points_egalite": 20,
                "points_gagnes_egalite": 12,
                "win_rate_egalite": 0.60,
                "points_en_tete": 35,
                "points_gagnes_en_tete": 22,
                "win_rate_en_tete": 0.629,
                "points_menee": 30,
                "points_gagnes_menee": 14,
                "win_rate_menee": 0.467,
                "points_money_time": 25,
                "points_gagnes_money_time": 15,
                "win_rate_money_time": 0.60,
                "balles_de_set_adverse_total": 3,
                "balles_de_set_adverse_sauvees": 3,
                "win_rate_sauve_balle_set": 1.0,
                "balles_de_match_adverse_total": 1,
                "balles_de_match_adverse_sauvees": 1,
                "win_rate_sauve_balle_match": 1.0,
                "balles_de_set_equipe_total": 4,
                "balles_de_set_equipe_converties": 3,
                "win_rate_balle_set_equipe": 0.75,
                "balles_de_match_equipe_total": 1,
                "balles_de_match_equipe_converties": 1,
                "win_rate_balle_match_equipe": 1.0,
                "max_serie_sauve_balle_set": 3,
                "max_serie_sauve_balle_match": 1,
            },
        }
    ]

    from datetime import datetime
    saved_entities = repo.replace_for_match(match.id, stats_data, match_updated_at=datetime.now(), flush=True)
    assert len(saved_entities) == 1
    db_entry = saved_entities[0]
    assert db_entry.plus_minus == 11
    assert db_entry.differentiel_points_gagnes == 0.082
    assert db_entry.temps_jeu_estime == 105.5
    assert db_entry.match_complet is True
    assert db_entry.titulaire_set_1 is True

    # Test conversion to_detailed_stats()
    detailed = db_entry.to_detailed_stats()
    assert detailed.plus_minus == 11
    assert detailed.differentiel_points_gagnes == 0.082
    assert detailed.rotations.p1.points_joues == 15
    assert detailed.clutch.balles_de_set_adverse_sauvees == 3
    assert detailed.clutch.win_rate_sauve_balle_match == 1.0

    # Test JoueurReport sections
    report = JoueurReport(session, j)
    sections_by_key = {s.key: s for s in report.build()}
    assert "profil" in sections_by_key
    assert "statistiques" in sections_by_key
    assert "performance_avancee" in sections_by_key
    assert "rotations" in sections_by_key
    assert "clutch" in sections_by_key
    assert not sections_by_key["performance_avancee"].empty
    assert not sections_by_key["rotations"].empty
    assert not sections_by_key["clutch"].empty

