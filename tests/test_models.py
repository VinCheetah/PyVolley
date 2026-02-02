"""
Tests pour les modèles Pydantic.
"""

import pytest
from pydantic import ValidationError

from pyvolley.core.models import Joueur, Equipe, Set, Match


class TestJoueur:
    """Tests pour le modèle Joueur."""
    
    def test_creation_valide(self):
        """Test création d'un joueur valide."""
        joueur = Joueur(
            numero="7",
            nom="DUPONT",
            prenom="Jean",
            licence="123456789",
        )
        
        assert joueur.numero == "7"
        assert joueur.nom == "DUPONT"
        assert joueur.prenom == "Jean"
        assert joueur.licence == "123456789"
        assert joueur.est_capitaine is False
    
    def test_joueur_capitaine(self):
        """Test création d'un joueur capitaine."""
        joueur = Joueur(
            numero="1",
            nom="MARTIN",
            prenom="Pierre",
            licence="123456",
            est_capitaine=True,
        )
        
        assert joueur.est_capitaine is True
    
    def test_joueur_nom_complet(self):
        """Test la propriété nom_complet."""
        joueur = Joueur(
            numero="5",
            nom="DURAND",
            prenom="Marie",
            licence="987654321",
        )
        
        assert joueur.nom_complet == "DURAND Marie"


class TestSet:
    """Tests pour le modèle Set."""
    
    def test_set_valide(self):
        """Test création d'un set valide."""
        set_data = Set(
            numero=1,
            score_a=25,
            score_b=23,
        )
        
        assert set_data.numero == 1
        assert set_data.score_a == 25
        assert set_data.score_b == 23
    
    def test_set_vainqueur(self):
        """Test détection du vainqueur d'un set."""
        set_a = Set(numero=1, score_a=25, score_b=23)
        set_b = Set(numero=2, score_a=20, score_b=25)
        
        assert set_a.vainqueur == "A"
        assert set_b.vainqueur == "B"
    
    def test_set_score_str(self):
        """Test affichage du score."""
        set_data = Set(numero=1, score_a=25, score_b=18)
        assert set_data.score_str == "25-18"


class TestEquipe:
    """Tests pour le modèle Equipe."""
    
    def test_equipe_valide(self):
        """Test création d'une équipe valide."""
        joueur = Joueur(numero="1", nom="TEST", prenom="Test", licence="123456")
        
        equipe = Equipe(
            nom="AS Volley",
            joueurs=[joueur],
            liberos=[],
        )
        
        assert equipe.nom == "AS Volley"
        assert len(equipe.joueurs) == 1
    
    def test_equipe_vide(self):
        """Test création d'une équipe vide."""
        equipe = Equipe(
            nom="Empty Team",
            joueurs=[],
            liberos=[],
        )
        
        assert len(equipe.joueurs) == 0


class TestMatch:
    """Tests pour le modèle Match."""
    
    def test_match_valide(self, sample_match):
        """Test création d'un match valide."""
        assert sample_match.code_match == "2024-R1-001"
        assert sample_match.vainqueur_nom == "AS Volley Club"
        assert sample_match.score_final == "3-0"
    
    def test_match_avec_sets(self, sample_match):
        """Test que les sets sont correctement associés."""
        assert len(sample_match.sets) == 1
        assert sample_match.sets[0].numero == 1
