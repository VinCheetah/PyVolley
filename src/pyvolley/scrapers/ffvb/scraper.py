"""
Scraper principal pour le site FFVB (ffvbbeach.org).

Compose les sous-modules du package ``ffvb`` via un ``ScrapeContext``
partagé, tout en exposant la même interface publique que l'ancien fichier
monolithique.
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
from pyvolley.scrapers.ffvb import matches as _mat
from pyvolley.scrapers.ffvb import poules as _pou
from pyvolley.scrapers.ffvb.models import EntityInfo, PouleInfo, ScrapeContext
from pyvolley.scrapers.ffvb.utils import detect_categorie, detect_genre, get_current_saison

logger = logging.getLogger(__name__)


class FFVBScraper(BaseScraper):
    """
    Scraper pour le site des résultats FFVB.

    URL de base : https://www.ffvbbeach.org/ffvbapp/resu/

    Méthodes principales :
    - get_entities()          → entités (ligues, comités, nationales)
    - get_poules_for_entity() → poules d'une entité
    - get_matches_for_poule() → matchs d'une poule (FFVB + LNV)
    - download_match_pdf()    → télécharge le PDF d'un match
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

    # ── Propriétés ────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "FFVB"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def client(self) -> HttpClient:
        """Accès direct au client HTTP."""
        return self._client

    @property
    def ctx(self) -> ScrapeContext:
        """Contexte partagé (client + base_url)."""
        return self._ctx

    # ── Entités ───────────────────────────────────────────────────────────

    def get_entities(self) -> list[EntityInfo]:
        """Récupère la liste de toutes les entités depuis planning_volley.php."""
        return _ent.get_entities(self._ctx)

    def get_ligues(self) -> list[dict]:
        """Récupère la liste des ligues (compatibilité ancienne interface)."""
        return [
            {"code": e.code, "nom": e.nom, "type": e.type}
            for e in self.get_entities()
        ]

    # ── Poules ────────────────────────────────────────────────────────────

    def get_poules_for_entity(
        self,
        entity_code: str,
        saison: Optional[str] = None,
    ) -> list[PouleInfo]:
        """Récupère les poules/divisions disponibles pour une entité."""
        saison = saison or get_current_saison()
        return _pou.get_poules_for_entity(self._ctx, entity_code, saison)

    def get_poules(self, competition_code: str, ligue_code: str) -> list[dict]:
        """Compat ancienne interface."""
        return [
            {"code": p.code, "nom": p.nom}
            for p in self.get_poules_for_entity(ligue_code)
        ]

    # ── Compétitions ──────────────────────────────────────────────────────

    def get_competitions(
        self,
        ligue_code: str,
        saison: Optional[str] = None,
    ) -> list[CompetitionInfo]:
        """Récupère les compétitions d'une ligue (compatibilité interface)."""
        saison = saison or get_current_saison()
        return [
            CompetitionInfo(
                code=p.code,
                nom=p.nom,
                ligue_code=ligue_code,
                saison=saison,
                genre=detect_genre(p.nom),
                categorie=detect_categorie(p.nom),
            )
            for p in self.get_poules_for_entity(ligue_code, saison)
        ]

    # ── Matchs ────────────────────────────────────────────────────────────

    def get_matches_for_poule(
        self,
        entity_code: str,
        poule_code: str,
        saison: Optional[str] = None,
        *,
        is_division: bool = False,
    ) -> Iterator[MatchInfo]:
        """Récupère tous les matchs d'une poule."""
        saison = saison or get_current_saison()
        yield from _mat.get_matches_for_poule(
            self._ctx, entity_code, poule_code, saison,
            is_division=is_division,
        )

    def get_matches(self, competition: CompetitionInfo) -> Iterator[MatchInfo]:
        """Récupère les matchs d'une compétition (compatibilité interface)."""
        yield from _mat.get_matches(self._ctx, competition)

    def get_all_matches_for_entity(
        self,
        entity_code: str,
        saison: Optional[str] = None,
    ) -> Iterator[MatchInfo]:
        """Récupère TOUS les matchs de toutes les poules d'une entité."""
        saison = saison or get_current_saison()
        poules = self.get_poules_for_entity(entity_code, saison)
        yield from _mat.get_all_matches_for_entity(
            self._ctx, entity_code, saison, poules
        )

    # ── Téléchargement ────────────────────────────────────────────────────

    def download_match_pdf(
        self,
        match: MatchInfo,
        output_dir: Path,
    ) -> ScrapeResult:
        """Télécharge le PDF d'un match."""
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

    def download_all_matches_for_entity(
        self,
        entity_code: str,
        base_output_dir: Path,
        saison: Optional[str] = None,
        skip_existing: bool = True,
        organize_by_poule: bool = True,
    ) -> list[ScrapeResult]:
        """Télécharge toutes les feuilles de match d'une entité."""
        saison = saison or get_current_saison()
        poules = self.get_poules_for_entity(entity_code, saison)
        return _dl.download_all_matches_for_entity(
            self._ctx, entity_code, base_output_dir, saison, poules,
            skip_existing, organize_by_poule,
        )

    def collect_all_pdf_urls(
        self,
        entity_codes: Optional[list[str]] = None,
        saison: Optional[str] = None,
        entity_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """Collecte toutes les URLs de PDFs sans télécharger."""
        saison = saison or get_current_saison()

        if entity_codes is None:
            entities = self.get_entities()
            if entity_types:
                entities = [e for e in entities if e.type in entity_types]
            entity_codes = [e.code for e in entities]

        return _dl.collect_all_pdf_urls(
            self._ctx, entity_codes, saison,
            lambda ec, s: self.get_all_matches_for_entity(ec, s),
        )

    # ── Utilitaires (compat) ──────────────────────────────────────────────

    @staticmethod
    def _get_current_saison() -> str:
        return get_current_saison()

    @staticmethod
    def _detect_genre(nom: str) -> Optional[str]:
        return detect_genre(nom)

    @staticmethod
    def _detect_categorie(nom: str) -> Optional[str]:
        return detect_categorie(nom)
