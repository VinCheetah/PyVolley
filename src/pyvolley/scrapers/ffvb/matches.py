"""
Découverte des matchs depuis le calendrier FFVB.

Gère deux types de feuilles de match :
- Cas 1 : formulaires classiques FFVB (ffvolley_fdme.php?codmatch=…)
- Cas 2 : PDFs externes hébergés sur lnv.fr (compétitions pro)
"""

from __future__ import annotations

import logging
import re
from typing import Iterator

from pyvolley.scrapers.base import CompetitionInfo, MatchInfo
from pyvolley.scrapers.ffvb.models import PouleInfo, ScrapeContext
from pyvolley.scrapers.ffvb.utils import build_calendar_url, build_pdf_url

logger = logging.getLogger(__name__)


def get_matches_for_poule(
    ctx: ScrapeContext,
    entity_code: str,
    poule_code: str,
    saison: str,
    *,
    is_division: bool = False,
) -> Iterator[MatchInfo]:
    """
    Récupère tous les matchs d'une poule depuis la page calendrier.

    Args:
        is_division: Si True, utilise ``division=`` au lieu de ``poule=``
            dans l'URL du calendrier (nécessaire pour ACJEUNES par ex.).

    Yields:
        MatchInfo pour chaque match trouvé.
    """
    url = build_calendar_url(
        ctx.base_url,
        entity_code,
        saison,
        poule=None if is_division else poule_code,
        division=poule_code if is_division else None,
    )

    soup = ctx.client.safe_get_soup(url)
    if soup is None:
        logger.warning(
            "Impossible de récupérer le calendrier pour %s/%s saison %s",
            entity_code, poule_code, saison,
        )
        return

    seen_codes: set[str] = set()

    for form in soup.find_all("form"):
        action = form.get("action", "")

        # --- Cas 1 : feuille de match FFVB classique ---
        if "ffvolley_fdme.php" in action:
            m = re.search(r"codmatch=([^&]+)", action)
            if m:
                match_code = m.group(1)
                if match_code in seen_codes:
                    continue
                seen_codes.add(match_code)

                pdf_url = build_pdf_url(
                    ctx.base_url, entity_code, match_code, saison
                )
                yield MatchInfo(
                    code=match_code,
                    competition_code=poule_code,
                    ligue_code=entity_code,
                    saison=saison,
                    pdf_url=pdf_url,
                )

        # --- Cas 2 : PDF externe (LNV / lnv.fr) ---
        elif action.endswith(".pdf") and (
            "lnv.fr" in action or "datavolley" in action.lower()
        ):
            code_match = re.search(
                r"/([A-Z0-9]{3,6}\d{3})-\d{4}\.pdf", action
            )
            if not code_match:
                # Fallback : chercher le code dans les cellules de la ligne
                tr = form.find_parent("tr")
                if tr:
                    for cell in tr.find_all("td"):
                        ct = cell.get_text(strip=True)
                        if re.match(r"^[A-Z]{2,5}\d{3,4}$", ct):
                            code_match = re.match(
                                r"^([A-Z]{2,5}\d{3,4})$", ct
                            )
                            break

            if code_match:
                match_code = code_match.group(1)
                if match_code in seen_codes:
                    continue
                seen_codes.add(match_code)

                yield MatchInfo(
                    code=match_code,
                    competition_code=poule_code,
                    ligue_code=entity_code,
                    saison=saison,
                    pdf_url=action,
                )


def get_matches(
    ctx: ScrapeContext,
    competition: CompetitionInfo,
) -> Iterator[MatchInfo]:
    """Raccourci qui accepte un ``CompetitionInfo``."""
    yield from get_matches_for_poule(
        ctx,
        entity_code=competition.ligue_code,
        poule_code=competition.code,
        saison=competition.saison,
    )


def get_all_matches_for_entity(
    ctx: ScrapeContext,
    entity_code: str,
    saison: str,
    poules: list[PouleInfo],
) -> Iterator[MatchInfo]:
    """
    Récupère TOUS les matchs de toutes les poules d'une entité.

    Les erreurs par poule sont loguées mais n'interrompent pas le traitement.
    """
    for poule in poules:
        try:
            yield from get_matches_for_poule(
                ctx, entity_code, poule.code, saison,
                is_division=poule.is_division,
            )
        except Exception as e:
            logger.warning(
                "Erreur lors de la récupération des matchs %s/%s saison %s : %s",
                entity_code, poule.code, saison, e,
            )
