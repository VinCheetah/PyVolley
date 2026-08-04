"""
Module Parsers – Extraction des données des PDFs de feuilles de match FFVB.

Structure :
    parser.py            – Orchestrateur principal (MatchSheetParser)
    base.py              – Interface abstraite BaseParser + ParseResult
    diagnostics.py       – Système de diagnostic structuré
    constants.py         – Constantes partagées
    utils.py             – Fonctions utilitaires pures
    validation.py        – Validation de cohérence post-parsing
    factory.py           – Factory pour instanciation
    extractors/          – Modules d'extraction spécialisés
        header.py        – En-tête du match
        equipes.py       – Équipes, joueurs, libéros, capitaines, officiels
        sets.py          – Sections SET, formations, changements
        resultats.py     – Résultat global, arbitres, sanctions, remarques
"""

from pyvolley.parsers.base import BaseParser, ParseResult
from pyvolley.parsers.parser import MatchSheetParser
from pyvolley.parsers.fast_parser import FastMatchSheetParser
from pyvolley.parsers.factory import ParserFactory, get_parser
from pyvolley.parsers.diagnostics import (
    Diagnostic,
    DiagnosticLevel,
    DiagnosticOrigin,
    DiagnosticCategory,
    DiagnosticCollector,
    CATEGORY_FOLDERS,
)
from pyvolley.parsers.plausibility import (
    PlausibilityEngine,
    PlausibilityReport,
    PlausibilityIssue,
    PlausibilityAction,
    PlausibilitySeverity,
)

__all__ = [
    "BaseParser",
    "ParseResult",
    "MatchSheetParser",
    "FastMatchSheetParser",
    "ParserFactory",
    "get_parser",
    "Diagnostic",
    "DiagnosticLevel",
    "DiagnosticOrigin",
    "DiagnosticCategory",
    "DiagnosticCollector",
    "CATEGORY_FOLDERS",
    "PlausibilityEngine",
    "PlausibilityReport",
    "PlausibilityIssue",
    "PlausibilityAction",
    "PlausibilitySeverity",
]
