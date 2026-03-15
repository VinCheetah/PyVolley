"""
Interface abstraite et modèles de base pour les scrapers.

Classes clés :
- ``MatchInfo`` : Informations minimales d'un match (pour le téléchargement)
- ``CompetitionInfo`` : Informations sur une compétition
- ``ScrapeResult`` : Résultat d'une opération de scraping
- ``BaseScraper`` : Interface abstraite pour les scrapers
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Iterator

from pyvolley.shared.pdf_storage import build_pdf_filename


@dataclass
class MatchInfo:
    """Informations sur un match (suffisant pour le téléchargement PDF).

    Pour les données enrichies depuis l'export CSV, voir
    ``ExportMatchInfo`` dans ``scrapers.ffvb.export_scraper``.
    """
    code: str                          # Code du match (ex: PMAA001)
    entite_code: str                   # Code de l'entité (ex: ABCCS, LIIDF)
    saison: str                        # Saison (ex: 2025/2026)
    poule_code: Optional[str] = None   # Code poule (ex: PMA)
    journee: Optional[str] = None
    pdf_url: Optional[str] = None

    @property
    def filename(self) -> str:
        """Nom du fichier PDF."""
        return build_pdf_filename(
            match_code=self.code,
            entite_code=self.entite_code,
            poule_code=self.poule_code,
            journee=self.journee,
        )


@dataclass
class CompetitionInfo:
    """Informations sur une compétition."""
    code: str
    nom: str
    entite_code: str
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
    """Interface abstraite pour les scrapers de données volleyball."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du scraper."""

    @property
    @abstractmethod
    def base_url(self) -> str:
        """URL de base du site."""

    @abstractmethod
    def get_entities(self) -> list[dict]:
        """Récupère la liste des entités (ligues, comités, nationales)."""

    @abstractmethod
    def get_matches(self, entite_code: str, saison: str) -> Iterator[MatchInfo]:
        """Récupère les matchs d'une entité pour une saison."""

    @abstractmethod
    def download_match_pdf(self, match: MatchInfo, output_dir: Path) -> ScrapeResult:
        """Télécharge le PDF d'un match."""
