"""Utilities to derive a robust match status from partial data."""

from __future__ import annotations

from typing import Any, Iterable, Optional


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        try:
            return int(text)
        except ValueError:
            return None
    return None


def normalize_score_sets(
    score_sets: Optional[str],
    *,
    replace_forfeit_with_zero: bool = False,
) -> Optional[str]:
    """Normalize a set score string to "A/B" format.

    Accepted inputs:
    - "3/1", "3-1", "3 - 1"
    - "P/3", "P-3", "P - 3"
    - "3/P", "3-P", "3 - P"
    - "P/P", "P-P", "P - P"
    """
    if not score_sets:
        return None

    raw = score_sets.strip().upper().replace("-", "/")
    if "/" not in raw:
        return None

    left_raw, right_raw = raw.split("/", 1)
    left = left_raw.strip()
    right = right_raw.strip()
    if not left or not right:
        return None

    valid = {"P"}
    if not (left.isdigit() or left in valid):
        return None
    if not (right.isdigit() or right in valid):
        return None

    if replace_forfeit_with_zero:
        if left == "P":
            left = "0"
        if right == "P":
            right = "0"

    return f"{left}/{right}"


def detect_forfeit_type(score_sets: Optional[str]) -> Optional[str]:
    """Détecte le type de forfait à partir de la chaîne de score sets.

    Returns:
        "double" si P/P ou double forfait
        "equipe_a" si forfait équipe A (P/3, P/0, etc.)
        "equipe_b" si forfait équipe B (3/P, 0/P, etc.)
        None si aucun forfait détecté
    """
    if not score_sets:
        return None
    raw = score_sets.strip().upper().replace("-", "/")
    if "/" not in raw:
        return None
    parts = raw.split("/", 1)
    left, right = parts[0].strip(), parts[1].strip()
    if left == "P" and right == "P":
        return "double"
    if left == "P":
        return "equipe_a"
    if right == "P":
        return "equipe_b"
    return None


def score_sets_indicates_played(score_sets: Optional[str]) -> bool:
    """Return True if the score string indicates a played or forfeited match."""
    canonical = normalize_score_sets(score_sets)
    if not canonical:
        return False

    left, right = canonical.split("/", 1)
    if left == "P" or right == "P":
        return True

    if left.isdigit() and right.isdigit():
        return (int(left) + int(right)) > 0

    return False


def _extract_set_points(item: Any) -> tuple[Optional[int], Optional[int]]:
    if item is None:
        return None, None

    if isinstance(item, tuple) and len(item) >= 2:
        return _to_int(item[0]), _to_int(item[1])

    if isinstance(item, dict):
        score_a = item.get("score_a", item.get("points_a"))
        score_b = item.get("score_b", item.get("points_b"))
        return _to_int(score_a), _to_int(score_b)

    return _to_int(getattr(item, "score_a", None)), _to_int(getattr(item, "score_b", None))


def sets_indicate_played(sets: Optional[Iterable[Any]]) -> bool:
    """Return True when at least one set contains a non-zero score."""
    if not sets:
        return False

    for set_item in sets:
        score_a, score_b = _extract_set_points(set_item)
        if score_a is None and score_b is None:
            continue
        if (score_a or 0) + (score_b or 0) > 0:
            return True

    return False


def compute_match_played(
    *,
    vainqueur: Optional[str] = None,
    score_sets: Optional[str] = None,
    sets: Optional[Iterable[Any]] = None,
    sets_a: Optional[int] = None,
    sets_b: Optional[int] = None,
    forfait: bool = False,
    has_set_scores: bool = False,
    declared_played: Optional[bool] = None,
    trust_declared: bool = False,
) -> bool:
    """Compute a robust played flag from all available evidence."""
    if forfait:
        return True
    if has_set_scores:
        return True

    if vainqueur and str(vainqueur).strip():
        return True

    if score_sets_indicates_played(score_sets):
        return True

    if (sets_a or 0) + (sets_b or 0) > 0:
        return True

    if sets_indicate_played(sets):
        return True

    if trust_declared and declared_played is not None:
        return bool(declared_played)

    return False
