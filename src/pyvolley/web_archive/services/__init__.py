"""
Package des services de vue (ViewServices) pour l'interface web PyVolley.

Ces services préparent, agrègent et structurent les données destinées aux templates
et composants interactifs, déchargeant ainsi les contrôleurs de routes FastAPI.
"""

from .joueur_view_service import JoueurViewService
from .match_view_service import MatchViewService

__all__ = [
    "JoueurViewService",
    "MatchViewService",
]
