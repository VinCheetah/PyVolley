"""
Téléchargement et recherche de PDFs de feuilles de match FFVB.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import requests

from pyvolley.core.exceptions import ScrapingError
from pyvolley.scrapers.base import MatchInfo, ScrapeResult
from pyvolley.scrapers.ffvb.models import PouleInfo, ScrapeContext
from pyvolley.scrapers.ffvb.utils import build_pdf_url

logger = logging.getLogger(__name__)


def download_match_pdf(
    ctx: ScrapeContext,
    match: MatchInfo,
    output_dir: Path,
) -> ScrapeResult:
    """
    Télécharge le PDF d'un match.

    Returns:
        ScrapeResult avec le statut du téléchargement.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / match.filename

    try:
        if not match.pdf_url:
            match.pdf_url = build_pdf_url(
                ctx.base_url, match.ligue_code, match.code, match.saison
            )

        response = ctx.client.get(match.pdf_url)

        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not response.content.startswith(b"%PDF"):
            return ScrapeResult(
                success=False,
                message=f"Not a PDF: {match.filename}",
                error=ScrapingError("Invalid content type"),
            )

        with open(filepath, "wb") as f:
            f.write(response.content)

        return ScrapeResult(
            success=True,
            message=f"Downloaded: {match.filename}",
            data={"path": str(filepath), "size": len(response.content)},
        )

    except Exception as e:
        return ScrapeResult(
            success=False,
            message=f"Failed: {match.filename}",
            error=e,
        )


def search_by_code(
    ctx: ScrapeContext,
    match_code: str,
    entity_code: str,
    saison: str,
) -> Optional[MatchInfo]:
    """
    Recherche un match par son code (HEAD request pour vérifier l'existence).

    Returns:
        MatchInfo si le PDF existe, None sinon.
    """
    pdf_url = build_pdf_url(ctx.base_url, entity_code, match_code, saison)

    try:
        ctx.client.rate_limit()
        response = ctx.client.session.head(pdf_url, timeout=ctx.client.timeout)
        if response.status_code == 200:
            poule_match = re.match(r"([A-Z]+)", match_code)
            competition_code = poule_match.group(1) if poule_match else match_code[:3]

            return MatchInfo(
                code=match_code,
                competition_code=competition_code,
                ligue_code=entity_code,
                saison=saison,
                pdf_url=pdf_url,
            )
    except requests.RequestException:
        pass

    return None


def download_all_matches_for_entity(
    ctx: ScrapeContext,
    entity_code: str,
    base_output_dir: Path,
    saison: str,
    poules: list[PouleInfo],
    skip_existing: bool = True,
    organize_by_poule: bool = True,
) -> list[ScrapeResult]:
    """Télécharge toutes les feuilles de match d'une entité."""
    from pyvolley.scrapers.ffvb.matches import get_matches_for_poule

    base_output_dir = Path(base_output_dir)
    results: list[ScrapeResult] = []

    for poule in poules:
        if organize_by_poule:
            saison_folder = saison.replace("/", "-")
            output_dir = base_output_dir / saison_folder / entity_code / poule.code
        else:
            output_dir = base_output_dir

        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            matches = list(get_matches_for_poule(
                ctx, entity_code, poule.code, saison,
                is_division=poule.is_division,
            ))
        except Exception as e:
            logger.warning(
                "Erreur lors de la récupération des matchs %s/%s saison %s : %s",
                entity_code, poule.code, saison, e,
            )
            results.append(ScrapeResult(
                success=False,
                message=f"Erreur calendrier {poule.code}: {e}",
                error=e,
            ))
            continue

        for match in matches:
            filepath = output_dir / match.filename

            if skip_existing and filepath.exists():
                results.append(ScrapeResult(
                    success=True,
                    message=f"Skipped (exists): {match.filename}",
                ))
                continue

            result = download_match_pdf(ctx, match, output_dir)
            results.append(result)

    return results


def collect_all_pdf_urls(
    ctx: ScrapeContext,
    entity_codes: list[str],
    saison: str,
    get_all_matches_fn,
) -> list[dict]:
    """
    Collecte toutes les URLs de PDFs sans télécharger.

    Args:
        get_all_matches_fn: Callable(entity_code, saison) → Iterator[MatchInfo]
    """
    all_matches: list[dict] = []

    for entity_code in entity_codes:
        try:
            for match in get_all_matches_fn(entity_code, saison):
                all_matches.append({
                    "entity_code": match.ligue_code,
                    "poule_code": match.competition_code,
                    "match_code": match.code,
                    "saison": match.saison,
                    "pdf_url": match.pdf_url,
                    "filename": match.filename,
                })
        except Exception as e:
            logger.warning("Erreur pour l'entité %s: %s", entity_code, e)

    return all_matches
