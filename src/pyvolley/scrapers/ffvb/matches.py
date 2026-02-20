"""
Découverte des matchs depuis le calendrier FFVB.

Gère trois cas de découverte :
- Cas 1 : formulaires classiques FFVB (ffvolley_fdme.php?codmatch=…)
- Cas 2 : PDFs externes hébergés sur lnv.fr (compétitions pro)
- Cas 3 : Énumération de codes (fallback quand le calendrier est bloqué par WAF)
"""

from __future__ import annotations

import logging
import re
from typing import Iterator

from pyvolley.scrapers.base import CompetitionInfo, MatchInfo
from pyvolley.scrapers.ffvb.models import PouleInfo, ScrapeContext
from pyvolley.scrapers.ffvb.utils import build_calendar_url, build_pdf_url

logger = logging.getLogger(__name__)

# Codes de poule bloqués par le WAF nginx (faux positifs ModSecurity).
# Le WAF bloque toute requête dont un paramètre vaut exactement "cmp" ou "rmt"
# (case-insensitive), car ces chaînes correspondent à des noms de commandes
# système. Les PDFs individuels restent accessibles.
WAF_BLOCKED_POULE_CODES = frozenset({"CMP", "RMT"})

# Nombre de templates consécutifs avant d'arrêter l'énumération.
_MAX_CONSECUTIVE_TEMPLATES = 10


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

    Si le calendrier est bloqué par le WAF (403 sur « CMP », « RMT »…),
    bascule automatiquement sur l'énumération de codes de match.

    Args:
        is_division: Si True, utilise ``division=`` au lieu de ``poule=``
            dans l'URL du calendrier (nécessaire pour ACJEUNES par ex.).

    Yields:
        MatchInfo pour chaque match trouvé.
    """

    # ── Détection WAF : certains codes déclenchent un 403 nginx ──
    if poule_code.upper() in WAF_BLOCKED_POULE_CODES and not is_division:
        logger.info(
            "Poule %s bloquée par le WAF – fallback par énumération de codes "
            "pour %s/%s saison %s",
            poule_code, entity_code, poule_code, saison,
        )
        yield from _enumerate_matches_for_blocked_poule(
            ctx, entity_code, poule_code, saison,
        )
        return

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


# ── Fallback WAF : énumération de codes de match ─────────────────────────


def _is_real_match_pdf(content: bytes) -> bool:
    """
    Vérifie si un PDF contient de vraies données de match.

    Les templates vides FFVB contiennent "xxxxx" comme nom d'équipe
    placeholder. Les vrais matchs ont des noms d'équipes réels.

    Utilise pymupdf (fitz) pour extraire le texte du PDF.
    En cas d'erreur de parsing, retourne False par sécurité.
    """
    try:
        import fitz  # pymupdf

        doc = fitz.open(stream=content, filetype="pdf")
        text = doc[0].get_text() if len(doc) > 0 else ""
        doc.close()
        return "xxxxx" not in text.lower()
    except Exception:
        return False


def _enumerate_matches_for_blocked_poule(
    ctx: ScrapeContext,
    entity_code: str,
    poule_code: str,
    saison: str,
    *,
    max_probe: int = 500,
) -> Iterator[MatchInfo]:
    """
    Découvre les matchs d'une poule WAF-bloquée par scan séquentiel
    des codes de match (POULE001, POULE002, …).

    Le serveur FFVB génère un PDF template pour *tout* code, mais les
    vrais matchs n'ont PAS le placeholder "xxxxx" dans leur texte.
    Les codes de match peuvent avoir des trous (ex: tournois avec byes),
    donc on scanne séquentiellement en s'arrêtant après N templates
    consécutifs.

    Args:
        max_probe: Numéro de match maximum à tester.

    Yields:
        MatchInfo pour chaque match réel trouvé.
    """
    import requests as _req

    consecutive_templates = 0
    real_count = 0

    for i in range(1, max_probe + 1):
        match_code = f"{poule_code}{i:03d}"
        pdf_url = build_pdf_url(
            ctx.base_url, entity_code, match_code, saison,
        )

        try:
            ctx.client.rate_limit()
            resp = ctx.client.session.get(
                pdf_url, timeout=ctx.client.timeout,
            )
            if resp.status_code != 200:
                consecutive_templates += 1
                if consecutive_templates >= _MAX_CONSECUTIVE_TEMPLATES:
                    break
                continue

            if _is_real_match_pdf(resp.content):
                consecutive_templates = 0
                real_count += 1
                yield MatchInfo(
                    code=match_code,
                    competition_code=poule_code,
                    ligue_code=entity_code,
                    saison=saison,
                    pdf_url=pdf_url,
                )
            else:
                consecutive_templates += 1
                if consecutive_templates >= _MAX_CONSECUTIVE_TEMPLATES:
                    break

        except _req.RequestException:
            consecutive_templates += 1
            if consecutive_templates >= _MAX_CONSECUTIVE_TEMPLATES:
                break

    if real_count:
        logger.info(
            "Énumération WAF : %d matchs découverts pour %s/%s saison %s",
            real_count, entity_code, poule_code, saison,
        )
    else:
        logger.info(
            "Aucun match trouvé par énumération pour %s/%s saison %s",
            entity_code, poule_code, saison,
        )
