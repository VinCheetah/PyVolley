"""API publique du package ``pyvolley.analysis``.

Le package expose uniquement les modules d'analyse actifs utilisés
par l'API/web actuelle :

- classement FFVB strict
- statistiques détaillées joueur
"""

from .classement import (
    MatchData,
    LigneClassement,
    EvolutionJournee,
    ClassementComplet,
    calculer_classement,
    calculer_classement_complet,
)
from .joueur_stats import analyze_joueur_match, aggregate_joueur_stats, build_set_timeline
from .models import (
    PresenceSet,
    ServiceSetDetail,
    JoueurMatchDetailedStats,
    JoueurStatsAggregated,
)

__all__ = [
    "MatchData",
    "LigneClassement",
    "EvolutionJournee",
    "ClassementComplet",
    "calculer_classement",
    "calculer_classement_complet",
    "analyze_joueur_match",
    "aggregate_joueur_stats",
    "build_set_timeline",
    "PresenceSet",
    "ServiceSetDetail",
    "JoueurMatchDetailedStats",
    "JoueurStatsAggregated",
]
