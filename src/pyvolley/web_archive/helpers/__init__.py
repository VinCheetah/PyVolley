"""
Helpers web — Utilitaires spécifiques à l'interface web.
"""

from pyvolley.web.helpers.niveau import (
    resolve_niveau_badge,
    niveau_sort_rank,
    niveau_sort_key,
    niveau_reference_labels,
    LEVEL_SORT_ORDER,
    RANK_REFERENCE_LABELS,
)
from pyvolley.web.helpers.match_utils import (
    build_simulation_data,
    build_niveau_evolution,
    build_momentum_data,
)
from pyvolley.web.helpers.brackets import (
    build_bracket_tree,
    build_challenge_bracket,
)
from pyvolley.web.helpers.club_branding import (
    parse_club_colors,
    build_club_branding,
)
from pyvolley.web.helpers.common import (
    safe_int,
    safe_float,
    pct,
    strip_accents,
    normalize_text_upper,
    normalize_numero,
    role_label,
    ROLE_LABELS,
    season_sort_key,
    season_end_year,
)

__all__ = [
    "resolve_niveau_badge",
    "niveau_sort_rank",
    "niveau_sort_key",
    "niveau_reference_labels",
    "LEVEL_SORT_ORDER",
    "RANK_REFERENCE_LABELS",
    "build_simulation_data",
    "build_niveau_evolution",
    "build_momentum_data",
    "build_bracket_tree",
    "build_challenge_bracket",
    "parse_club_colors",
    "build_club_branding",
    "safe_int",
    "safe_float",
    "pct",
    "strip_accents",
    "normalize_text_upper",
    "normalize_numero",
    "role_label",
    "ROLE_LABELS",
    "season_sort_key",
    "season_end_year",
]
