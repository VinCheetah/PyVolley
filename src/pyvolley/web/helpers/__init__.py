"""
Helpers web — Utilitaires spécifiques à l'interface web.
"""

from pyvolley.web.helpers.niveau import resolve_niveau_badge
from pyvolley.web.helpers.match_utils import (
    build_simulation_data,
    build_niveau_evolution,
    NIVEAU_ORDER,
    niveau_rank,
)
from pyvolley.web.helpers.brackets import (
    build_bracket_tree,
    build_challenge_bracket,
)
from pyvolley.web.helpers.club_branding import (
    parse_club_colors,
    detect_club_logo_url,
    build_club_branding,
)

__all__ = [
    "resolve_niveau_badge",
    "build_simulation_data",
    "build_niveau_evolution",
    "build_bracket_tree",
    "build_challenge_bracket",
    "NIVEAU_ORDER",
    "niveau_rank",
    "parse_club_colors",
    "detect_club_logo_url",
    "build_club_branding",
]
