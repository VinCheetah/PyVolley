"""
Modèles de données spécifiques au scraper FFVB.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyvolley.scrapers.http_client import HttpClient


@dataclass
class EntityInfo:
    """Informations sur une entité (ligue, comité, compétition nationale)."""
    code: str  # Code de l'entité (ex: LIIDF, ABCCS, PTPL44)
    nom: str   # Nom complet
    type: str  # Type: 'nationale', 'ligue', 'comite'


@dataclass
class PouleInfo:
    """Informations sur une poule/division."""
    code: str          # Code de la poule (ex: EFA, EFB)
    nom: str           # Nom complet
    entity_code: str   # Code de l'entité parente
    saison: str        # Saison (ex: 2025/2026)
    is_division: bool = False  # True si c'est une division plutôt qu'une poule


@dataclass
class ScrapeContext:
    """
    Contexte partagé par tous les sous-modules du scraper FFVB.

    Évite de passer ``client`` et ``base_url`` comme arguments séparés
    à chaque fonction.
    """
    client: HttpClient
    base_url: str  # ex: https://www.ffvbbeach.org/ffvbapp/resu/
