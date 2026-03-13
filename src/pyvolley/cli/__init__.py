"""
Module CLI — Interface en ligne de commande pour PyVolley.

Commandes principales :
- import : importer des données FFVB (scrape → download → parse)
- status : tableau de bord du pipeline
- list   : consulter entités, poules, matchs
- parse  : analyser un PDF
- serve  : lancer le serveur web
"""

from pyvolley.cli.main import app, main


__all__ = ["app", "main"]
