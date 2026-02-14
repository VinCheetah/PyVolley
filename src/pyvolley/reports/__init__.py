"""
Module de génération de rapports pour PyVolley.

Architecture extensible : chaque rapport est composé de sections
qui peuvent être ajoutées, retirées ou réordonnées facilement.
"""

from .base import Report, ReportSection
from .joueur import JoueurReport
from .club import ClubReport
from .equipe import EquipeReport
from .match import MatchReport
from .arbitre import ArbitreReport
from .competition import CompetitionReport
from .saison import SaisonReport

__all__ = [
    "Report",
    "ReportSection",
    "JoueurReport",
    "ClubReport",
    "EquipeReport",
    "MatchReport",
    "ArbitreReport",
    "CompetitionReport",
    "SaisonReport",
]
