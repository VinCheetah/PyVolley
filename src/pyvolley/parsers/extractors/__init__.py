"""
Sous-modules d'extraction pour le parsing des feuilles de match FFVB.
"""

from __future__ import annotations

# ── Extracteurs directs ultra-rapides PyMuPDF (FastMatchSheetParser) ──
from pyvolley.parsers.extractors.fast import (
    WordTuple,
    normalize_words,
    slice_words_in_box,
    slice_words_in_region,
    extract_text_in_region,
    HeaderData,
    extract_fast_header,
    extract_team_marker,
    FastRosterData,
    extract_fast_rosters,
    extract_single_team_roster,
    FastResultsData,
    SetSummary,
    extract_fast_resultats,
    extract_fast_arbitres,
    extract_fast_sets,
)

# ── Shims et adaptateurs de compatibilité ──
from pyvolley.parsers.extractors.zone_extractor import (
    extract_hierarchical_data,
    extract_text_in_zone,
)
from pyvolley.parsers.extractors.equipes_geometry import (
    extract_team_roster_geometry,
    RosterData,
)
from pyvolley.parsers.extractors.sets_geometry import (
    extract_sets_geometry,
)

# ── Extracteurs heuristiques pdfplumber (MatchSheetParser / Legacy) ──
from pyvolley.parsers.extractors.header import extract_header
from pyvolley.parsers.extractors.equipes import (
    extract_equipes,
    extract_joueurs,
    extract_liberos,
    extract_officiels,
    detect_capitaines,
    recover_joueurs_from_sets,
)
from pyvolley.parsers.extractors.sets import (
    extract_all_sets,
    extract_resultats_table,
    build_sets,
)
from pyvolley.parsers.extractors.resultats import (
    extract_resultat,
    extract_arbitres,
    extract_sanctions,
    extract_remarques,
    extract_demande_non_fondee,
    compute_match_played,
)

__all__ = [
    # Fast direct
    "WordTuple",
    "normalize_words",
    "slice_words_in_box",
    "slice_words_in_region",
    "extract_text_in_region",
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
    # Shims
    "extract_hierarchical_data",
    "extract_text_in_zone",
    "extract_team_roster_geometry",
    "RosterData",
    "extract_sets_geometry",
    # Legacy
    "extract_header",
    "extract_equipes",
    "extract_joueurs",
    "extract_liberos",
    "extract_officiels",
    "detect_capitaines",
    "recover_joueurs_from_sets",
    "extract_all_sets",
    "extract_resultats_table",
    "build_sets",
    "extract_resultat",
    "extract_arbitres",
    "extract_sanctions",
    "extract_remarques",
    "extract_demande_non_fondee",
    "compute_match_played",
]
