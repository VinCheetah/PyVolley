"""
Tests pour les modèles Pydantic.
"""

import pytest
from pydantic import ValidationError

from pyvolley.core.models import JoueurData, EquipeData, SetData, MatchData


class TestJoueurData:
    """Tests pour le modèle JoueurData."""
    
    def test_creation_valide(self):
        """Test création d'un joueur valide."""
        joueur = JoueurData(
            numero=7,
            nom="DUPONT",
            prenom="Jean",
            licence="123456789",
        )
        
        assert joueur.numero == 7
        assert joueur.nom == "DUPONT"
        assert joueur.prenom == "Jean"
        assert joueur.licence == "123456789"
        assert joueur.est_capitaine is False
    
    def test_joueur_capitaine(self):
        """Test création d'un joueur capitaine."""
        joueur = JoueurData(
            numero=1,
            nom="MARTIN",
            prenom="Pierre",
            est_capitaine=True,
        )
        
        assert joueur.est_capitaine is True
    
    def test_joueur_minimal(self):
        """Test création d'un joueur avec données minimales."""
        joueur = JoueurData(
            numero=0,
            nom="TEST",
            prenom="",
        )
        
        assert joueur.numero == 0
        assert joueur.licence is None


class TestSetData:
    """Tests pour le modèle SetData."""
    
    def test_set_valide(self):
        """Test création d'un set valide."""
        set_data = SetData(
            numero=1,
            score_a=25,
            score_b=23,
            debut="14:00",
            fin="14:30",
        )
        
        assert set_data.numero == 1
        assert set_data.score_a == 25
        assert set_data.score_b == 23
    
    def test_set_sans_horaires(self):
        """Test création d'un set sans horaires."""
        set_data = SetData(
            numero=2,
            score_a=25,
            score_b=18,
        )
        
        assert set_data.debut is None
        assert set_data.fin is None


class TestEquipeData:
    """Tests pour le modèle EquipeData."""
    
    def test_equipe_valide(self):
        """Test création d'une équipe valide."""
        joueur = JoueurData(numero=1, nom="TEST", prenom="Test")
        
        equipe = EquipeData(
            nom="AS Volley",
            joueurs=[joueur],
            liberos=[],
            officiels=[],
        )
        
        assert equipe.nom == "AS Volley"
        assert len(equipe.joueurs) == 1
    
    def test_equipe_vide(self):
        """Test création d'une équipe vide."""
        equipe = EquipeData(
            nom="Empty Team",
            joueurs=[],
            liberos=[],
            officiels=[],
        )
        
        assert len(equipe.joueurs) == 0


class TestMatchData:
    """Tests pour le modèle MatchData."""
    
    def test_match_valide(self, sample_match):
        """Test création d'un match valide."""
        assert sample_match.code_match == "2024-R1-001"
        assert sample_match.vainqueur == "AS Volley Club"
        assert sample_match.score_final == "3-0"
    
    def test_match_avec_sets(self, sample_match):
        """Test que les sets sont correctement associés."""
        assert len(sample_match.sets) == 1
        assert sample_match.sets[0].numero == 1
