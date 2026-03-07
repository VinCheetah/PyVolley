"""
Modeles de donnees specifiques au scraper FFVB.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyvolley.scrapers.http_client import HttpClient


@dataclass
class EntityInfo:
    """Informations sur une entite (ligue, comite, competition nationale)."""
    code: str   # Code de l entite (ex: LIIDF, ABCCS, PTPL44)
    nom: str    # Nom complet
    type: str   # Type: nationale, ligue, comite


@dataclass
class PouleInfo:
    """Informations sur une poule/division."""
    code: str           # Code de la poule (ex: EFA, EFB)
    nom: str            # Nom complet
    entity_code: str    # Code de l entite parente
    saison: str         # Saison (ex: 2025/2026)
    is_division: bool = False
    url_calendrier: str | None = None  # URL du calendrier de cette poule


@dataclass
class ScrapeContext:
    """Contexte partage par tous les sous-modules du scraper FFVB."""
    client: HttpClient
    base_url: str
