"""
Helpers web communs — Utilitaires partagés entre les routes web.

Regroupe les fonctions utilitaires qui étaient dupliquées dans plusieurs
modules de routes (joueurs.py, equipes.py, matchs.py, clubs.py).
"""

from __future__ import annotations

import re
from typing import Optional

# Réexport des utilitaires transverses centralisés dans shared.helpers
from pyvolley.shared.helpers import (
    safe_int,
    safe_float,
    pct,
    strip_accents,
    normalize_text_upper,
    normalize_numero,
    parse_optional_int,
    is_winner,
)


# ═══════════════════════════════════════════════════════════════════
#  Rôles de joueurs
# ═══════════════════════════════════════════════════════════════════

from pyvolley.core.constants import ROLE_LABELS, get_role_label


def role_label(role_code: Optional[str]) -> str:
    """Retourne un label humain pour un code de rôle."""
    return get_role_label(role_code, default="Non déterminé")


# ═══════════════════════════════════════════════════════════════════
#  Tri de saisons
# ═══════════════════════════════════════════════════════════════════

_SEASON_CODE_RE = re.compile(r"(\d{4})\s*[-/]\s*(\d{4})")
_SEASON_SHORT_CODE_RE = re.compile(r"\b(\d{2})\s*[-/]\s*(\d{2})\b")


def season_sort_key(code: Optional[str]) -> tuple[int, int, str]:
    """Clé de tri pour les codes de saison (ex: '2024-2025').

    Retourne (année_début, année_fin, code) pour un tri naturel.
    """
    if not code:
        return (0, 0, "")
    match = _SEASON_CODE_RE.search(code)
    if match:
        return (int(match.group(1)), int(match.group(2)), code)
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) >= 4:
        year = int(digits[:4])
        return (year, year, code)
    return (0, 0, code)


def season_end_year(code: Optional[str]) -> Optional[int]:
    """Extrait l'année de fin d'un code saison."""
    if not code:
        return None
    match = _SEASON_CODE_RE.search(code)
    if match:
        return int(match.group(2))
    short_match = _SEASON_SHORT_CODE_RE.search(code)
    if short_match:
        start = 2000 + int(short_match.group(1))
        end = 2000 + int(short_match.group(2))
        return end + 100 if end < start else end
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) >= 4:
        return int(digits[:4])
    return None


__all__ = [
    "safe_int",
    "safe_float",
    "pct",
    "strip_accents",
    "normalize_text_upper",
    "normalize_numero",
    "parse_optional_int",
    "is_winner",
    "ROLE_LABELS",
    "role_label",
    "season_sort_key",
    "season_end_year",
]
