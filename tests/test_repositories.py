"""Tests pour les repositories — CRUD et méthodes spécialisées."""

import pytest
from sqlalchemy.orm import Session

from pyvolley.database.models import JoueurDB, ClubDB, EquipeDB, MatchDB
from pyvolley.database.repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    MatchRepository,
)


# ============== JoueurRepository ==============


class TestJoueurRepository:
    """Tests pour le repository des joueurs."""

    def test_add_joueur(self, test_session: Session):
        repo = JoueurRepository(test_session)
        joueur = JoueurDB(licence="123456789", nom="DUPONT", prenom="Jean")
        result = repo.add(joueur)
        test_session.commit()
        assert result.id is not None
        assert result.nom == "DUPONT"

    def test_get_by_licence(self, test_session: Session):
        repo = JoueurRepository(test_session)
        repo.add(JoueurDB(licence="987654321", nom="MARTIN", prenom="Pierre"))
        test_session.commit()
        result = repo.get_by_licence("987654321")
        assert result is not None
        assert result.nom == "MARTIN"

    def test_get_by_licence_inexistante(self, test_session: Session):
        repo = JoueurRepository(test_session)
        assert repo.get_by_licence("NOPE") is None

    def test_search_by_name(self, test_session: Session):
        repo = JoueurRepository(test_session)
        repo.add(JoueurDB(licence="001", nom="DUBOIS", prenom="Alice"))
        repo.add(JoueurDB(licence="002", nom="DURAND", prenom="Bob"))
        repo.add(JoueurDB(licence="003", nom="PETIT", prenom="Charles"))
        test_session.commit()
        results = repo.search_by_name("DU")
        assert len(results) == 2
        noms = {j.nom for j in results}
        assert noms == {"DUBOIS", "DURAND"}

    def test_search_by_name_sans_resultat(self, test_session: Session):
        repo = JoueurRepository(test_session)
        repo.add(JoueurDB(licence="001", nom="DUPONT", prenom="X"))
        test_session.commit()
        assert repo.search_by_name("ZZZZZ") == []

    def test_get_or_create_existing(self, test_session: Session):
        repo = JoueurRepository(test_session)
        repo.add(JoueurDB(licence="111", nom="EXISTANT", prenom="Test"))
        test_session.commit()
        result, created = repo.get_or_create("111", "AUTRE", "Nom")
        assert created is False
        assert result.nom == "EXISTANT"

    def test_get_or_create_new(self, test_session: Session):
        repo = JoueurRepository(test_session)
        result, created = repo.get_or_create("999", "NOUVEAU", "Joueur")
        test_session.commit()
        assert created is True
        assert result.nom == "NOUVEAU"
        assert result.licence == "999"

    def test_count(self, test_session: Session):
        repo = JoueurRepository(test_session)
        assert repo.count() == 0
        repo.add(JoueurDB(licence="A01", nom="A", prenom="X"))
        repo.add(JoueurDB(licence="A02", nom="B", prenom="Y"))
        test_session.commit()
        assert repo.count() == 2

    def test_delete(self, test_session: Session):
        repo = JoueurRepository(test_session)
        joueur = repo.add(JoueurDB(licence="DEL01", nom="TODELETE", prenom="X"))
        test_session.commit()
        repo.delete(joueur)
        test_session.commit()
        assert repo.get_by_licence("DEL01") is None


# ============== ClubRepository ==============


class TestClubRepository:
    """Tests pour le repository des clubs."""

    def test_add_club(self, test_session: Session):
        repo = ClubRepository(test_session)
        club = ClubDB(nom="AS Volley Paris", ville="Paris")
        result = repo.add(club)
        test_session.commit()
        assert result.id is not None
        assert result.nom == "AS Volley Paris"

    def test_search_by_name(self, test_session: Session):
        repo = ClubRepository(test_session)
        repo.add(ClubDB(nom="Paris Volley"))
        repo.add(ClubDB(nom="Lyon Volley"))
        repo.add(ClubDB(nom="Marseille OM"))
        test_session.commit()
        results = repo.search_by_name("Volley")
        assert len(results) == 2

    def test_search_by_name_sans_resultat(self, test_session: Session):
        repo = ClubRepository(test_session)
        repo.add(ClubDB(nom="Paris Volley"))
        test_session.commit()
        assert repo.search_by_name("Basketball") == []

    def test_get_or_create_club(self, test_session: Session):
        repo = ClubRepository(test_session)
        club1, created1 = repo.get_or_create("Nouveau Club")
        test_session.commit()
        club2, created2 = repo.get_or_create("Nouveau Club")
        assert created1 is True
        assert created2 is False
        assert club1.id == club2.id

    def test_count(self, test_session: Session):
        repo = ClubRepository(test_session)
        assert repo.count() == 0
        repo.add(ClubDB(nom="Club A"))
        repo.add(ClubDB(nom="Club B"))
        test_session.commit()
        assert repo.count() == 2


# ============== EquipeRepository ==============


class TestEquipeRepository:
    """Tests pour le repository des équipes."""

    def test_add_equipe(self, test_session: Session):
        repo = EquipeRepository(test_session)
        equipe = EquipeDB(nom="Équipe A Senior Masculin")
        result = repo.add(equipe)
        test_session.commit()
        assert result.id is not None

    def test_get_or_create(self, test_session: Session):
        repo = EquipeRepository(test_session)
        equipe1, created1 = repo.get_or_create("Nouvelle Équipe")
        test_session.commit()
        equipe2, created2 = repo.get_or_create("Nouvelle Équipe")
        assert created1 is True
        assert created2 is False
        assert equipe1.id == equipe2.id

    def test_get_by_club(self, test_session: Session):
        """Les équipes peuvent être filtrées par club."""
        club_repo = ClubRepository(test_session)
        club, _ = club_repo.get_or_create("Test Club")
        test_session.commit()

        equipe_repo = EquipeRepository(test_session)
        equipe = EquipeDB(nom="Equipe Test", club_id=club.id)
        equipe_repo.add(equipe)
        test_session.commit()

        results = equipe_repo.get_by_club(club.id)
        assert len(results) == 1
        assert results[0].nom == "Equipe Test"


# ============== MatchRepository ==============


class TestMatchRepository:
    """Tests pour le repository des matchs."""

    def _create_match(self, session, code="2024-001"):
        """Helper pour créer un match avec équipes."""
        equipe_repo = EquipeRepository(session)
        equipe_a, _ = equipe_repo.get_or_create(f"Équipe A {code}")
        equipe_b, _ = equipe_repo.get_or_create(f"Équipe B {code}")
        session.flush()

        match_repo = MatchRepository(session)
        match = MatchDB(
            code_match=code,
            equipe_a_id=equipe_a.id,
            equipe_b_id=equipe_b.id,
        )
        return match_repo.add(match), match_repo

    def test_add_match(self, test_session: Session):
        match, _ = self._create_match(test_session)
        test_session.commit()
        assert match.id is not None
        assert match.code_match == "2024-001"

    def test_get_by_code(self, test_session: Session):
        self._create_match(test_session, "TEST-001")
        test_session.commit()
        repo = MatchRepository(test_session)
        result = repo.get_by_code("TEST-001")
        assert result is not None
        assert result.code_match == "TEST-001"

    def test_get_by_code_inexistant(self, test_session: Session):
        repo = MatchRepository(test_session)
        assert repo.get_by_code("NOPE-999") is None

    def test_exists(self, test_session: Session):
        self._create_match(test_session, "EXISTS-001")
        test_session.commit()
        repo = MatchRepository(test_session)
        assert repo.exists("EXISTS-001") is True
        assert repo.exists("UNKNOWN-999") is False

    def test_count(self, test_session: Session):
        repo = MatchRepository(test_session)
        assert repo.count() == 0
        self._create_match(test_session, "CNT-001")
        self._create_match(test_session, "CNT-002")
        test_session.commit()
        assert repo.count() == 2

    def test_get_all(self, test_session: Session):
        self._create_match(test_session, "ALL-001")
        self._create_match(test_session, "ALL-002")
        self._create_match(test_session, "ALL-003")
        test_session.commit()
        repo = MatchRepository(test_session)
        results = repo.get_all(limit=2)
        assert len(results) == 2
