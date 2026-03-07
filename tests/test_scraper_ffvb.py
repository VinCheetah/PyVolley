"""
Tests pour le scraper FFVB.

Ces tests vérifient le bon fonctionnement du scraper pour le site ffvbbeach.org.
Note: Certains tests font des requêtes réelles au site FFVB (tests d'intégration).
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile

from pyvolley.scrapers.ffvb import FFVBScraper, EntityInfo, PouleInfo
from pyvolley.scrapers.ffvb.entities import detect_entity_type
from pyvolley.scrapers.ffvb.utils import (
    build_pdf_url,
    detect_categorie,
    detect_genre,
    get_current_saison,
)
from pyvolley.scrapers.base import MatchInfo, CompetitionInfo, ScrapeResult


# ============== Fixtures ==============

@pytest.fixture
def scraper():
    """Crée une instance du scraper FFVB."""
    return FFVBScraper(request_delay=0.1)  # Délai réduit pour les tests


@pytest.fixture
def mock_scraper():
    """Crée un scraper avec un client HTTP mocké."""
    with patch.object(FFVBScraper, 'client', new_callable=lambda: property(lambda self: Mock())) as _:
        scraper = FFVBScraper(request_delay=0)
        yield scraper


# ============== Tests unitaires ==============

class TestFFVBScraperInit:
    """Tests d'initialisation du scraper."""
    
    def test_default_initialization(self):
        """Vérifie l'initialisation avec les valeurs par défaut."""
        scraper = FFVBScraper()
        assert scraper.name == "FFVB"
        assert "ffvbbeach.org" in scraper.base_url
    
    def test_custom_initialization(self):
        """Vérifie l'initialisation avec des valeurs personnalisées."""
        scraper = FFVBScraper(
            base_url="https://custom.url/",
            request_delay=2.0,
            timeout=60
        )
        assert scraper.base_url == "https://custom.url/"
        assert scraper.client.delay == 2.0
        assert scraper.client.timeout == 60


class TestEntityTypeDetection:
    """Tests de détection du type d'entité."""
    
    def test_detect_nationale(self):
        """Détecte les compétitions nationales."""
        assert detect_entity_type("ABCCS", "Compétitions Nationales") == "nationale"
        assert detect_entity_type("ACJEUNES", "Nationales Jeunes") == "nationale"
    
    def test_detect_ligue(self):
        """Détecte les ligues régionales."""
        assert detect_entity_type("LIIDF", "Ligue Ile-de-France") == "ligue"
        assert detect_entity_type("LIPL", "Ligue Pays de la Loire") == "ligue"
    
    def test_detect_comite(self):
        """Détecte les comités départementaux."""
        assert detect_entity_type("PTPL44", "CD44 - Loire-Atlantique") == "comite"
        assert detect_entity_type("PTIDF75", "Comité Paris") == "comite"


class TestGenreCategorie:
    """Tests de détection du genre et de la catégorie."""
    
    def test_detect_genre_masculin(self):
        """Détecte le genre masculin."""
        assert detect_genre("Elite Masculine") == "MASCULIN"
        assert detect_genre("N2 MASC Poule A") == "MASCULIN"
    
    def test_detect_genre_feminin(self):
        """Détecte le genre féminin."""
        assert detect_genre("Elite Féminine") == "FEMININ"
        assert detect_genre("N2 FEM Poule A") == "FEMININ"
    
    def test_detect_genre_inconnu(self):
        """Retourne None si genre inconnu."""
        assert detect_genre("Poule A") is None
    
    def test_detect_categorie_senior(self):
        """Détecte la catégorie senior."""
        assert detect_categorie("Seniors Masculins") == "SENIOR"
    
    def test_detect_categorie_jeunes(self):
        """Détecte les catégories jeunes."""
        assert detect_categorie("M18 Masculins") == "M18"
        assert detect_categorie("M15 Féminines") == "M15"


class TestSaisonCalculation:
    """Tests de calcul de la saison."""
    
    def test_get_current_saison(self):
        """Vérifie le format de la saison."""
        saison = get_current_saison()
        assert "/" in saison
        parts = saison.split("/")
        assert len(parts) == 2
        assert int(parts[1]) == int(parts[0]) + 1


class TestBuildPdfUrl:
    """Tests de construction des URLs PDF."""
    
    def test_build_pdf_url(self):
        """Vérifie la construction de l'URL du PDF."""
        base = "https://www.ffvbbeach.org/ffvbapp/resu/"
        url = build_pdf_url(base, "ABCCS", "EFA001", "2025/2026")
        assert "ffvolley_fdme.php" in url
        assert "saison=2025%2F2026" in url
        assert "codent=ABCCS" in url
        assert "codmatch=EFA001" in url


# ============== Tests d'intégration (requêtes réelles) ==============

@pytest.mark.integration
class TestFFVBScraperIntegration:
    """
    Tests d'intégration avec le site FFVB réel.
    
    Ces tests font des requêtes réelles et peuvent être lents.
    Exécuter avec: pytest -m integration
    """
    
    def test_get_entities(self, scraper):
        """Vérifie la récupération des entités."""
        entities = scraper.get_entities()
        
        assert len(entities) > 0
        assert any(e.code == "ABCCS" for e in entities)
        assert any(e.code == "LIIDF" for e in entities)
        
        # Vérifier la structure
        for entity in entities[:5]:
            assert entity.code
            assert entity.nom
            assert entity.type in ["nationale", "ligue", "comite", "autre"]
    
    def test_discover_poules_for_abccs(self, scraper):
        """Vérifie la découverte des poules pour ABCCS via export CSV."""
        poules = scraper.discover_poules("ABCCS", "2025/2026")
        
        assert len(poules) > 0
        # Vérifier les poules attendues
        poule_codes = [p.code for p in poules]
        assert "EFA" in poule_codes
        assert "EMA" in poule_codes
    
    def test_discover_poules_for_ligue_lira(self, scraper):
        """Vérifie la découverte des poules pour une ligue (LIRA)."""
        poules = scraper.discover_poules("LIRA", "2025/2026")
        
        assert len(poules) > 0
        # Vérifier qu'on a des poules typiques de ligue
        poule_codes = [p.code for p in poules]
        # LIRA a des poules comme PMA (Prénational Masculin A)
        assert any(code.startswith("P") for code in poule_codes), "Devrait avoir des poules Prénationales"
    
    def test_scrape_entity(self, scraper):
        """Vérifie la récupération des matchs via export CSV."""
        matches = scraper.scrape_entity("ABCCS", "2025/2026", poule="EFA")
        
        assert len(matches) > 0
        
        # Vérifier la structure ExportMatchInfo
        for match in matches[:5]:
            assert match.code_match.startswith("EFA")
            assert match.entite_code == "ABCCS"
            assert match.saison == "2025/2026"
            assert match.feuille_match_url
    
    def test_get_matches_iterator(self, scraper):
        """Vérifie la conversion en MatchInfo via get_matches."""
        matches = list(scraper.get_matches("ABCCS", "2025/2026"))
        
        assert len(matches) > 0
        for match in matches[:5]:
            assert match.entite_code == "ABCCS"
            assert match.code
            assert match.pdf_url
    
    def test_download_pdf(self, scraper):
        """Vérifie le téléchargement d'un PDF."""
        # Récupérer un match via get_matches
        matches = list(scraper.get_matches("ABCCS", "2025/2026"))
        # Filtrer les matchs EFA
        efa_matches = [m for m in matches if m.code.startswith("EFA")]
        assert len(efa_matches) > 0
        
        # Télécharger dans un dossier temporaire
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scraper.download_match_pdf(efa_matches[0], Path(tmpdir))
            
            assert result.success
            assert result.data
            assert result.data["size"] > 0
            
            # Vérifier que le fichier existe
            filepath = Path(result.data["path"])
            assert filepath.exists()
            assert filepath.suffix == ".pdf"
    
    def test_search_by_code(self, scraper):
        """Vérifie la recherche par code."""
        match = scraper.search_by_code("EFA001", "ABCCS", "2025/2026")
        
        assert match is not None
        assert match.code == "EFA001"
        assert match.entite_code == "ABCCS"


# ============== Tests de robustesse ==============

@pytest.mark.integration
class TestErrorHandling:
    """Tests de gestion des erreurs (requêtes réelles)."""
    
    def test_invalid_entity_code(self, scraper):
        """Vérifie le comportement avec un code entité invalide."""
        poules = scraper.discover_poules("INVALID_CODE", "2025/2026")
        # Devrait retourner une liste vide plutôt qu'une erreur
        assert poules == []
    
    def test_invalid_poule_filter(self, scraper):
        """Vérifie le comportement avec un code poule invalide."""
        matches = scraper.scrape_entity("ABCCS", "2025/2026", poule="INVALID")
        # Le filtrage client-side garantit une liste vide
        assert matches == []


# ============== Marqueurs pytest ==============

def pytest_configure(config):
    """Configure les marqueurs personnalisés."""
    config.addinivalue_line(
        "markers", "integration: tests d'intégration avec le site FFVB réel"
    )
