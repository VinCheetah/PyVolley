"""
Module Analysis – Analyse de matchs, joueurs, équipes et compétitions.

Fonctions principales :
    analyze_match:       Analyse complète d'un match unique.
    analyze_joueur_over_matches: Bilan d'un joueur sur plusieurs matchs.
    analyze_equipe:      Bilan d'une équipe sur une série de matchs.
    analyze_competition: Classement et statistiques d'une compétition/ligue.

Tous les résultats sont retournés sous forme de modèles Pydantic
définis dans ``analysis.models``.
"""

from .match import analyze_match
from .joueur import analyze_joueur_over_matches
from .equipe import analyze_equipe
from .competition import analyze_competition
from .models import (
    MatchAnalysis,
    SetAnalysis,
    JoueurMatchAnalysis,
    PresenceSet,
    ServiceStats,
    EquipeSeasonRecord,
    JoueurSeasonRecord,
    CompetitionAnalysis,
)

__all__ = [
    # Fonctions d'analyse
    "analyze_match",
    "analyze_joueur_over_matches",
    "analyze_equipe",
    "analyze_competition",
    # Modèles de résultats
    "MatchAnalysis",
    "SetAnalysis",
    "JoueurMatchAnalysis",
    "PresenceSet",
    "ServiceStats",
    "EquipeSeasonRecord",
    "JoueurSeasonRecord",
    "CompetitionAnalysis",
]
