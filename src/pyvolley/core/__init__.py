"""
Module Core - Modèles de données et services métier.

Contient :
- Configuration de l'application
- Modèles Pydantic (schémas de données)
- Services métier (recherche, statistiques)
- Exceptions personnalisées
"""

from pyvolley.core.config import settings
from pyvolley.core.models import (
    Joueur,
    Equipe,
    Club,
    Match,
    Set,
    Arbitre,
    Sanction,
    Saison,
)
from pyvolley.core.exceptions import PyVolleyError

__all__ = [
    "settings",
    "Joueur",
    "Equipe", 
    "Club",
    "Match",
    "Set",
    "Arbitre",
    "Sanction",
    "Saison",
    "PyVolleyError",
]
