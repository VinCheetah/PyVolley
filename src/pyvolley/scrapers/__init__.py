"""
Module Scrapers - Récupération des feuilles de match.

Contient :
- Interface abstraite BaseScraper
- Implémentation FFVBScraper pour le site FFVB
- Utilitaires de téléchargement
"""

from pyvolley.scrapers.base import BaseScraper
from pyvolley.scrapers.ffvb import FFVBScraper

__all__ = ["BaseScraper", "FFVBScraper"]
