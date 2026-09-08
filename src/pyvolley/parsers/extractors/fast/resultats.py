"""
Module d'extraction direct et ultra-rapide des résultats et remarques du match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pyvolley.parsers.layout_config import ParserLayoutConfig
from pyvolley.parsers.extractors.fast.utils import (
    RE_DIGITS,
    RE_SUB_SCORE,
    RE_TIME,
    WordTuple,
    extract_text_in_region,
    group_words_by_line,
    line_tokens,
    slice_words_in_region,
)


@dataclass
class SetSummary:
    """Récapitulatif des points et de la durée d'un set depuis le tableau des résultats."""

    numero: int
    points_a: Optional[int] = None
    points_b: Optional[int] = None
    duree: Optional[str] = None


@dataclass
class FastResultsData:
    """Données complètes extraites de la zone des résultats et remarques."""

    vainqueur: Optional[str] = None
    score_final: Optional[str] = None
    duree_totale: Optional[str] = None
    heure_debut: Optional[str] = None
    heure_fin: Optional[str] = None
    remarques: Optional[str] = None
    sets_summary: Dict[int, SetSummary] = field(default_factory=dict)
    raw_text: str = ""


def _is_duration_token(token: str) -> bool:
    t = token.strip().lower()
    if t.endswith("min") and t[:-3].strip().isdigit():
        return True
    if t.endswith("'") and t[:-1].strip().isdigit():
        return True
    if "h" in t:
        parts = t.split("h", 1)
        return parts[0].isdigit() and parts[1].isdigit()
    return False


def extract_fast_resultats(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    config: ParserLayoutConfig,
) -> FastResultsData:
    """
    Extrait le vainqueur, score final, durée totale et récapitulatif des sets depuis la zone de résultats.
    """
    res = FastResultsData()
    bboxes = config.bboxes

    # 1. Remarques / Observations
    rem_reg = bboxes.get("remarques")
    if rem_reg:
        rem_text = extract_text_in_region(sorted_words, y0_list, rem_reg)
        if rem_text and rem_text not in ("-", "NEANT", "NÉANT", "RAS", "R.A.S."):
            res.remarques = rem_text

    # 2. Résultats
    res_reg = bboxes.get("resultats")
    if not res_reg:
        return res

    res_words = slice_words_in_region(sorted_words, y0_list, res_reg)
    if not res_words:
        return res

    res.raw_text = extract_text_in_region(sorted_words, y0_list, res_reg)
    lines_res = group_words_by_line(res_words, y_step=3.0)

    for y_key in sorted(lines_res.keys()):
        words_in_line = sorted(lines_res[y_key], key=lambda w: w[0])
        tokens = [w[4] for w in words_in_line if w[4]]
        if not tokens:
            continue

        line_upper = " ".join(tokens).upper()

        # Détection du Vainqueur
        if "VAINQUEUR" in line_upper:
            capture = False
            winner_parts: List[str] = []
            for t in tokens:
                t_clean = t.rstrip(":")
                if t_clean.upper() == "VAINQUEUR":
                    capture = True
                    continue
                if capture:
                    if "/" in t:
                        parts = t.split("/", 1)
                        if parts[0].isdigit() and parts[1].isdigit():
                            res.score_final = t
                            break
                    winner_parts.append(t)
            if winner_parts:
                res.vainqueur = " ".join(winner_parts).strip() or None
            continue

        # Détection des heures début/fin et durée globale du match
        if len(tokens) <= 4:
            times = [t for t in tokens if RE_TIME.search(t)]
            if times and not res.heure_debut:
                res.heure_debut = times[0]
            if len(times) >= 2 and not res.heure_fin:
                res.heure_fin = times[1]
            if not res.duree_totale:
                dur = next((t for t in tokens if _is_duration_token(t)), None)
                if dur:
                    res.duree_totale = dur

        # Extraction des lignes de sets (1 à 5)
        # Tableau FFVB récapitulatif :
        # - Points Équipe A : 458.0 <= x0 <= 472.0
        # - Numéro du Set (1..5) : 478.0 <= x0 <= 486.0
        # - Durée du Set : 494.0 <= x0 <= 512.0
        # - Points Équipe B : 514.0 <= x0 <= 528.0
        num_w = next((w for w in words_in_line if 476.0 <= w[0] <= 488.0 and w[4].isdigit()), None)
        if num_w:
            try:
                s_num = int(num_w[4])
                if 1 <= s_num <= 5:
                    pt_a_w = next((w for w in words_in_line if 458.0 <= w[0] <= 473.0 and w[4].isdigit()), None)
                    pt_b_w = next((w for w in words_in_line if 514.0 <= w[0] <= 529.0 and w[4].isdigit()), None)
                    dur_w = next((w for w in words_in_line if 492.0 <= w[0] <= 512.0), None)

                    pt_a = int(pt_a_w[4]) if pt_a_w else None
                    pt_b = int(pt_b_w[4]) if pt_b_w else None
                    dur_str = dur_w[4] if dur_w else None

                    res.sets_summary[s_num] = SetSummary(
                        numero=s_num,
                        points_a=pt_a,
                        points_b=pt_b,
                        duree=dur_str,
                    )
            except Exception:
                pass

    return res
