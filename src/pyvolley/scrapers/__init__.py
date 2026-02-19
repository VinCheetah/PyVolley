"""
Module Scrapers - Récupération des feuilles de match.

Contient :
- Interface abstraite BaseScraper
- Implémentation FFVBScraper pour le site FFVB
- LNVScraper pour les compétitions professionnelles (via FFVB)
- Utilitaires de téléchargement
"""

from pyvolley.scrapers.base import BaseScraper
from pyvolley.scrapers.ffvb import FFVBScraper
from pyvolley.scrapers.lnv import LNVScraper

__all__ = ["BaseScraper", "FFVBScraper", "LNVScraper"]
