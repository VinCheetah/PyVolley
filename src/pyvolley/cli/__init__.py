"""
Module CLI - Interface en ligne de commande pour PyVolley.

Fournit des commandes pour :
- Scraper les feuilles de match
- Parser les PDFs
- Importer en base de données
- Lancer le serveur web
"""

from pyvolley.cli.main import app, main


__all__ = ["app", "main"]
