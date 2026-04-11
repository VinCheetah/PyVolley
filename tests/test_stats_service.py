"""Tests de robustesse pour le service de statistiques amusantes."""

from pyvolley.database.models import (
    ArbitreDB,
    ArbitreMatchDB,
    EquipeDB,
    JoueurDB,
    MatchDB,
    ParticipationMatchDB,
)
from pyvolley.database.stats_service import StatsAmusantesService, StatsFilters


def test_top_capitaine_libero_arbitres_only_counts_played_matches(test_session):
    equipe_a = EquipeDB(nom="Equipe A")
    equipe_b = EquipeDB(nom="Equipe B")
    joueur = JoueurDB(licence="LIC-STATS-001", nom="DUPONT", prenom="JEAN")
    arbitre = ArbitreDB(licence="ARB-STATS-001", nom="MARTIN", prenom="PAUL")
    test_session.add_all([equipe_a, equipe_b, joueur, arbitre])
    test_session.flush()

    played = MatchDB(
        code_match="PLAYED-001",
        match_joue=True,
        sets_equipe_a=3,
        sets_equipe_b=1,
        score_sets="3/1",
        equipe_a_id=equipe_a.id,
        equipe_b_id=equipe_b.id,
    )
    unplayed = MatchDB(
        code_match="UNPLAYED-001",
        match_joue=False,
        sets_equipe_a=0,
        sets_equipe_b=0,
        equipe_a_id=equipe_a.id,
        equipe_b_id=equipe_b.id,
    )
    test_session.add_all([played, unplayed])
    test_session.flush()

    test_session.add_all(
        [
            ParticipationMatchDB(
                match_id=played.id,
                joueur_id=joueur.id,
                equipe_id=equipe_a.id,
                est_capitaine=True,
                est_libero=True,
            ),
            ParticipationMatchDB(
                match_id=unplayed.id,
                joueur_id=joueur.id,
                equipe_id=equipe_a.id,
                est_capitaine=True,
                est_libero=True,
            ),
            ArbitreMatchDB(arbitre_id=arbitre.id, match_id=played.id, role="P"),
            ArbitreMatchDB(arbitre_id=arbitre.id, match_id=unplayed.id, role="S"),
        ]
    )
    test_session.commit()

    service = StatsAmusantesService(test_session)
    filters = StatsFilters()

    top_capitaines = service.top_joueurs_capitaine(filters, limit=10)
    top_liberos = service.top_joueurs_libero(filters, limit=10)
    top_arbitres = service.top_arbitres(filters, limit=10)

    assert len(top_capitaines) == 1
    assert top_capitaines[0]["valeur"] == 1

    assert len(top_liberos) == 1
    assert top_liberos[0]["valeur"] == 1

    assert len(top_arbitres) == 1
    assert top_arbitres[0]["valeur"] == 1


def test_top_equipes_victoires_requires_five_matches(test_session):
    equipe_a = EquipeDB(nom="Equipe A")
    equipe_b = EquipeDB(nom="Equipe B")
    equipe_c = EquipeDB(nom="Equipe C")
    equipe_d = EquipeDB(nom="Equipe D")
    test_session.add_all([equipe_a, equipe_b, equipe_c, equipe_d])
    test_session.flush()

    matches = []
    for idx in range(4):
        matches.append(
            MatchDB(
                code_match=f"A-WIN-{idx}",
                match_joue=True,
                sets_equipe_a=3,
                sets_equipe_b=0,
                score_sets="3/0",
                equipe_a_id=equipe_a.id,
                equipe_b_id=equipe_b.id,
            )
        )
    for idx in range(5):
        matches.append(
            MatchDB(
                code_match=f"C-WIN-{idx}",
                match_joue=True,
                sets_equipe_a=3,
                sets_equipe_b=1,
                score_sets="3/1",
                equipe_a_id=equipe_c.id,
                equipe_b_id=equipe_d.id,
            )
        )

    test_session.add_all(matches)
    test_session.commit()

    service = StatsAmusantesService(test_session)
    rows = service.top_equipes_victoires(StatsFilters(), limit=20)

    row_by_team = {row["id"]: row for row in rows}
    assert equipe_a.id not in row_by_team
    assert equipe_c.id in row_by_team
    assert row_by_team[equipe_c.id]["matchs"] == 5
