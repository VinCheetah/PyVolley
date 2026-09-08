"""
Scraper pour les compétitions professionnelles LNV (Ligue Nationale de Volley).

Les matchs des compétitions professionnelles (Ligue A, Ligue B) sont gérés par
la LNV mais les feuilles de match sont hébergées sur le site FFVB (ffvbbeach.org)
sous l'entité ABCCS.

Ce module fournit un wrapper spécialisé qui :
- Identifie automatiquement les poules pro (MSL, SPS, LBM, LBF)
- Facilite l'accès aux matchs pro sans connaître les codes internes
- Peut être utilisé en complément du scraper FFVB standard

Compétitions couvertes :
- Marmara SpikeLigue (LAM) : code poule MSL
- Saforelle Power 6 (LAF) : code poule SPS
- Ligue B Masculine (LBM) : code poule LBM
- Ligue B Féminine (LBF) : code poule LBF
- Coupe de France Pro Masculine : code poule CFM
- Coupe de France Pro Féminine : code poule CFF
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from pyvolley.scrapers.base import MatchInfo, ScrapeResult
from pyvolley.scrapers.ffvb import FFVBScraper, PouleInfo

logger = logging.getLogger(__name__)


@dataclass
class ProCompetition:
    """Informations sur une compétition professionnelle."""
    code: str
    nom: str
    short_name: str  # Nom court (LAM, LAF, LBM, LBF)
    genre: str  # MASCULIN ou FEMININ


# Définition des compétitions pro connues
PRO_COMPETITIONS = [
    ProCompetition("MSL", "Marmara SpikeLigue", "LAM", "MASCULIN"),
    ProCompetition("SPS", "Saforelle Power 6", "LAF", "FEMININ"),
    ProCompetition("LBM", "Ligue B Masculine", "LBM", "MASCULIN"),
    ProCompetition("PAZ", "Marmara SpikeLigue - Playoffs", "LAM_PO", "MASCULIN"),
    ProCompetition("FAZ", "Saforelle Power 6 - Playoffs", "LAF_PO", "FEMININ"),
    ProCompetition("DAZ", "Ligue A Masculine - Qualification Europe", "LAM_EUR", "MASCULIN"),
    ProCompetition("PBA", "Ligue B Masculine - Playoffs Poule A", "LBM_POA", "MASCULIN"),
    ProCompetition("PBB", "Ligue B Masculine - Playoffs Poule B", "LBM_POB", "MASCULIN"),
    ProCompetition("PBZ", "Ligue B Masculine - Playoffs", "LBM_PO", "MASCULIN"),
]

# Entité FFVB qui héberge les compétitions pro LNV
PRO_ENTITY_CODE = "AALNV"


class LNVScraper:
    """
    Scraper pour les compétitions professionnelles LNV.

    Utilise le scraper FFVB en interne car les feuilles de match sont
    hébergées sur ffvbbeach.org.

    Usage::

        scraper = LNVScraper()

        # Lister les compétitions pro disponibles
        competitions = scraper.get_pro_competitions()

        # Récupérer les matchs d'une compétition
        for match in scraper.get_matches("MSL", "2025/2026"):
            print(match.code, match.pdf_url)

        # Récupérer TOUS les matchs pro
        for match in scraper.get_all_pro_matches("2025/2026"):
            print(match.code)

        # Télécharger un match
        result = scraper.download_match(match, Path("data/pdfs"))
    """

    def __init__(self, ffvb_scraper: Optional[FFVBScraper] = None):
        self._scraper = ffvb_scraper or FFVBScraper()

    @staticmethod
    def get_pro_competitions() -> list[ProCompetition]:
        """Retourne la liste des compétitions professionnelles connues."""
        return list(PRO_COMPETITIONS)

    def discover_competitions(
        self,
        saison: Optional[str] = None,
    ) -> list[PouleInfo]:
        """
        Découvre dynamiquement les compétitions LNV disponibles.

        Interroge la page d'accueil AALNV pour récupérer les poules
        réellement actives, y compris celles non listées dans
        PRO_COMPETITIONS (nouvelles poules, tests, etc.).

        Returns:
            Liste des PouleInfo découvertes.
        """
        if saison is None:
            saison = self._scraper._get_current_saison()
        return self._scraper.discover_poules(PRO_ENTITY_CODE, saison)

    def get_matches(
        self,
        competition_code: str,
        saison: Optional[str] = None,
    ) -> Iterator[MatchInfo]:
        """
        Récupère les matchs d'une compétition pro.

        Args:
            competition_code: Code de la compétition (ex: MSL, SPS, LBM)
            saison: Saison au format YYYY/YYYY

        Yields:
            MatchInfo pour chaque match trouvé
        """
        if saison is None:
            saison = self._scraper._get_current_saison()

        for m in self._scraper.scrape_entity(PRO_ENTITY_CODE, saison, poule=competition_code):
            yield MatchInfo(
                code=m.code_match,
                entite_code=m.entite_code,
                saison=m.saison,
                poule_code=m.poule_code,
                journee=m.journee,
                pdf_url=m.feuille_match_url,
            )

    def get_all_pro_matches(
        self,
        saison: Optional[str] = None,
    ) -> Iterator[MatchInfo]:
        """
        Récupère tous les matchs de toutes les compétitions pro.

        Args:
            saison: Saison au format YYYY/YYYY

        Yields:
            MatchInfo pour chaque match trouvé
        """
        if saison is None:
            saison = self._scraper._get_current_saison()

        try:
            for m in self._scraper.scrape_entity(PRO_ENTITY_CODE, saison):
                yield MatchInfo(
                    code=m.code_match,
                    entite_code=m.entite_code,
                    saison=m.saison,
                    poule_code=m.poule_code,
                    journee=m.journee,
                    pdf_url=m.feuille_match_url,
                )
        except Exception as e:
            logger.warning("Erreur lors de la récupération des matchs pro saison %s : %s", saison, e)

    def download_match(
        self,
        match: MatchInfo,
        output_dir: Path,
        overwrite: bool = False,
    ) -> ScrapeResult:
        """Télécharge le PDF d'un match pro."""
        return self._scraper.download_match_pdf(match, output_dir, overwrite=overwrite)

    def count_matches(
        self,
        saison: Optional[str] = None,
    ) -> dict[str, int]:
        """
        Compte le nombre de matchs par compétition pro.

        Returns:
            Dictionnaire {code_compétition: nombre_matchs}
        """
        if saison is None:
            saison = self._scraper._get_current_saison()

        counts: dict[str, int] = {comp.code: 0 for comp in PRO_COMPETITIONS}
        try:
            for m in self._scraper.scrape_entity(PRO_ENTITY_CODE, saison):
                if m.poule_code in counts:
                    counts[m.poule_code] += 1
                else:
                    counts[m.poule_code] = 1
        except Exception as e:
            logger.warning("Erreur comptage global pro saison %s: %s", saison, e)
            for comp in PRO_COMPETITIONS:
                counts[comp.code] = -1
        return counts

