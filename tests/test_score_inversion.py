"""Tests de détection et de réalignement de l'inversion d'équipes (PDF A/B vs DB A/B)."""

import pytest
from datetime import date, time
from sqlalchemy import select

from pyvolley.core.models import (
    Match,
    Equipe,
    Joueur,
    Set,
    SetTeamData,
    Formation,
    TimeOut,
    Changement,
    Sanction,
    Officiel,
    invert_match_sides,
)
from pyvolley.core.constants import TypeSanction
from pyvolley.database.club_matching import detect_team_inversion
from pyvolley.database.models import (
    MatchDB,
    EquipeDB,
    ClubDB,
    SaisonDB,
    CompetitionDB,
    SetDB,
    ParticipationMatchDB,
)
from pyvolley.database.import_service import MatchImportService


def test_invert_match_sides():
    """Vérifie l'inversion complète et fidèle d'un objet Match."""
    joueur_a = Joueur(licence="1111111", nom="DUPONT", prenom="Jean", numero="1")
    joueur_b = Joueur(licence="2222222", nom="MARTIN", prenom="Paul", numero="2")

    set1 = Set(
        numero=1,
        score_a=18,
        score_b=25,
        service_initial="A",
        equipe_a=SetTeamData(
            formation=Formation(position_1="1", position_2="3"),
            timeouts=[TimeOut(score_a=10, score_b=15)],
            changements=[Changement(joueur_entrant="5", joueur_sortant="1", score_a=12, score_b=18)],
            services={1: [1, 2], 2: [3]},
        ),
        equipe_b=SetTeamData(
            formation=Formation(position_1="2", position_2="4"),
            timeouts=[TimeOut(score_a=12, score_b=20)],
            changements=[],
            services={1: [5, 6]},
        ),
    )

    sanction = Sanction(
        type=TypeSanction.AVERTISSEMENT,
        set_numero=1,
        equipe="A",
        score_a=5,
        score_b=10,
    )

    m = Match(
        code_match="TEST001",
        equipe_a=Equipe(nom="EQUIPE ALPHA", joueurs=[joueur_a]),
        equipe_b=Equipe(nom="EQUIPE BETA", joueurs=[joueur_b]),
        equipe_a_id=10,
        equipe_b_id=20,
        sets_a=1,
        sets_b=3,
        score_final="1/3",
        score_pdf="1/3",
        score_export="3/1",
        vainqueur_nom="EQUIPE BETA",
        vainqueur_id=20,
        sets=[set1],
        sanctions=[sanction],
    )

    inv = invert_match_sides(m)

    assert inv.equipe_a.nom == "EQUIPE BETA"
    assert inv.equipe_b.nom == "EQUIPE ALPHA"
    assert inv.equipe_a_id == 20
    assert inv.equipe_b_id == 10
    assert inv.sets_a == 3
    assert inv.sets_b == 1
    assert inv.score_final == "3/1"
    assert inv.score_pdf == "3/1"
    assert inv.score_export == "1/3"
    assert inv.vainqueur_id == 10  # Ancien equipe_b_id -> devient equipe_a_id

    # Sets
    assert len(inv.sets) == 1
    s_inv = inv.sets[0]
    assert s_inv.score_a == 25
    assert s_inv.score_b == 18
    assert s_inv.service_initial == "B"

    # Formation et timeouts A proviennent de B
    assert s_inv.equipe_a.formation.position_1 == "2"
    assert len(s_inv.equipe_a.timeouts) == 1
    assert s_inv.equipe_a.timeouts[0].score_a == 20
    assert s_inv.equipe_a.timeouts[0].score_b == 12

    # Formation et timeouts B proviennent de A
    assert s_inv.equipe_b.formation.position_1 == "1"
    assert len(s_inv.equipe_b.timeouts) == 1
    assert s_inv.equipe_b.timeouts[0].score_a == 15
    assert s_inv.equipe_b.timeouts[0].score_b == 10
    assert len(s_inv.equipe_b.changements) == 1
    assert s_inv.equipe_b.changements[0].score_a == 18
    assert s_inv.equipe_b.changements[0].score_b == 12

    # Sanctions
    assert len(inv.sanctions) == 1
    sanc_inv = inv.sanctions[0]
    assert sanc_inv.equipe == "B"
    assert sanc_inv.score_a == 10
    assert sanc_inv.score_b == 5


def test_detect_team_inversion_rules():
    """Vérifie les différentes règles de détection d'inversion."""
    # 1. Cas direct simple
    assert not detect_team_inversion(
        "VB VILLEFRANCHE", "VC MEXIMIEUX",
        "VB VILLEFRANCHE", "VC MEXIMIEUX",
    )

    # 2. Cas inversé simple
    assert detect_team_inversion(
        "VB VILLEFRANCHE", "VC MEXIMIEUX",
        "VC MEXIMIEUX", "VB VILLEFRANCHE",
    )

    # 3. Cas avec numéros d'équipes d'un même club
    assert not detect_team_inversion(
        "RHONE 1", "RHONE 3",
        "RHONE 1", "RHONE 3",
    )
    assert detect_team_inversion(
        "RHONE 1", "RHONE 3",
        "RHONE 3", "RHONE 1",
    )

    # 4. Cas avec variantes de suffixes (VB, VOLLEY, etc.)
    assert not detect_team_inversion(
        "LYON PESD VB", "US VALLEE DE LA GRESSE",
        "LYON PESD VOLLEY", "US VALLEE DE LA GRESSE 2",
    )
    assert detect_team_inversion(
        "LYON PESD VB", "US VALLEE DE LA GRESSE",
        "US VALLEE DE LA GRESSE 2", "LYON PESD VOLLEY",
    )

    # 5. Score agreement fallback
    assert detect_team_inversion(
        "EQUIPE INCONNUE 1", "EQUIPE INCONNUE 2",
        "AUTRE NOM A", "AUTRE NOM B",
        score_export="3/0",
        parsed_sets_a=0,
        parsed_sets_b=3,
    )
    assert not detect_team_inversion(
        "EQUIPE INCONNUE 1", "EQUIPE INCONNUE 2",
        "AUTRE NOM A", "AUTRE NOM B",
        score_export="3/0",
        parsed_sets_a=3,
        parsed_sets_b=0,
    )


def test_enrich_from_pdf_inversion_integration(test_session):
    """Test d'intégration : un match inversé est correctement réaligné en base."""
    # Setup base
    saison = SaisonDB(code="2025-2026", nom="2025/2026", date_debut=date(2025, 9, 1), date_fin=date(2026, 6, 30))
    comp = CompetitionDB(code_competition="REG", nom="Régionale 1", saison=saison)
    club_a = ClubDB(nom="VB VILLEFRANCHE")
    club_b = ClubDB(nom="VC MEXIMIEUX")
    eq_a = EquipeDB(nom="VB VILLEFRANCHE", club=club_a, saison=saison, competition=comp)
    eq_b = EquipeDB(nom="VC MEXIMIEUX", club=club_b, saison=saison, competition=comp)

    match_db = MatchDB(
        code_match="BFAA001",
        saison=saison,
        competition=comp,
        equipe_a=eq_a,
        equipe_b=eq_b,
        score_export="2/0",
        score_sets="2/0",
        sets_equipe_a=2,
        sets_equipe_b=0,
        vainqueur="VB VILLEFRANCHE",
        parsing_status="downloaded",
        match_joue=True,
    )
    test_session.add_all([saison, comp, club_a, club_b, eq_a, eq_b, match_db])
    test_session.flush()

    # Match PDF où VC MEXIMIEUX est Équipe A et VB VILLEFRANCHE est Équipe B
    joueur_mex = Joueur(licence="2520295", nom="BESSON", prenom="MELINE", numero="6")
    joueur_vil = Joueur(licence="2722751", nom="ADJAOUD", prenom="MEISSANE", numero="8")

    parsed_pdf = Match(
        code_match="BFAA001",
        date=date(2025, 12, 14),
        heure=time(11, 0),
        equipe_a=Equipe(nom="VC MEXIMIEUX", joueurs=[joueur_mex]),
        equipe_b=Equipe(nom="VB VILLEFRANCHE", joueurs=[joueur_vil]),
        sets_a=0,
        sets_b=2,
        score_final="0/2",
        vainqueur_nom="VB VILLEFRANCHE",
        match_joue=True,
        sets=[
            Set(
                numero=1,
                score_a=14,
                score_b=25,
                equipe_a=SetTeamData(),
                equipe_b=SetTeamData(),
            ),
            Set(
                numero=2,
                score_a=9,
                score_b=25,
                equipe_a=SetTeamData(),
                equipe_b=SetTeamData(),
            ),
        ],
    )

    service = MatchImportService(test_session)
    updated = service.enrich_from_pdf(match_db, parsed_pdf, force=True)

    assert updated is True
    # Le score PDF doit être réaligné sur equipe_a/equipe_b de la base
    assert match_db.score_pdf == "2/0"
    assert match_db.score_sets == "2/0"
    assert match_db.sets_equipe_a == 2
    assert match_db.sets_equipe_b == 0
    assert match_db.score_conflict is False

    # Sets en base
    sets_in_db = test_session.scalars(
        select(SetDB).where(SetDB.match_id == match_db.id).order_by(SetDB.numero)
    ).all()
    assert len(sets_in_db) == 2
    assert sets_in_db[0].score_a == 25  # Villefranche
    assert sets_in_db[0].score_b == 14  # Meximieux
    assert sets_in_db[1].score_a == 25
    assert sets_in_db[1].score_b == 9

    # Participations
    parts = test_session.scalars(
        select(ParticipationMatchDB).where(ParticipationMatchDB.match_id == match_db.id)
    ).all()
    assert len(parts) == 2

    # Besson (Meximieux) doit être liée à eq_b (VC MEXIMIEUX) côté B
    part_mex = next(p for p in parts if p.joueur.nom == "BESSON")
    assert part_mex.equipe_id == eq_b.id
    assert part_mex.side == "B"

    # Adjaoud (Villefranche) doit être liée à eq_a (VB VILLEFRANCHE) côté A
    part_vil = next(p for p in parts if p.joueur.nom == "ADJAOUD")
    assert part_vil.equipe_id == eq_a.id
    assert part_vil.side == "A"
