"""
Scraper principal pour le site FFVB (ffvbbeach.org).

Architecture en deux phases :
  Phase 1 : Export CSV -> ExportMatchInfo (rapide, complet)
  Phase 2 : Telechargement + parsing PDF (enrichissement)

Ce module compose les sous-modules :
  - export_scraper : extraction de donnees depuis l'export CSV
  - entities : decouverte des entites (ligues, comites)
  - download : telechargement de PDFs
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator, Optional

from pyvolley.core.config import settings
from pyvolley.scrapers.base import (
    BaseScraper,
    CompetitionInfo,
    MatchInfo,
    ScrapeResult,
)
from pyvolley.scrapers.http_client import HttpClient

from pyvolley.scrapers.ffvb import download as _dl
from pyvolley.scrapers.ffvb import entities as _ent
from pyvolley.scrapers.ffvb.export_scraper import (
    ExportMatchInfo,
    fetch_export,
    get_unique_clubs,
    get_unique_poules,
)
from pyvolley.scrapers.ffvb.models import EntityInfo, PouleInfo, ScrapeContext
from pyvolley.scrapers.ffvb.utils import (
    build_calendar_url,
    detect_categorie,
    detect_genre,
    get_current_saison,
)

logger = logging.getLogger(__name__)


class FFVBScraper(BaseScraper):
    """
    Scraper pour le site des resultats FFVB.

    URL de base : https://www.ffvbbeach.org/ffvbapp/resu/

    Pipeline en deux phases :
    1. ``scrape_entity()`` -> export CSV -> ExportMatchInfo (Phase 1)
    2. ``download_match_pdf()`` -> PDF -> parsing (Phase 2)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        request_delay: Optional[float] = None,
        timeout: Optional[int] = None,
    ):
        self._base_url = base_url or settings.ffvb_base_url
        self._client = HttpClient(
            request_delay=request_delay or settings.ffvb_request_delay,
            timeout=timeout or settings.ffvb_timeout,
        )
        self._ctx = ScrapeContext(client=self._client, base_url=self._base_url)

    # -- Proprietes --------------------------------------------------------

    @property
    def name(self) -> str:
        return "FFVB"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def client(self) -> HttpClient:
        """Acces direct au client HTTP."""
        return self._client

    @property
    def ctx(self) -> ScrapeContext:
        """Contexte partage (client + base_url)."""
        return self._ctx

    # -- Entites -----------------------------------------------------------

    def get_entities(self) -> list[EntityInfo]:
        """Recupere la liste de toutes les entites depuis planning_volley.php."""
        return _ent.get_entities(self._ctx)

    def get_ligues(self) -> list[dict]:
        """Recupere la liste des ligues (compat ancienne interface)."""
        return [
            {"code": e.code, "nom": e.nom, "type": e.type}
            for e in self.get_entities()
        ]

    # -- Phase 1 : Export CSV ----------------------------------------------

    def scrape_entity(
        self,
        entite_code: str,
        saison: Optional[str] = None,
        *,
        poule: Optional[str] = None,
    ) -> list[ExportMatchInfo]:
        """Recupere tous les matchs d'une entite via l'export CSV.

        C'est la methode principale de la Phase 1. Une seule requete HTTP
        retourne toutes les donnees structurees.

        Args:
            entite_code: Code de l'entite (ex: ABCCS)
            saison: Saison (ex: 2025/2026). Par defaut : saison courante.
            poule: Code poule optionnel pour filtrer.

        Returns:
            Liste de ExportMatchInfo avec toutes les metadonnees.
        """
        saison = saison or get_current_saison()
        return fetch_export(
            self._client,
            self._base_url,
            entite_code,
            saison,
            poule=poule,
        )

    def scrape_entities(
        self,
        entite_codes: list[str],
        saison: Optional[str] = None,
    ) -> dict[str, list[ExportMatchInfo]]:
        """Scrape plusieurs entites et retourne les resultats groupes.

        Args:
            entite_codes: Liste de codes d'entites.
            saison: Saison.

        Returns:
            Dict {entite_code: [matches]}.
        """
        saison = saison or get_current_saison()
        results: dict[str, list[ExportMatchInfo]] = {}
        for code in entite_codes:
            try:
                results[code] = self.scrape_entity(code, saison)
            except Exception as e:
                logger.error("Erreur scraping %s: %s", code, e)
                results[code] = []
        return results

    # -- Phase 1 : Decouverte des poules -----------------------------------

    def discover_poules(
        self,
        entite_code: str,
        saison: Optional[str] = None,
    ) -> list[PouleInfo]:
        """Decouvre les poules d'une entite via l'export CSV.

        Remplace l'ancienne decouverte par parsing HTML (poules.py) +
        patterns hardcodes (patterns.py).

        Returns:
            Liste de PouleInfo decouvertes automatiquement.
        """
        saison = saison or get_current_saison()
        matches = self.scrape_entity(entite_code, saison)
        poules_dict = get_unique_poules(matches)

        return [
            PouleInfo(
                code=code,
                nom=f"Poule {code}",
                entity_code=entite_code,
                saison=saison,
                url_calendrier=build_calendar_url(
                    self._base_url, entite_code, saison, poule=code,
                ),
            )
            for code in poules_dict
        ]

    # -- Phase 1 : Clubs uniques -------------------------------------------

    def get_club_codes(
        self,
        entite_code: str,
        saison: Optional[str] = None,
    ) -> set[str]:
        """Extrait les codes club FFVB uniques d'une entite.

        Args:
            entite_code: Code de l'entite.
            saison: Saison.

        Returns:
            Set de codes club (7 chiffres).
        """
        saison = saison or get_current_saison()
        matches = self.scrape_entity(entite_code, saison)
        return get_unique_clubs(matches)

    # -- Interface BaseScraper ---------------------------------------------

    def get_matches(
        self,
        entite_code: str,
        saison: Optional[str] = None,
    ) -> Iterator[MatchInfo]:
        """Recupere les matchs d'une entite (interface BaseScraper).

        Convertit les ExportMatchInfo en MatchInfo simples pour
        compatibilite avec le reste du systeme.
        """
        saison = saison or get_current_saison()
        for m in self.scrape_entity(entite_code, saison):
            yield MatchInfo(
                code=m.code_match,
                entite_code=m.entite_code,
                saison=m.saison,
                poule_code=m.poule_code,
                journee=m.journee,
                pdf_url=m.feuille_match_url,
            )

    # -- Telechargement PDF ------------------------------------------------

    def download_match_pdf(
        self,
        match: MatchInfo,
        output_dir: Path,
    ) -> ScrapeResult:
        """Telecharge le PDF d'un match."""
        return _dl.download_match_pdf(self._ctx, match, output_dir)

    def search_by_code(
        self,
        match_code: str,
        entity_code: str,
        saison: Optional[str] = None,
    ) -> Optional[MatchInfo]:
        """Recherche un match par son code."""
        saison = saison or get_current_saison()
        return _dl.search_by_code(
            self._ctx, match_code, entity_code, saison
        )

    # -- Utilitaires -------------------------------------------------------

    @staticmethod
    def _get_current_saison() -> str:
        return get_current_saison()

    @staticmethod
    def _detect_genre(nom: str) -> Optional[str]:
        return detect_genre(nom)

    @staticmethod
    def _detect_categorie(nom: str) -> Optional[str]:
        return detect_categorie(nom)
