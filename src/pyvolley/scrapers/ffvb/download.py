"""
Téléchargement et recherche de PDFs de feuilles de match FFVB.

Gère les cas spéciaux :
- PDFs LNV hébergés sur lnv.fr ou datavolley.lnv.fr
  → datavolley.lnv.fr a un certificat SSL invalide (domaine mort)
  → www.lnv.fr ne conserve que les PDFs récents (≥ 2023/2024)
  → Fallback automatique vers le PDF FFVB quand l'URL externe échoue
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


def _is_external_pdf_url(url: str) -> bool:
    """Vrai si l'URL pointe vers un serveur externe (LNV, etc.)."""
    return "lnv.fr" in url or "datavolley" in url.lower()


def _try_download_external_pdf(
    ctx: ScrapeContext,
    url: str,
) -> Optional[requests.Response]:
    """
    Tente de télécharger un PDF externe (lnv.fr, datavolley.lnv.fr).

    - datavolley.lnv.fr : certificat SSL invalide → skip verify
    - www.lnv.fr : peut 404 pour les anciennes saisons

    Returns:
        Response si succès, None sinon.
    """
    try:
        ctx.client.rate_limit()
        # datavolley.lnv.fr a un certificat SSL invalide (domaine mort)
        verify = "datavolley.lnv.fr" not in url
        resp = ctx.client.session.get(url, timeout=ctx.client.timeout, verify=verify)
        if resp.status_code == 200 and resp.content.startswith(b"%PDF"):
            return resp
        logger.debug(
            "PDF externe non disponible (status=%d): %s", resp.status_code, url,
        )
    except requests.exceptions.SSLError:
        logger.debug("Erreur SSL sur PDF externe: %s", url)
    except requests.exceptions.RequestException as e:
        logger.debug("Erreur réseau sur PDF externe: %s (%s)", url, e)
    return None


def download_match_pdf(
    ctx: ScrapeContext,
    match: MatchInfo,
    output_dir: Path,
) -> ScrapeResult:
    """
    Télécharge le PDF d'un match.

    Pour les matchs LNV dont le PDF est hébergé sur un serveur externe
    (lnv.fr, datavolley.lnv.fr), tente d'abord l'URL externe puis
    retombe sur le PDF FFVB en cas d'échec (SSL, 404, etc.).

    Returns:
        ScrapeResult avec le statut du téléchargement.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / match.filename

    try:
        if not match.pdf_url:
            match.pdf_url = build_pdf_url(
                ctx.base_url, match.entite_code, match.code, match.saison
            )

        response = None

        # ── Cas 1 : PDF externe (LNV) ───────────────────────────
        if _is_external_pdf_url(match.pdf_url):
            response = _try_download_external_pdf(ctx, match.pdf_url)
            if response is None:
                # Fallback : PDF FFVB classique
                ffvb_url = build_pdf_url(
                    ctx.base_url, match.entite_code, match.code, match.saison,
                )
                logger.info(
                    "Fallback FFVB pour %s (external URL failed)", match.code,
                )
                response = ctx.client.get(ffvb_url)
        else:
            # ── Cas 2 : PDF FFVB classique ───────────────────────
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
            poule_match = re.match(r"([A-Z]{2}[A-Z0-9])", match_code)
            competition_code = poule_match.group(1) if poule_match else match_code[:3]

            return MatchInfo(
                code=match_code,
                entite_code=entity_code,
                saison=saison,
                poule_code=competition_code,
                pdf_url=pdf_url,
            )
    except requests.RequestException:
        pass

    return None


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
                    "entity_code": match.entite_code,
                    "poule_code": match.poule_code,
                    "match_code": match.code,
                    "saison": match.saison,
                    "pdf_url": match.pdf_url,
                    "filename": match.filename,
                })
        except Exception as e:
            logger.warning("Erreur pour l'entité %s: %s", entity_code, e)

    return all_matches
