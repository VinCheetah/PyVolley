"""
Tests pour les repositories de base de données.
"""

import pytest
from sqlalchemy.orm import Session

from pyvolley.database.models import JoueurDB, ClubDB, EquipeDB, MatchDB
from pyvolley.database.repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    MatchRepository,
)


class TestJoueurRepository:
    """Tests pour le repository des joueurs."""
    
    def test_add_joueur(self, test_session: Session):
        """Test ajout d'un joueur."""
        repo = JoueurRepository(test_session)
        
        joueur = JoueurDB(
            licence="123456789",
            nom="DUPONT",
            prenom="Jean",
        )
        
        result = repo.add(joueur)
        test_session.commit()
        
        assert result.id is not None
        assert result.nom == "DUPONT"
    
    def test_get_by_licence(self, test_session: Session):
        """Test recherche par licence."""
        repo = JoueurRepository(test_session)
        
        joueur = JoueurDB(
            licence="987654321",
            nom="MARTIN",
            prenom="Pierre",
        )
        repo.add(joueur)
        test_session.commit()
        
        result = repo.get_by_licence("987654321")
        
        assert result is not None
        assert result.nom == "MARTIN"
    
    def test_search_by_name(self, test_session: Session):
        """Test recherche par nom."""
        repo = JoueurRepository(test_session)
        
        # Ajouter plusieurs joueurs
        repo.add(JoueurDB(licence="001", nom="DUBOIS", prenom="Alice"))
        repo.add(JoueurDB(licence="002", nom="DURAND", prenom="Bob"))
        repo.add(JoueurDB(licence="003", nom="PETIT", prenom="Charles"))
        test_session.commit()
        
        # Rechercher
        results = repo.search_by_name("DU")
        
        assert len(results) == 2
        noms = [j.nom for j in results]
        assert "DUBOIS" in noms
        assert "DURAND" in noms
    
    def test_get_or_create_existing(self, test_session: Session):
        """Test get_or_create avec joueur existant."""
        repo = JoueurRepository(test_session)
        
        joueur = JoueurDB(licence="111", nom="EXISTANT", prenom="Test")
        repo.add(joueur)
        test_session.commit()
        
        result, created = repo.get_or_create("111", "AUTRE", "Nom")
        
        assert created is False
        assert result.nom == "EXISTANT"
    
    def test_get_or_create_new(self, test_session: Session):
        """Test get_or_create avec nouveau joueur."""
        repo = JoueurRepository(test_session)
        
        result, created = repo.get_or_create("999", "NOUVEAU", "Joueur")
        test_session.commit()
        
        assert created is True
        assert result.nom == "NOUVEAU"


class TestClubRepository:
    """Tests pour le repository des clubs."""
    
    def test_add_club(self, test_session: Session):
        """Test ajout d'un club."""
        repo = ClubRepository(test_session)
        
        club = ClubDB(nom="AS Volley Paris", ville="Paris")
        result = repo.add(club)
        test_session.commit()
        
        assert result.id is not None
        assert result.nom == "AS Volley Paris"
    
    def test_search_by_name(self, test_session: Session):
        """Test recherche par nom."""
        repo = ClubRepository(test_session)
        
        repo.add(ClubDB(nom="Paris Volley"))
        repo.add(ClubDB(nom="Lyon Volley"))
        repo.add(ClubDB(nom="Marseille OM"))
        test_session.commit()
        
        results = repo.search_by_name("Volley")
        
        assert len(results) == 2
    
    def test_search_by_name_club(self, test_session: Session):
        """Test recherche par nom de club."""
        repo = ClubRepository(test_session)
        
        repo.add(ClubDB(nom="Club Volley A", departement="75"))
        repo.add(ClubDB(nom="Club Volley B", departement="75"))
        repo.add(ClubDB(nom="Club Basket C", departement="69"))
        test_session.commit()
        
        results = repo.search_by_name("Volley")
        
        assert len(results) == 2


class TestEquipeRepository:
    """Tests pour le repository des équipes."""
    
    def test_add_equipe(self, test_session: Session):
        """Test ajout d'une équipe."""
        repo = EquipeRepository(test_session)
        
        equipe = EquipeDB(nom="Équipe A Senior Masculin")
        result = repo.add(equipe)
        test_session.commit()
        
        assert result.id is not None
    
    def test_get_or_create(self, test_session: Session):
        """Test get_or_create pour équipe."""
        repo = EquipeRepository(test_session)
        
        # Premier appel - création
        equipe1, created1 = repo.get_or_create("Nouvelle Équipe")
        test_session.commit()
        
        # Deuxième appel - récupération
        equipe2, created2 = repo.get_or_create("Nouvelle Équipe")
        
        assert created1 is True
        assert created2 is False
        assert equipe1.id == equipe2.id


class TestMatchRepository:
    """Tests pour le repository des matchs."""
    
    def test_add_match(self, test_session: Session):
        """Test ajout d'un match."""
        # Créer les équipes d'abord
        equipe_repo = EquipeRepository(test_session)
        equipe_a, _ = equipe_repo.get_or_create("Équipe A")
        equipe_b, _ = equipe_repo.get_or_create("Équipe B")
        test_session.commit()
        
        match_repo = MatchRepository(test_session)
        
        match = MatchDB(
            code_match="2024-001",
            equipe_a_id=equipe_a.id,
            equipe_b_id=equipe_b.id,
            score_sets="3/1",
            vainqueur="Équipe A",
        )
        result = match_repo.add(match)
        test_session.commit()
        
        assert result.id is not None
        assert result.code_match == "2024-001"
    
    def test_get_by_code(self, test_session: Session):
        """Test recherche par code match."""
        equipe_repo = EquipeRepository(test_session)
        equipe_a, _ = equipe_repo.get_or_create("Équipe A")
        equipe_b, _ = equipe_repo.get_or_create("Équipe B")
        test_session.commit()
        
        match_repo = MatchRepository(test_session)
        
        match = MatchDB(
            code_match="TEST-001",
            equipe_a_id=equipe_a.id,
            equipe_b_id=equipe_b.id,
        )
        match_repo.add(match)
        test_session.commit()
        
        result = match_repo.get_by_code("TEST-001")
        
        assert result is not None
        assert result.code_match == "TEST-001"
    
    def test_exists(self, test_session: Session):
        """Test vérification d'existence."""
        equipe_repo = EquipeRepository(test_session)
        equipe_a, _ = equipe_repo.get_or_create("Équipe A")
        equipe_b, _ = equipe_repo.get_or_create("Équipe B")
        test_session.commit()
        
        match_repo = MatchRepository(test_session)
        
        match = MatchDB(
            code_match="EXISTS-001",
            equipe_a_id=equipe_a.id,
            equipe_b_id=equipe_b.id,
        )
        match_repo.add(match)
        test_session.commit()
        
        assert match_repo.exists("EXISTS-001") is True
        assert match_repo.exists("UNKNOWN-999") is False
