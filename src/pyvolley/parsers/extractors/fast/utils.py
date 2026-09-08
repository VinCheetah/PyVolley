"""
Utilitaires géométriques et spatiales ultra-rapides pour les extracteurs Fast.

Optimisé pour un traitement < 1ms sans allocations mémoire superflues.
"""

from __future__ import annotations

import bisect
import re
from datetime import date as datetime_date, time as datetime_time
from typing import Any, Dict, List, Optional, Tuple, Union

from pyvolley.parsers.constants import MOIS_MAP
from pyvolley.parsers.layout_config import LayoutRegion

# Type alias pour un mot normalisé (x0, y0, x1, y1, text)
WordTuple = Tuple[float, float, float, float, str]

# Regex pré-compilées pour performance maximale
RE_TIME = re.compile(r'(\d{1,2})[h:](\d{2})', re.IGNORECASE)
RE_DATE_FR = re.compile(r'(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})')
RE_DATE_NUM = re.compile(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})')
RE_SUB_SCORE = re.compile(r'(\d{1,2})[:\s\-\.h]+(\d{1,2})')
RE_DIGITS = re.compile(r'\b\d{1,2}\b')


def normalize_words(words: Union[List[dict], List[tuple], List[Any]]) -> Tuple[List[WordTuple], List[float]]:
    """
    Convertit et pré-trie les mots en liste de tuples (x0, y0, x1, y1, text)
    avec une liste d'index Y0 pour recherche dichotomique (bisect) ultra-rapide (< 0.1ms).
    """
    if not words:
        return [], []

    first = words[0]
    if isinstance(first, dict):
        word_tuples = [
            (
                float(w.get("x0", w.get("left", 0.0))),
                float(w.get("y0", w.get("top", 0.0))),
                float(w.get("x1", w.get("right", 0.0))),
                float(w.get("y1", w.get("bottom", 0.0))),
                str(w.get("text", "")).strip(),
            )
            for w in words
            if str(w.get("text", "")).strip()
        ]
    elif isinstance(first, (tuple, list)):
        word_tuples = [
            (
                float(w[0]),
                float(w[1]),
                float(w[2]),
                float(w[3]),
                str(w[4]).strip(),
            )
            for w in words
            if len(w) >= 5 and str(w[4]).strip()
        ]
    else:
        word_tuples = []

    # Tri spatial primaire par Y0 puis par X0
    word_tuples.sort(key=lambda w: (w[1], w[0]))
    y0_list = [w[1] for w in word_tuples]

    return word_tuples, y0_list


def slice_words_in_box(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> List[WordTuple]:
    """
    Extrait par bisect dichotomique les mots dont le centre (cx, cy) est dans la bounding box.
    """
    if not sorted_words:
        return []

    start_idx = bisect.bisect_left(y0_list, y0 - 5.0)
    end_idx = bisect.bisect_right(y0_list, y1 + 5.0)

    res: List[WordTuple] = []
    for w in sorted_words[start_idx:end_idx]:
        cx = (w[0] + w[2]) * 0.5
        cy = (w[1] + w[3]) * 0.5
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            res.append(w)
    return res


def slice_words_in_region(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    region: LayoutRegion,
) -> List[WordTuple]:
    """Shorthand pour découper les mots dans un LayoutRegion."""
    return slice_words_in_box(sorted_words, y0_list, region.x0, region.y0, region.x1, region.y1)


def extract_text_in_region(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    region: Optional[LayoutRegion],
) -> str:
    """Extrait et ordonne la chaîne textuelle d'une zone rectangulaire."""
    if region is None:
        return ""
    words = slice_words_in_region(sorted_words, y0_list, region)
    if not words:
        return ""

    # Regrouper et ordonner par ligne Y (tolérance 3.0pt) puis par X0
    sorted_w = sorted(words, key=lambda w: (round(w[1] / 3.0) * 3.0, w[0]))
    return " ".join(w[4] for w in sorted_w).strip()


def group_words_by_line(words: List[WordTuple], y_step: float = 3.0) -> Dict[float, List[WordTuple]]:
    """Regroupe les mots par ligne Y selon un seuil de pas y_step."""
    lines: Dict[float, List[WordTuple]] = {}
    for w in words:
        y_key = round(w[1] / y_step) * y_step
        lines.setdefault(y_key, []).append(w)
    return lines


def line_tokens(words_in_line: List[WordTuple]) -> List[str]:
    """Trie les mots horizontalement et retourne la liste des tokens texte."""
    words_sorted = sorted(words_in_line, key=lambda w: w[0])
    return [w[4] for w in words_sorted if w[4]]


def is_digit_token(token: str, min_len: int = 1, max_len: int = 8) -> bool:
    """Vérifie si un token est un entier numérique dans les limites de longueur."""
    return token.isdigit() and min_len <= len(token) <= max_len


def parse_name_parts(parts: List[str]) -> Tuple[str, str]:
    """Sépare une liste de parties de nom en (Nom, Prénom)."""
    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    if parts:
        return parts[0], "Inconnu"
    return "", ""


def parse_time_token(time_str: Optional[str]) -> Optional[datetime_time]:
    """Convertit une chaîne '14h00', '14:00' ou '09:30' en datetime_time."""
    if not time_str:
        return None
    m = RE_TIME.search(str(time_str))
    if m:
        try:
            h, mn = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return datetime_time(h, mn)
        except ValueError:
            return None
    return None


def parse_date_heure(date_str: str) -> Tuple[Optional[datetime_date], Optional[datetime_time]]:
    """Parse la date et l'heure depuis une chaîne brute d'en-tête."""
    if not date_str:
        return None, None

    parsed_date: Optional[datetime_date] = None
    parsed_time: Optional[datetime_time] = parse_time_token(date_str)

    # Date française textuelle (ex: "Dimanche 15 Décembre 2024" ou "05 Octobre 2025")
    m_fr = RE_DATE_FR.search(date_str)
    if m_fr:
        try:
            day = int(m_fr.group(1))
            month_str = m_fr.group(2).lower()
            year = int(m_fr.group(3))
            month = MOIS_MAP.get(month_str)
            if month:
                parsed_date = datetime_date(year, month, day)
        except ValueError:
            parsed_date = None

    if not parsed_date:
        # Date numérique (ex: "15/12/2024" ou "15-12-24")
        m_num = RE_DATE_NUM.search(date_str)
        if m_num:
            try:
                day = int(m_num.group(1))
                month = int(m_num.group(2))
                yr = int(m_num.group(3))
                if yr < 100:
                    yr += 2000
                parsed_date = datetime_date(yr, month, day)
            except ValueError:
                parsed_date = None

    return parsed_date, parsed_time
