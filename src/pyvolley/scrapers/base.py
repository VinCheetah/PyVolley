"""
Interface abstraite pour les scrapers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Iterator


@dataclass
class MatchInfo:
    """Informations sur un match à télécharger."""
    code: str  # Code du match (ex: PMAA001)
    competition_code: str  # Code de la compétition (ex: PMA)
    ligue_code: str  # Code de la ligue (ex: LIIDF)
    saison: str  # Saison (ex: 2024-2025)
    journee: Optional[str] = None
    pdf_url: Optional[str] = None
    
    @property
    def filename(self) -> str:
        """Nom du fichier PDF."""
        return f"{self.ligue_code}_{self.code}.pdf"


@dataclass
class CompetitionInfo:
    """Informations sur une compétition."""
    code: str
    nom: str
    ligue_code: str
    saison: str
    genre: Optional[str] = None
    categorie: Optional[str] = None
    poules: list[str] = field(default_factory=list)


@dataclass
class ScrapeResult:
    """Résultat d'une opération de scraping."""
    success: bool
    message: str
    data: Optional[dict] = None
    error: Optional[Exception] = None


class BaseScraper(ABC):
    """
    Interface abstraite pour les scrapers de feuilles de match.
    
    Permet de supporter différentes sources de données
    (FFVB, autres fédérations, etc.)
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du scraper."""
        pass
    
    @property
    @abstractmethod
    def base_url(self) -> str:
        """URL de base du site."""
        pass
    
    @abstractmethod
    def get_ligues(self) -> list[dict]:
        """
        Récupère la liste des ligues disponibles.
        
        Returns:
            Liste de dictionnaires avec clés: code, nom
        """
        pass
    
    @abstractmethod
    def get_competitions(self, ligue_code: str, saison: Optional[str] = None) -> list[CompetitionInfo]:
        """
        Récupère les compétitions d'une ligue.
        
        Args:
            ligue_code: Code de la ligue
            saison: Saison (optionnel, défaut = saison courante)
            
        Returns:
            Liste des compétitions
        """
        pass
    
    @abstractmethod
    def get_matches(self, competition: CompetitionInfo) -> Iterator[MatchInfo]:
        """
        Récupère les matchs d'une compétition.
        
        Args:
            competition: Information sur la compétition
            
        Yields:
            Informations sur chaque match
        """
        pass
    
    @abstractmethod
    def download_match_pdf(self, match: MatchInfo, output_dir: Path) -> ScrapeResult:
        """
        Télécharge le PDF d'un match.
        
        Args:
            match: Informations sur le match
            output_dir: Dossier de destination
            
        Returns:
            Résultat de l'opération
        """
        pass
    
    def download_competition(
        self, 
        competition: CompetitionInfo, 
        output_dir: Path,
        skip_existing: bool = True
    ) -> list[ScrapeResult]:
        """
        Télécharge tous les PDFs d'une compétition.
        
        Args:
            competition: Information sur la compétition
            output_dir: Dossier de destination
            skip_existing: Ignorer les fichiers existants
            
        Returns:
            Liste des résultats
        """
        results = []
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for match in self.get_matches(competition):
            if skip_existing:
                filepath = output_dir / match.filename
                if filepath.exists():
                    results.append(ScrapeResult(
                        success=True,
                        message=f"Skipped (exists): {match.filename}"
                    ))
                    continue
            
            result = self.download_match_pdf(match, output_dir)
            results.append(result)
        
        return results
