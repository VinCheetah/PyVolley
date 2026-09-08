"""
Package des extracteurs déterministes ultra-rapides pour les feuilles de match FFVB.
"""

from __future__ import annotations

from pyvolley.parsers.extractors.fast.utils import (
    WordTuple,
    normalize_words,
    slice_words_in_box,
    slice_words_in_region,
    extract_text_in_region,
    group_words_by_line,
    parse_date_heure,
    parse_time_token,
)
from pyvolley.parsers.extractors.fast.header import (
    HeaderData,
    extract_fast_header,
    extract_team_marker,
)
from pyvolley.parsers.extractors.fast.rosters import (
    FastRosterData,
    extract_fast_rosters,
    extract_single_team_roster,
)
from pyvolley.parsers.extractors.fast.resultats import (
    FastResultsData,
    SetSummary,
    extract_fast_resultats,
)
from pyvolley.parsers.extractors.fast.arbitres import (
    extract_fast_arbitres,
)
from pyvolley.parsers.extractors.fast.sets import (
    extract_fast_sets,
)

__all__ = [
    "WordTuple",
    "normalize_words",
    "slice_words_in_box",
    "slice_words_in_region",
    "extract_text_in_region",
    "group_words_by_line",
    "parse_date_heure",
    "parse_time_token",
    "HeaderData",
    "extract_fast_header",
    "extract_team_marker",
    "FastRosterData",
    "extract_fast_rosters",
    "extract_single_team_roster",
    "FastResultsData",
    "SetSummary",
    "extract_fast_resultats",
    "extract_fast_arbitres",
    "extract_fast_sets",
]
