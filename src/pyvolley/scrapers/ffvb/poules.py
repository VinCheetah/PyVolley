"""
Découverte des poules / divisions pour une entité FFVB.

Implémente plusieurs stratégies complémentaires et les **fusionne** pour
ne manquer aucune poule :
1. Page home (sommaire) — la plus fiable, fonctionne pour tout
2. Scraping ffvb.org (nationale uniquement, liens index_xxx.htm)
3. Page calendrier (fallback)
4. Patterns connus (fallback ultime, entités nationales)
"""

from __future__ import annotations

import logging
import re

from pyvolley.scrapers.ffvb.models import PouleInfo, ScrapeContext
from pyvolley.scrapers.ffvb.patterns import get_known_poules
from pyvolley.scrapers.ffvb.utils import build_home_url

logger = logging.getLogger(__name__)

# Mapping des entités vers des pages ffvb.org pour lister les index_xxx.htm
ENTITY_FFVB_URLS: dict[str, str] = {
    "ABCCS": "http://www.ffvb.org/front/119-159-1-Championnats-Nationaux",
    "ACJEUNES": "http://www.ffvb.org/front/124-167-1-Coupes-de-France-Jeunes",
}


def get_poules_for_entity(
    ctx: ScrapeContext,
    entity_code: str,
    saison: str,
) -> list[PouleInfo]:
    """
    Récupère les poules/divisions disponibles pour une entité.

    **Toutes** les stratégies sont essayées et les résultats fusionnés
    (dédupliqués par code). Le nom le plus descriptif est conservé.
    """
    # Accumulateur dédupliqué : code → PouleInfo
    seen: dict[str, PouleInfo] = {}

    def _merge(poules: list[PouleInfo]) -> None:
        for p in poules:
            existing = seen.get(p.code)
            if existing is None:
                seen[p.code] = p
            else:
                # Garder le nom le plus descriptif (plus long, pas juste le code)
                # et propager is_division si détecté
                if len(p.nom) > len(existing.nom) and p.nom != p.code:
                    existing.nom = p.nom
                if p.is_division:
                    existing.is_division = True

    # 1. Page home (sommaire) — la plus complète pour trouver les codes
    _merge(_from_home(ctx, entity_code, saison))

    # 2. ffvb.org (entités nationales uniquement)
    if entity_code in ENTITY_FFVB_URLS:
        _merge(_from_ffvb_org(ctx, entity_code, saison))

    # 3. Page calendrier (parfois contient des poules non listées ailleurs)
    _merge(_from_calendar(ctx, entity_code, saison))

    # 4. Patterns connus — apportent les noms descriptifs et les codes manquants
    _merge(get_known_poules(entity_code, saison))

    return list(seen.values())


# ── Stratégies de découverte ──────────────────────────────────────────────


def _from_home(
    ctx: ScrapeContext,
    entity_code: str,
    saison: str,
) -> list[PouleInfo]:
    """Récupère les poules depuis la page home (sommaire) de l'entité."""
    url = build_home_url(ctx.base_url, entity_code, saison)

    try:
        soup = ctx.client.get_soup(url)
    except Exception:
        return []

    poules: list[PouleInfo] = []
    seen_codes: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.text.strip()

        # Liens avec poule= (classique)
        if "vbspo_calendrier.php" in href and "poule=" in href:
            match = re.search(r"poule=([^&]+)", href)
            if match:
                code = match.group(1).upper()
                if code and code not in seen_codes:
                    seen_codes.add(code)
                    nom = _clean_poule_name(code, text)
                    poules.append(PouleInfo(
                        code=code, nom=nom,
                        entity_code=entity_code, saison=saison,
                    ))

        # Liens avec division= (ACJEUNES, etc.)
        elif "vbspo_calendrier.php" in href and "division=" in href:
            match = re.search(r"division=([^&]+)", href)
            if match:
                code = match.group(1).upper()
                if code and code not in seen_codes:
                    seen_codes.add(code)
                    poules.append(PouleInfo(
                        code=code,
                        nom=text or code,
                        entity_code=entity_code,
                        saison=saison,
                        is_division=True,
                    ))

    return poules


def _from_ffvb_org(
    ctx: ScrapeContext,
    entity_code: str,
    saison: str,
) -> list[PouleInfo]:
    """Récupère les poules depuis ffvb.org (liens index_xxx.htm)."""
    url = ENTITY_FFVB_URLS.get(entity_code)
    if not url:
        return []

    try:
        soup = ctx.client.get_soup(url)
    except Exception:
        return []

    poules: list[PouleInfo] = []
    seen_codes: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.text.strip()
        if "ffvbbeach.org/ffvbapp/resu" in href and "index_" in href:
            match = re.search(r"index_([^.]+)\.htm", href)
            if match:
                code = match.group(1).upper()
                if code not in seen_codes:
                    seen_codes.add(code)
                    poules.append(PouleInfo(
                        code=code,
                        nom=text or code,
                        entity_code=entity_code,
                        saison=saison,
                    ))
    return poules


def _from_calendar(
    ctx: ScrapeContext,
    entity_code: str,
    saison: str,
) -> list[PouleInfo]:
    """Récupère les poules depuis la page calendrier."""
    from pyvolley.scrapers.ffvb.utils import build_calendar_url

    url = build_calendar_url(
        ctx.base_url, entity_code, saison, complet=False,
    )

    try:
        soup = ctx.client.get_soup(url)
    except Exception:
        return []

    poules: list[PouleInfo] = []
    seen_codes: set[str] = set()

    # Formulaires
    for form in soup.find_all("form"):
        action = form.get("action", "")
        if "vbspo_calendrier.php" in action:
            poule_input = form.find("input", {"name": "poule"})
            if poule_input and poule_input.get("value"):
                code = poule_input["value"].upper()
                if code and code not in seen_codes:
                    seen_codes.add(code)
                    poules.append(PouleInfo(
                        code=code, nom=code,
                        entity_code=entity_code, saison=saison,
                    ))

    # Liens directs
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "poule=" in href:
            match = re.search(r"poule=([^&]+)", href)
            if match:
                code = match.group(1).upper()
                if code and code not in seen_codes:
                    seen_codes.add(code)
                    poules.append(PouleInfo(
                        code=code,
                        nom=link.text.strip() or code,
                        entity_code=entity_code, saison=saison,
                    ))

    return poules


# ── Helpers ───────────────────────────────────────────────────────────────


def _clean_poule_name(code: str, raw_text: str) -> str:
    """Nettoie le nom de la poule récupéré depuis un lien."""
    nom = raw_text
    if nom.upper().startswith(code):
        nom = nom[len(code):].strip()
    return f"{code} {nom}" if nom else code
