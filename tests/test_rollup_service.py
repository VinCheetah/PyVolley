"""
Tests pour le service de statistiques agglomérées (RollupStatsService).
"""

from datetime import date, datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pyvolley.database.models import (
    Base, SaisonDB, CompetitionDB, PouleDB, ClubDB, EquipeDB,
    JoueurDB, MatchDB, ParticipationMatchDB, JoueurMatchStatsDB,
    JoueurSaisonStatsDB, JoueurCarriereStatsDB, EquipeSaisonStatsDB,
)
from pyvolley.database.rollup_service import RollupStatsService
from pyvolley.database.repositories import (
    JoueurSaisonStatsRepository,
    JoueurCarriereStatsRepository,
    EquipeSaisonStatsRepository,
)


@pytest.fixture
def db_session():
    """Crée une base de données SQLite en mémoire pour les tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _populate_test_data(session):
    """Crée un jeu de données de test avec 2 saisons, 2 équipes et des matchs."""
    saison_1 = SaisonDB(code="2024-2025", nom="Saison 2024-2025")
    saison_2 = SaisonDB(code="2025-2026", nom="Saison 2025-2026")
    session.add_all([saison_1, saison_2])
    session.flush()

    comp_1 = CompetitionDB(nom="NATIONALE 2 MASCULINE", saison_id=saison_1.id, genre="MASCULIN", niveau="N2")
    comp_2 = CompetitionDB(nom="NATIONALE 2 MASCULINE", saison_id=saison_2.id, genre="MASCULIN", niveau="N2")
    session.add_all([comp_1, comp_2])
    session.flush()

    poule_1 = PouleDB(code="N2M_A", competition_id=comp_1.id)
    poule_2 = PouleDB(code="N2M_A", competition_id=comp_2.id)
    session.add_all([poule_1, poule_2])
    session.flush()

    club_a = ClubDB(nom="PARIS VOLLEY", code_ffvb="0750001")
    club_b = ClubDB(nom="TOURS VB", code_ffvb="0370002")
    session.add_all([club_a, club_b])
    session.flush()

    eq_a_s1 = EquipeDB(nom="PARIS VOLLEY", club_id=club_a.id, saison_id=saison_1.id, competition_id=comp_1.id)
    eq_b_s1 = EquipeDB(nom="TOURS VB", club_id=club_b.id, saison_id=saison_1.id, competition_id=comp_1.id)
    eq_a_s2 = EquipeDB(nom="PARIS VOLLEY", club_id=club_a.id, saison_id=saison_2.id, competition_id=comp_2.id)
    eq_b_s2 = EquipeDB(nom="TOURS VB", club_id=club_b.id, saison_id=saison_2.id, competition_id=comp_2.id)
    session.add_all([eq_a_s1, eq_b_s1, eq_a_s2, eq_b_s2])
    session.flush()

    j1 = JoueurDB(licence="1000001", nom="NGAPETH", prenom="EARVIN")
    j2 = JoueurDB(licence="1000002", nom="BRIZARD", prenom="ANTOINE")
    session.add_all([j1, j2])
    session.flush()

    # Match 1 (Saison 1): Paris 3 - 1 Tours (Paris gagne)
    m1 = MatchDB(
        code_match="M001",
        date_match=date(2024, 10, 12),
        saison_id=saison_1.id,
        competition_id=comp_1.id,
        poule_id=poule_1.id,
        equipe_a_id=eq_a_s1.id,
        equipe_b_id=eq_b_s1.id,
        sets_equipe_a=3,
        sets_equipe_b=1,
        match_joue=True,
        has_details=True,
    )
    session.add(m1)
    session.flush()

    # Participations M1
    p1 = ParticipationMatchDB(match_id=m1.id, joueur_id=j1.id, equipe_id=eq_a_s1.id, numero_maillot="09")
    p2 = ParticipationMatchDB(match_id=m1.id, joueur_id=j2.id, equipe_id=eq_b_s1.id, numero_maillot="06")
    session.add_all([p1, p2])
    session.flush()

    # Match Stats M1
    jms1 = JoueurMatchStatsDB(
        match_id=m1.id,
        joueur_id=j1.id,
        equipe_id=eq_a_s1.id,
        points_gagnes=22,
        points_perdus=6,
        points_joues=40,
        points_gagnes_service=3,
        points_gagnes_sideout=19,
        services=18,
        series=5,
        max_serie=4,
        role_principal="RECEPTEUR_ATTAQUANT",
        sets_joues=4,
        sets_titulaire=4,
    )
    jms2 = JoueurMatchStatsDB(
        match_id=m1.id,
        joueur_id=j2.id,
        equipe_id=eq_b_s1.id,
        points_gagnes=5,
        points_perdus=3,
        points_joues=38,
        points_gagnes_service=1,
        points_gagnes_sideout=4,
        services=12,
        series=4,
        max_serie=2,
        role_principal="PASSEUR",
        sets_joues=4,
        sets_titulaire=4,
    )
    session.add_all([jms1, jms2])
    session.flush()

    # Match 2 (Saison 2): Tours 3 - 0 Paris (Tours gagne)
    m2 = MatchDB(
        code_match="M002",
        date_match=date(2025, 11, 15),
        saison_id=saison_2.id,
        competition_id=comp_2.id,
        poule_id=poule_2.id,
        equipe_a_id=eq_b_s2.id,
        equipe_b_id=eq_a_s2.id,
        sets_equipe_a=3,
        sets_equipe_b=0,
        match_joue=True,
        has_details=True,
    )
    session.add(m2)
    session.flush()

    p3 = ParticipationMatchDB(match_id=m2.id, joueur_id=j1.id, equipe_id=eq_a_s2.id, numero_maillot="09")
    p4 = ParticipationMatchDB(match_id=m2.id, joueur_id=j2.id, equipe_id=eq_b_s2.id, numero_maillot="06")
    session.add_all([p3, p4])
    session.flush()

    jms3 = JoueurMatchStatsDB(
        match_id=m2.id,
        joueur_id=j1.id,
        equipe_id=eq_a_s2.id,
        points_gagnes=14,
        points_perdus=5,
        points_joues=30,
        points_gagnes_service=1,
        points_gagnes_sideout=13,
        services=10,
        series=3,
        max_serie=2,
        role_principal="RECEPTEUR_ATTAQUANT",
        sets_joues=3,
        sets_titulaire=3,
    )
    session.add(jms3)
    session.flush()

    return {
        "saison_1": saison_1,
        "saison_2": saison_2,
        "comp_1": comp_1,
        "comp_2": comp_2,
        "eq_a_s1": eq_a_s1,
        "eq_b_s1": eq_b_s1,
        "eq_a_s2": eq_a_s2,
        "eq_b_s2": eq_b_s2,
        "j1": j1,
        "j2": j2,
        "m1": m1,
        "m2": m2,
    }


def test_compute_player_season_stats(db_session):
    data = _populate_test_data(db_session)
    service = RollupStatsService(db_session)

    count = service.compute_player_season_stats()
    assert count > 0

    repo = JoueurSaisonStatsRepository(db_session)
    stats_j1_s1 = repo.get_by_key(
        joueur_id=data["j1"].id,
        saison_id=data["saison_1"].id,
        competition_id=data["comp_1"].id,
        equipe_id=data["eq_a_s1"].id,
    )
    assert stats_j1_s1 is not None
    assert stats_j1_s1.matchs_joues == 1
    assert stats_j1_s1.victoires == 1
    assert stats_j1_s1.points_gagnes == 22
    assert stats_j1_s1.services == 18
    assert stats_j1_s1.max_serie == 4
    assert stats_j1_s1.role_principal == "RECEPTEUR_ATTAQUANT"

    # Top scorers query
    top_scorers = repo.get_top_scorers(saison_id=data["saison_1"].id)
    assert len(top_scorers) >= 1
    assert top_scorers[0]["nom"] == "NGAPETH"
    assert top_scorers[0]["points"] == 22


def test_compute_team_season_stats(db_session):
    data = _populate_test_data(db_session)
    service = RollupStatsService(db_session)

    count = service.compute_team_season_stats()
    assert count > 0

    repo = EquipeSaisonStatsRepository(db_session)
    stats_paris_s1 = repo.get_by_key(
        equipe_id=data["eq_a_s1"].id,
        saison_id=data["saison_1"].id,
        competition_id=data["comp_1"].id,
    )
    assert stats_paris_s1 is not None
    assert stats_paris_s1.matchs_joues == 1
    assert stats_paris_s1.victoires == 1
    assert stats_paris_s1.victoires_3_1 == 1
    assert stats_paris_s1.sets_pour == 3
    assert stats_paris_s1.sets_contre == 1

    standings = repo.get_standings(saison_id=data["saison_1"].id, competition_id=data["comp_1"].id)
    assert len(standings) == 2
    assert standings[0].equipe_id == data["eq_a_s1"].id  # Paris first (1 win vs 0 win)


def test_compute_player_career_stats(db_session):
    data = _populate_test_data(db_session)
    service = RollupStatsService(db_session)

    service.compute_player_season_stats()
    service.compute_player_career_stats()

    repo = JoueurCarriereStatsRepository(db_session)
    career_j1 = repo.get_for_joueur(data["j1"].id)
    assert career_j1 is not None
    assert career_j1.total_matchs == 2
    assert career_j1.total_points_gagnes == 36  # 22 + 14
    assert career_j1.total_services == 28       # 18 + 10
    assert career_j1.max_points_match == 22
    assert career_j1.saisons_count == 2
    assert career_j1.premier_match_date == date(2024, 10, 12)
    assert career_j1.dernier_match_date == date(2025, 11, 15)


def test_apply_match_delta(db_session):
    data = _populate_test_data(db_session)
    service = RollupStatsService(db_session)

    # Initial compute for match 1 only via delta
    res = service.apply_match_delta(data["m1"].id)
    assert res["status"] == "updated"
    assert res["player_seasons_updated"] >= 2
    assert res["teams_updated"] == 2

    repo_s = JoueurSaisonStatsRepository(db_session)
    stats_j1 = repo_s.get_by_key(
        joueur_id=data["j1"].id,
        saison_id=data["saison_1"].id,
        competition_id=data["comp_1"].id,
        equipe_id=data["eq_a_s1"].id,
    )
    assert stats_j1 is not None
    assert stats_j1.points_gagnes == 22
