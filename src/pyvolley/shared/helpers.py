"""
Helpers partagés entre les modules web et API.
"""

from typing import Optional


def is_winner(match, equipe) -> bool:
    """Détermine si l'équipe donnée a gagné le match."""
    if match.equipe_a_id == equipe.id:
        return match.sets_equipe_a > match.sets_equipe_b
    elif match.equipe_b_id == equipe.id:
        return match.sets_equipe_b > match.sets_equipe_a
    return False


def parse_optional_int(value: Optional[str]) -> Optional[int]:
    """Parse une valeur en int optionnel, retourne None si invalide."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None
