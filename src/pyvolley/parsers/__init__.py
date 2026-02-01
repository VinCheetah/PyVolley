"""
Module Parsers - Extraction des données des PDFs.

Contient :
- Interface abstraite BaseParser
- Différentes implémentations de parsers (pour benchmark)
- Factory pour sélectionner le meilleur parser
"""

from pyvolley.parsers.base import BaseParser, ParseResult
from pyvolley.parsers.v2 import MatchSheetParserV2
from pyvolley.parsers.v3 import MatchSheetParserV3
from pyvolley.parsers.factory import ParserFactory, get_parser

__all__ = [
    "BaseParser",
    "ParseResult", 
    "MatchSheetParserV2",
    "MatchSheetParserV3",
    "ParserFactory",
    "get_parser",
]
