"""
Package ``pyvolley.scrapers.ffvb`` — scraper FFVB modulaire.

Ré-exporte les types principaux pour que les imports existants
(``from pyvolley.scrapers.ffvb import FFVBScraper``) continuent de
fonctionner sans modification.
"""

from pyvolley.scrapers.ffvb.jeunes import (
    CATEGORY_LETTER_MAP,
    DIVISION_MAP,
    YouthCupIndex,
    YouthDivisionInfo,
    YouthMatchResult,
    YouthPouleInfo,
    YouthStandingEntry,
    YouthTourInfo,
    infer_division_from_poule_code,
)
from pyvolley.scrapers.ffvb.models import EntityInfo, PouleInfo, ScrapeContext
from pyvolley.scrapers.ffvb.scraper import FFVBScraper

__all__ = [
    "FFVBScraper",
    "EntityInfo",
    "PouleInfo",
    "ScrapeContext",
    # Coupe de France Jeunes
    "CATEGORY_LETTER_MAP",
    "DIVISION_MAP",
    "YouthCupIndex",
    "YouthDivisionInfo",
    "YouthMatchResult",
    "YouthPouleInfo",
    "YouthStandingEntry",
    "YouthTourInfo",
    "infer_division_from_poule_code",
]
