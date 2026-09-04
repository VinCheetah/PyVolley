"""
Helpers partagés entre les modules core, database, analysis, web et API.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Any


def is_winner(match, equipe) -> bool:
    """Détermine si l'équipe donnée a gagné le match."""
    if getattr(match, "equipe_a_id", None) == getattr(equipe, "id", None):
        return (match.sets_equipe_a or 0) > (match.sets_equipe_b or 0)
    elif getattr(match, "equipe_b_id", None) == getattr(equipe, "id", None):
        return (match.sets_equipe_b or 0) > (match.sets_equipe_a or 0)
    return False


def parse_optional_int(value: Optional[str | int]) -> Optional[int]:
    """Parse une valeur en int optionnel, retourne None si invalide."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    stripped = str(value).strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def safe_int(value: object, default: int = 0) -> int:
    """Convertit une valeur en int, retourne *default* en cas d'échec."""
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: object, default: float = 0.0) -> float:
    """Convertit une valeur en float, retourne *default* en cas d'échec."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def pct(part: float, whole: float) -> float:
    """Calcule un pourcentage (0.0 si *whole* ≤ 0)."""
    if whole <= 0:
        return 0.0
    return (part / whole) * 100.0


def strip_accents(value: str) -> str:
    """Supprime les accents d'une chaîne."""
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text_upper(value: str) -> str:
    """Supprime accents, normalise espaces et met en majuscules."""
    return re.sub(r"\s+", " ", strip_accents(value)).strip().upper()


def normalize_numero(numero: Optional[str | int]) -> str:
    """Normalise un numéro de maillot (supprime espaces et zéros superflus)."""
    raw = str(numero or "").strip()
    if not raw:
        return ""
    if raw.isdigit():
        return str(int(raw))
    return raw.lstrip("0") or raw
