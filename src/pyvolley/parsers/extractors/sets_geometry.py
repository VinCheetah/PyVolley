"""
Module d'extraction géométrique pour les sets (Sets 1 à 5).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pyvolley.core.models import Set
from pyvolley.parsers.layout_config import ParserLayoutConfig, DEFAULT_FFVB_LAYOUT
from pyvolley.parsers.extractors.fast.utils import normalize_words
from pyvolley.parsers.extractors.fast.resultats import SetSummary, extract_fast_resultats
from pyvolley.parsers.extractors.fast.sets import extract_fast_sets


def extract_sets_geometry(
    words: List[Any],
    h_data: Optional[Dict[str, Any]] = None,
    gauche_est_equipe_a: bool = True,
    nom_a: str = "",
    nom_b: str = "",
    config: Optional[ParserLayoutConfig] = None,
) -> List[Set]:
    """
    Extrait et construit la liste complète des objets Set de façon déterministe.
    """
    active_config = config or DEFAULT_FFVB_LAYOUT
    sorted_words, y0_list = normalize_words(words)

    # Récupérer les scores de sets depuis h_data ou les ré-extraire rapidement
    sets_summary: Dict[int, SetSummary] = {}
    if h_data and isinstance(h_data.get("resultats"), dict):
        raw_sets = h_data["resultats"].get("sets", [])
        for s in raw_sets:
            if isinstance(s, dict) and "numero" in s:
                num = s["numero"]
                sets_summary[num] = SetSummary(
                    numero=num,
                    points_a=s.get("points_a") or s.get("score_a"),
                    points_b=s.get("points_b") or s.get("score_b"),
                    duree=s.get("duree"),
                )
    else:
        res_data = extract_fast_resultats(sorted_words, y0_list, active_config)
        sets_summary = res_data.sets_summary

    return extract_fast_sets(
        sorted_words,
        y0_list,
        active_config,
        gauche_est_equipe_a=gauche_est_equipe_a,
        sets_summary=sets_summary,
    )
