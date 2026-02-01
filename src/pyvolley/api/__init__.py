"""
Module API - Endpoints FastAPI pour l'application PyVolley.

Fournit les routes pour :
- Recherche de joueurs, clubs, équipes
- Consultation des matchs
- Statistiques
- Import de données
"""

from pyvolley.api.app import create_app, app
from pyvolley.api.routes import router


__all__ = [
    "create_app",
    "app",
    "router",
]
