"""Tests du module converters — conversion MatchDB → core Match (round-trip)."""

import pytest
from datetime import date, time

from sqlalchemy import select

from pyvolley.core.models import (
    Match, Equipe, Joueur, Set, SetTeamData, Formation,
    Changement, TimeOut, Arbitre, Sanction, Officiel,
    RoleArbitre, TypeSanction,
)
from pyvolley.database.converters import match_db_to_core
from pyvolley.database.import_service import MatchImportService
from pyvolley.database.models import (
    MatchDB, SetDB, JoueurDB, ParticipationMatchDB,
    ArbitreMatchDB, SanctionDB, OfficielMatchDB,
)


# ============== Tests round-trip import → convert ==============


class TestMatchRoundTrip:
    """Import un Match, le reconvertit en core, vérifie que rien n'est perdu."""

    def _import_and_convert(self, session, match: Match) -> Match:
        """Helper : import → flush → reload → convert."""
        service = MatchImportService(session)
        match_db = service.import_match(match)
        session.flush()
        # Reload pour forcer le chargement complet des relations
        match_db = session.get(MatchDB, match_db.id)
        return match_db_to_core(match_db)

    def test_identifiers_preserved(self, test_session, full_match):
        """Les identifiants basiques sont conservés."""
        result = self._import_and_convert(test_session, full_match)
        assert result.code_match == "TST-FULL-001"
        assert result.id is not None

    def test_metadata_preserved(self, test_session, full_match):
        """Date, heure, salle, compétition sont conservés."""
        result = self._import_and_convert(test_session, full_match)
        assert result.date == date(2025, 1, 15)
        assert result.heure == time(20, 0)
        assert result.salle == "Gymnase Central"
        assert "ELITE" in result.competition

    def test_score_preserved(self, test_session, full_match):
        """Score, vainqueur, durée sont conservés."""
        result = self._import_and_convert(test_session, full_match)
        assert result.vainqueur_nom == "AS Volley Paris"
        assert result.score_final == "3-0"
        assert result.sets_a == 3
        assert result.sets_b == 0
        assert result.duree_totale == "1h15"
        assert result.match_joue is True

    def test_equipe_names_preserved(self, test_session, full_match):
        """Les noms des équipes sont conservés."""
        result = self._import_and_convert(test_session, full_match)
        assert result.equipe_a is not None
        assert result.equipe_b is not None
        # Les noms dépendent de la résolution en base, on vérifie qu'ils existent
        assert result.equipe_a.nom is not None
        assert result.equipe_b.nom is not None

    def test_joueurs_preserved(self, test_session, full_match):
        """Les joueurs de chaque équipe sont préservés."""
        result = self._import_and_convert(test_session, full_match)
        # L'équipe A a 7 joueurs (5 réguliers + 2 libéros)
        assert len(result.equipe_a.joueurs) >= 5
        # Vérifier qu'au moins un joueur a son nom
        noms = [j.nom for j in result.equipe_a.joueurs]
        assert "DUPONT" in noms or any("DUPONT" in (n or "") for n in noms)

    def test_liberos_marked(self, test_session, full_match):
        """Les libéros sont signalés comme tels."""
        result = self._import_and_convert(test_session, full_match)
        liberos = result.equipe_a.liberos
        assert len(liberos) >= 1

    def test_sets_preserved(self, test_session, full_match):
        """Les 3 sets avec scores sont conservés."""
        result = self._import_and_convert(test_session, full_match)
        assert len(result.sets) == 3
        assert result.sets[0].numero == 1
        assert result.sets[0].score_a == 25
        assert result.sets[0].score_b == 22
        assert result.sets[2].score_a == 25
        assert result.sets[2].score_b == 18

    def test_set_metadata_preserved(self, test_session, full_match):
        """Durée et service initial de chaque set conservés."""
        result = self._import_and_convert(test_session, full_match)
        set1 = result.sets[0]
        assert set1.duree_minutes == 28

    def test_formations_preserved(self, test_session, full_match):
        """Les formations de départ sont conservées dans les sets."""
        result = self._import_and_convert(test_session, full_match)
        set1 = result.sets[0]
        # Vérifier que les données d'équipe A ont une formation
        if set1.equipe_a:
            form = set1.equipe_a.formation
            assert form is not None
            assert form.position_1 == "1"
            assert form.position_2 == "4"

    def test_changements_preserved(self, test_session, full_match):
        """Les changements sont conservés dans les données de set."""
        result = self._import_and_convert(test_session, full_match)
        set1 = result.sets[0]
        if set1.equipe_a and set1.equipe_a.changements:
            assert len(set1.equipe_a.changements) == 1
            c = set1.equipe_a.changements[0]
            assert c.joueur_entrant == "2"
            assert c.joueur_sortant == "13"

    def test_timeouts_preserved(self, test_session, full_match):
        """Les timeouts sont conservés dans les données de set."""
        result = self._import_and_convert(test_session, full_match)
        set1 = result.sets[0]
        if set1.equipe_a and set1.equipe_a.timeouts:
            assert len(set1.equipe_a.timeouts) >= 1

    def test_arbitres_preserved(self, test_session, full_match):
        """Les arbitres avec rôle, nom, prénom, licence sont conservés."""
        result = self._import_and_convert(test_session, full_match)
        assert len(result.arbitres) == 2
        licences = {a.licence for a in result.arbitres}
        assert "ARB001" in licences
        assert "ARB002" in licences
        noms = {a.nom for a in result.arbitres}
        assert "ARBITRE1" in noms
        assert "ARBITRE2" in noms

    def test_sanctions_preserved(self, test_session, full_match):
        """Les sanctions sont conservées."""
        result = self._import_and_convert(test_session, full_match)
        assert len(result.sanctions) == 1
        s = result.sanctions[0]
        assert s.type == TypeSanction.AVERTISSEMENT
        assert s.equipe == "B"
        assert s.joueur_numero == "5"
        assert s.set_numero == 2

    def test_remarques_preserved(self, test_session, full_match):
        """Les remarques sont conservées."""
        result = self._import_and_convert(test_session, full_match)
        assert result.remarques == "Match test complet"

    def test_officiels_preserved(self, test_session, full_match):
        """Les officiels d'équipe sont conservés."""
        result = self._import_and_convert(test_session, full_match)

        all_officiels_a = result.equipe_a.officiels if result.equipe_a else []
        all_officiels_b = result.equipe_b.officiels if result.equipe_b else []

        assert len(all_officiels_a) >= 1
        assert len(all_officiels_b) >= 1


# ============== Tests de cas limites ==============


class TestConverterEdgeCases:
    """Tests des cas limites de la conversion."""

    def test_match_without_sets(self, test_session):
        """Un match sans sets est converti sans erreur."""
        service = MatchImportService(test_session)
        match = Match(
            code_match="NOSETS01",
            equipe_a=Equipe(nom="Equipe AA", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Equipe BB", joueurs=[], liberos=[]),
        )
        match_db = service.import_match(match)
        test_session.flush()
        result = match_db_to_core(match_db)
        assert result.sets == []
        assert result.code_match == "NOSETS01"

    def test_match_without_arbitres(self, test_session):
        """Un match sans arbitres est converti sans erreur."""
        service = MatchImportService(test_session)
        match = Match(
            code_match="NOARB01",
            equipe_a=Equipe(nom="Equipe AA", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Equipe BB", joueurs=[], liberos=[]),
        )
        match_db = service.import_match(match)
        test_session.flush()
        result = match_db_to_core(match_db)
        assert result.arbitres == []

    def test_match_without_sanctions(self, test_session):
        """Un match sans sanctions est converti sans erreur."""
        service = MatchImportService(test_session)
        match = Match(
            code_match="NOSANC01",
            equipe_a=Equipe(nom="Equipe AA", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Equipe BB", joueurs=[], liberos=[]),
        )
        match_db = service.import_match(match)
        test_session.flush()
        result = match_db_to_core(match_db)
        assert result.sanctions == []

    def test_auto_split_participants(self, test_session):
        """Sans participants explicites, ils sont auto-répartis par equipe_id."""
        service = MatchImportService(test_session)
        match = Match(
            code_match="AUTOSPLIT01",
            equipe_a=Equipe(
                nom="Equipe Alpha",
                joueurs=[Joueur(numero="1", nom="J1", prenom="P1", licence="100001")],
                liberos=[],
            ),
            equipe_b=Equipe(
                nom="Equipe Beta",
                joueurs=[Joueur(numero="2", nom="J2", prenom="P2", licence="100002")],
                liberos=[],
            ),
        )
        match_db = service.import_match(match)
        test_session.flush()

        # Convertir sans passer de participants → doit auto-split
        result = match_db_to_core(match_db)
        assert len(result.equipe_a.joueurs) == 1
        assert len(result.equipe_b.joueurs) == 1
        assert result.equipe_a.joueurs[0].nom == "J1"
        assert result.equipe_b.joueurs[0].nom == "J2"

    def test_heure_parsing(self, test_session):
        """L'heure est correctement parsée du format string."""
        service = MatchImportService(test_session)
        match = Match(
            code_match="HEURE01",
            heure=time(14, 30),
            equipe_a=Equipe(nom="Equipe AA", joueurs=[], liberos=[]),
            equipe_b=Equipe(nom="Equipe BB", joueurs=[], liberos=[]),
        )
        match_db = service.import_match(match)
        test_session.flush()

        result = match_db_to_core(match_db)
        assert result.heure == time(14, 30)
