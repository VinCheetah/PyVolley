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


def test_clean_sheets_and_tie_breaks(test_session):
    equipe_a = EquipeDB(nom="Equipe Dominante")
    equipe_b = EquipeDB(nom="Equipe Resiliente")
    test_session.add_all([equipe_a, equipe_b])
    test_session.flush()

    # 2 clean sheets (3-0) for equipe_a
    # 1 tie-break (3-2) for equipe_b against equipe_a
    matches = [
        MatchDB(
            code_match="CS-1",
            match_joue=True,
            sets_equipe_a=3,
            sets_equipe_b=0,
            score_sets="3/0",
            equipe_a_id=equipe_a.id,
            equipe_b_id=equipe_b.id,
        ),
        MatchDB(
            code_match="CS-2",
            match_joue=True,
            sets_equipe_a=3,
            sets_equipe_b=0,
            score_sets="3/0",
            equipe_a_id=equipe_a.id,
            equipe_b_id=equipe_b.id,
        ),
        MatchDB(
            code_match="TB-1",
            match_joue=True,
            sets_equipe_a=2,
            sets_equipe_b=3,
            score_sets="2/3",
            equipe_a_id=equipe_a.id,
            equipe_b_id=equipe_b.id,
        ),
    ]
    test_session.add_all(matches)
    test_session.commit()

    service = StatsAmusantesService(test_session)
    clean_sheets = service.top_equipes_clean_sheets(StatsFilters())
    tie_breaks = service.top_equipes_tie_breaks(StatsFilters())

    assert len(clean_sheets) >= 1
    assert clean_sheets[0]["id"] == equipe_a.id
    assert clean_sheets[0]["valeur"] == 2

    assert len(tie_breaks) >= 1
    assert tie_breaks[0]["id"] == equipe_b.id
    assert tie_breaks[0]["valeur"] == 1


def test_top_clubs_victoires(test_session):
    from pyvolley.database.models import ClubDB

    club = ClubDB(nom="Volley Club Test", code_ffvb="0999999", ville="Paris", departement="75")
    test_session.add(club)
    test_session.flush()

    equipe1 = EquipeDB(nom="VC Test 1", club_id=club.id)
    equipe2 = EquipeDB(nom="VC Test 2", club_id=club.id)
    equipe_adv = EquipeDB(nom="Adversaire")
    test_session.add_all([equipe1, equipe2, equipe_adv])
    test_session.flush()

    matches = [
        MatchDB(
            code_match="CLUB-W-1",
            match_joue=True,
            sets_equipe_a=3,
            sets_equipe_b=1,
            score_sets="3/1",
            equipe_a_id=equipe1.id,
            equipe_b_id=equipe_adv.id,
        ),
        MatchDB(
            code_match="CLUB-W-2",
            match_joue=True,
            sets_equipe_a=0,
            sets_equipe_b=3,
            score_sets="0/3",
            equipe_a_id=equipe_adv.id,
            equipe_b_id=equipe2.id,
        ),
    ]
    test_session.add_all(matches)
    test_session.commit()

    service = StatsAmusantesService(test_session)
    top_clubs = service.top_clubs_victoires(StatsFilters())

    assert len(top_clubs) >= 1
    assert top_clubs[0]["id"] == club.id
    assert top_clubs[0]["valeur"] == 2


def test_record_points_match(test_session):
    from pyvolley.database.models import JoueurMatchStatsDB

    joueur = JoueurDB(licence="LIC-SCORER-01", nom="NGAPETH", prenom="EARVIN")
    equipe = EquipeDB(nom="Equipe Star")
    equipe_opp = EquipeDB(nom="Equipe Opp")
    test_session.add_all([joueur, equipe, equipe_opp])
    test_session.flush()

    match = MatchDB(
        code_match="MATCH-REC-01",
        match_joue=True,
        sets_equipe_a=3,
        sets_equipe_b=2,
        score_sets="3/2",
        equipe_a_id=equipe.id,
        equipe_b_id=equipe_opp.id,
    )
    test_session.add(match)
    test_session.flush()

    stat = JoueurMatchStatsDB(
        joueur_id=joueur.id,
        match_id=match.id,
        equipe_id=equipe.id,
        points_gagnes=38,
        points_gagnes_service=5,
    )
    test_session.add(stat)
    test_session.commit()

    service = StatsAmusantesService(test_session)
    records = service.record_points_match(StatsFilters())

    assert len(records) >= 1
    assert records[0]["id"] == joueur.id
    assert records[0]["valeur"] == 38
    assert records[0]["match_id"] == match.id


def test_top_joueurs_ratio_victoires(test_session):
    joueur_invincible = JoueurDB(licence="LIC-INVINCIBLE", nom="LE GOFF", prenom="NICOLAS")
    equipe = EquipeDB(nom="Equipe Gagnante")
    equipe_opp = EquipeDB(nom="Equipe Perdante")
    test_session.add_all([joueur_invincible, equipe, equipe_opp])
    test_session.flush()

    for idx in range(6):
        m = MatchDB(
            code_match=f"INV-{idx}",
            match_joue=True,
            sets_equipe_a=3,
            sets_equipe_b=1 if idx > 0 else 0,
            score_sets="3/1",
            equipe_a_id=equipe.id,
            equipe_b_id=equipe_opp.id,
        )
        test_session.add(m)
        test_session.flush()

        test_session.add(
            ParticipationMatchDB(
                match_id=m.id,
                joueur_id=joueur_invincible.id,
                equipe_id=equipe.id,
            )
        )
    test_session.commit()

    service = StatsAmusantesService(test_session)
    top_ratios = service.top_joueurs_ratio_victoires(StatsFilters(), limit=10, min_matchs=5)

    assert len(top_ratios) >= 1
    assert top_ratios[0]["id"] == joueur_invincible.id
    assert top_ratios[0]["matchs"] == 6
    assert top_ratios[0]["valeur"] == 100.0  # 100% victoires
