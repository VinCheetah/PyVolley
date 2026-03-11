"""Tests ciblés du MatchImportService."""

from sqlalchemy import select

from pyvolley.core.models import Match, Equipe, Joueur, Officiel
from pyvolley.database.import_service import MatchImportService
from pyvolley.database.models import JoueurDB, OfficielMatchDB, PersonneDB


def test_missing_or_zero_licence_does_not_merge_all_players(test_session):
    service = MatchImportService(test_session)

    match = Match(
        code_match="TST001",
        equipe_a=Equipe(
            nom="Equipe A",
            joueurs=[
                Joueur(numero="1", nom="DUPONT", prenom="Jean", licence="0"),
                Joueur(numero="2", nom="MARTIN", prenom="Paul", licence="0"),
            ],
            liberos=[],
        ),
        equipe_b=Equipe(
            nom="Equipe B",
            joueurs=[],
            liberos=[],
        ),
    )

    imported = service.import_match(match)
    assert imported is not None
    test_session.flush()

    joueurs = test_session.execute(select(JoueurDB).order_by(JoueurDB.id)).scalars().all()
    assert len(joueurs) == 2
    assert joueurs[0].licence.startswith("NL-")
    assert joueurs[1].licence.startswith("NL-")
    assert joueurs[0].licence != joueurs[1].licence


def test_officiels_are_linked_to_personnes(test_session):
    service = MatchImportService(test_session)

    match = Match(
        code_match="TST002",
        equipe_a=Equipe(
            nom="Equipe A",
            joueurs=[],
            liberos=[],
            officiels=[Officiel(role="EA", nom="COACH", prenom="Alice", licence="998877")],
        ),
        equipe_b=Equipe(
            nom="Equipe B",
            joueurs=[],
            liberos=[],
            officiels=[Officiel(role="EB", nom="MANAGER", prenom="Bob", licence=None)],
        ),
    )

    imported = service.import_match(match)
    assert imported is not None
    test_session.flush()

    officiels = test_session.execute(select(OfficielMatchDB).order_by(OfficielMatchDB.id)).scalars().all()
    assert len(officiels) == 2
    assert officiels[0].personne_id is not None
    assert officiels[1].personne_id is not None

    personnes = test_session.execute(select(PersonneDB).order_by(PersonneDB.id)).scalars().all()
    assert len(personnes) >= 2
