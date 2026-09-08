"""
Module d'extraction géométrique pour les effectifs (Section 2 - Joueurs, Libéros, Officiels Équipe A & B).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pyvolley.core.models import Joueur, Officiel
from pyvolley.parsers.layout_config import ParserLayoutConfig, DEFAULT_FFVB_LAYOUT
from pyvolley.parsers.extractors.fast.utils import normalize_words
from pyvolley.parsers.extractors.fast.rosters import extract_single_team_roster


@dataclass
class RosterData:
    """Modèle de données pour les effectifs d'une équipe."""

    joueurs: List[Joueur] = field(default_factory=list)
    liberos: List[Joueur] = field(default_factory=list)
    officiels: List[Officiel] = field(default_factory=list)
    capitaine: Optional[str] = None
    sources: Dict[str, Tuple[float, float, float, float]] = field(default_factory=dict)


def extract_team_roster_geometry(
    words: List[Any],
    team_suffix: str = "gauche",
    config: Optional[ParserLayoutConfig] = None,
    drawings: Optional[List[dict]] = None,
    image_blocks: Optional[List[Tuple[float, float, float, float]]] = None,
) -> RosterData:
    """Extrait l'effectif des joueurs, libéros et officiels pour l'Équipe Gauche ou Droite."""
    active_config = config or DEFAULT_FFVB_LAYOUT
    sorted_words, y0_list = normalize_words(words)

    side = "gauche" if team_suffix in ("gauche", "a") else "droite"
    fast_roster = extract_single_team_roster(
        sorted_words, y0_list, active_config, side=side, captain_image_bboxes=image_blocks
    )

    return RosterData(
        joueurs=fast_roster.joueurs,
        liberos=fast_roster.liberos,
        officiels=fast_roster.officiels,
        capitaine=fast_roster.capitaine,
        sources={},
    )
