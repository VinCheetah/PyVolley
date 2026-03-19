"""
Tests pour l'API FastAPI.
"""

import pytest
from fastapi.testclient import TestClient


class TestAPIHealth:
    """Tests pour l'endpoint de santé."""
    
    def test_health_check(self, api_client: TestClient):
        """Test que l'API répond correctement."""
        response = api_client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "pyvolley-api"


class TestAPISearch:
    """Tests pour l'endpoint de recherche."""
    
    def test_search_requires_query(self, api_client: TestClient):
        """Test que la recherche nécessite un paramètre q."""
        response = api_client.get("/api/search")
        
        assert response.status_code == 422  # Validation error
    
    def test_search_min_length(self, api_client: TestClient):
        """Test longueur minimale de recherche."""
        response = api_client.get("/api/search?q=a")
        
        assert response.status_code == 422  # min_length=2
    
    def test_search_empty_results(self, api_client: TestClient):
        """Test recherche sans résultats."""
        response = api_client.get("/api/search?q=xxxxxxx")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0


class TestAPIJoueurs:
    """Tests pour les endpoints joueurs."""
    
    def test_list_joueurs(self, api_client: TestClient):
        """Test liste des joueurs."""
        response = api_client.get("/api/joueurs")
        
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    
    def test_get_joueur_not_found(self, api_client: TestClient):
        """Test joueur non trouvé."""
        response = api_client.get("/api/joueurs/2147483647")
        
        assert response.status_code == 404


class TestAPIEquipes:
    """Tests pour les endpoints équipes."""
    
    def test_list_equipes(self, api_client: TestClient):
        """Test liste des équipes."""
        response = api_client.get("/api/equipes")
        
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    
    def test_get_equipe_not_found(self, api_client: TestClient):
        """Test équipe non trouvée."""
        response = api_client.get("/api/equipes/2147483647")
        
        assert response.status_code == 404


class TestAPIMatchs:
    """Tests pour les endpoints matchs."""
    
    def test_list_matchs(self, api_client: TestClient):
        """Test liste des matchs."""
        response = api_client.get("/api/matchs")
        
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    
    def test_get_match_not_found(self, api_client: TestClient):
        """Test match non trouvé."""
        response = api_client.get("/api/matchs/2147483647")
        
        assert response.status_code == 404


class TestAPIStats:
    """Tests pour l'endpoint statistiques."""
    
    def test_get_stats(self, api_client: TestClient):
        """Test récupération des statistiques."""
        response = api_client.get("/api/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert "total_matchs" in data
        assert "total_joueurs" in data
        assert "total_clubs" in data
        assert "total_equipes" in data
