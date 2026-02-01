"""
PyVolley - Système de statistiques volleyball français.

Ce package fournit des outils pour :
- Scraper les feuilles de match depuis le site FFVB
- Parser les PDFs pour extraire les données
- Stocker les données dans une base de données
- Rechercher et analyser les statistiques

Usage:
    from pyvolley.parsers import ParserFactory
    from pyvolley.scrapers import FFVBScraper
    from pyvolley.database import get_db, JoueurRepository
"""

__version__ = "0.1.0"
__author__ = "PyVolley Team"

from pyvolley.core.config import settings

__all__ = [
    "settings",
    "__version__",
]
