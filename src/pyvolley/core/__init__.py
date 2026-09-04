"""
Module Core - Modèles de données et services métier.

Contient :
- Configuration de l'application
- Modèles Pydantic (schémas de données)
- Services métier (recherche, statistiques)
- Exceptions personnalisées
"""

from pyvolley.core.config import settings
from pyvolley.core.constants import (
    ALL_ROLES,
    ALL_SPECIFIC_ROLES,
    Categorie,
    Genre,
    Niveau,
    RoleArbitre,
    RoleJoueur,
    TypeSanction,
    ROLE_COLORS,
    ROLE_LABELS,
    ROLE_LIBERO,
    ROLE_MIDDLE,
    ROLE_MULTI,
    ROLE_OPPOSITE,
    ROLE_OUTSIDE,
    ROLE_SETTER,
    ROLE_UNKNOWN,
    get_role_label,
)
from pyvolley.core.exceptions import PyVolleyError
from pyvolley.core.models import (
    Arbitre,
    Club,
    Equipe,
    Joueur,
    Match,
    Saison,
    Sanction,
    Set,
)

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
    "Genre",
    "Categorie",
    "Niveau",
    "TypeSanction",
    "RoleArbitre",
    "RoleJoueur",
    "ROLE_SETTER",
    "ROLE_OPPOSITE",
    "ROLE_MIDDLE",
    "ROLE_OUTSIDE",
    "ROLE_LIBERO",
    "ROLE_MULTI",
    "ROLE_UNKNOWN",
    "ALL_SPECIFIC_ROLES",
    "ALL_ROLES",
    "ROLE_LABELS",
    "ROLE_COLORS",
    "get_role_label",
    "PyVolleyError",
]
