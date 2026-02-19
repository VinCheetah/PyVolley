"""
Utilitaires partagés par les sous-modules du scraper FFVB.

Fournit les fonctions communes pour éviter la duplication de code :
- Construction d'URLs (calendrier, PDF)
- Détection de saison courante
- Détection genre / catégorie depuis les noms de compétitions
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import urlencode, urljoin


# ── Saison ────────────────────────────────────────────────────────────────


def get_current_saison() -> str:
    """Retourne la saison courante au format ``YYYY/YYYY``."""
    now = datetime.now()
    if now.month >= 9:
        return f"{now.year}/{now.year + 1}"
    return f"{now.year - 1}/{now.year}"


# ── Construction d'URLs ──────────────────────────────────────────────────


def build_calendar_url(
    base_url: str,
    entity_code: str,
    saison: str,
    *,
    poule: Optional[str] = None,
    division: Optional[str] = None,
    complet: bool = True,
) -> str:
    """
    Construit l'URL d'une page calendrier FFVB.

    Au moins ``poule`` ou ``division`` doit être fourni.
    """
    params: dict[str, str] = {
        "saison": saison,
        "codent": entity_code,
    }
    if poule:
        params["poule"] = poule
    if division:
        params["division"] = division
    if complet:
        params["calend"] = "COMPLET"
    return urljoin(base_url, f"vbspo_calendrier.php?{urlencode(params)}")


def build_pdf_url(
    base_url: str,
    entity_code: str,
    match_code: str,
    saison: str,
) -> str:
    """Construit l'URL FFVB classique pour récupérer le PDF d'un match."""
    params = {
        "saison": saison,
        "codent": entity_code,
        "codmatch": match_code,
    }
    return urljoin(base_url, f"ffvolley_fdme.php?{urlencode(params)}")


def build_home_url(base_url: str, entity_code: str, saison: str) -> str:
    """Construit l'URL de la page home (sommaire) d'une entité."""
    params = {"saison": saison, "codent": entity_code}
    return urljoin(base_url, f"vbspo_home.php?{urlencode(params)}")


# ── Détection genre / catégorie ──────────────────────────────────────────


def detect_genre(nom: str) -> Optional[str]:
    """Détecte le genre depuis le nom de compétition."""
    nom_upper = nom.upper()
    if any(x in nom_upper for x in ("MASCULIN", " M ", "MASC")):
        return "MASCULIN"
    if any(x in nom_upper for x in ("FEMININ", "FÉMININ", " F ", "FEM")):
        return "FEMININ"
    return None


def detect_categorie(nom: str) -> Optional[str]:
    """Détecte la catégorie depuis le nom de compétition."""
    nom_upper = nom.upper()
    if "SENIOR" in nom_upper:
        return "SENIOR"
    for cat in ("M21", "M20", "M18", "M17", "M15", "M13"):
        if cat in nom_upper:
            return cat
    return None
