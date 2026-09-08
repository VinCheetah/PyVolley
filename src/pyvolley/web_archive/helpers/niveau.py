"""
Résolution des badges et hiérarchie des niveaux de volley pour la couche web.

Ce module réexporte les fonctionnalités du module partagé ``pyvolley.shared.niveau``
pour assurer la compatibilité et l'accès direct par les templates Jinja2.
"""

from pyvolley.shared.niveau import (
    LEVEL_SORT_ORDER,
    RANK_REFERENCE_LABELS,
    niveau_sort_rank,
    niveau_sort_key,
    niveau_reference_labels,
    resolve_niveau_badge,
    normalize_level_text as _normalize_level_text,
)

__all__ = [
    "LEVEL_SORT_ORDER",
    "RANK_REFERENCE_LABELS",
    "niveau_sort_rank",
    "niveau_sort_key",
    "niveau_reference_labels",
    "resolve_niveau_badge",
    "_normalize_level_text",
]
