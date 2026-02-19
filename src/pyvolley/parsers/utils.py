"""
Utilitaires de traitement de texte pour le parsing des feuilles de match.

Fonctions pures et statiques, réutilisables par tous les extracteurs.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional


def split_nom_prenom(nom_prenom: str) -> tuple[str, str]:
    """Sépare nom et prénom.

    Heuristique : dans les PDFs FFVB, tout est en majuscules.
    Le dernier mot est considéré comme le prénom.

    >>> split_nom_prenom("HUMBERT RIDET DYLAN")
    ('HUMBERT RIDET', 'DYLAN')
    >>> split_nom_prenom("THE OWONA IVAN")
    ('THE OWONA', 'IVAN')
    """
    parts = nom_prenom.split()
    if len(parts) <= 1:
        return nom_prenom, "Inconnu"
    return ' '.join(parts[:-1]), parts[-1]


def normalize_name(name: str) -> str:
    """Corrige les artefacts d'extraction PDF sur les noms.

    Certains vieux PDFs insèrent un espace après la 1ère lettre :
    ``'M AROMME CANTELEU'`` → ``'MAROMME CANTELEU'``

    Ne joint PAS si le 2ème token est aussi une seule lettre (acronyme).
    """
    name = name.strip()
    name = re.sub(
        r'^([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ])\s+(?=[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]{2,})',
        r'\1', name,
    )
    return re.sub(r'\s+', ' ', name).strip()


def clean_team_name(name: str) -> str:
    """Nettoie un nom d'équipe (espaces multiples, lettre isolée en fin)."""
    name = re.sub(r'\s+', ' ', name).strip()
    # Lettre isolée en fin = troncature PDF
    name = re.sub(r'\s+[A-Z]$', '', name)
    return name.strip()


def extract_club_info(team_name: str) -> tuple[str, Optional[int]]:
    """Extrait le nom du club et le numéro d'équipe.

    ``"PARIS UC 2"`` → ``("PARIS UC", 2)``
    ``"AS CANNES VB"`` → ``("AS CANNES VB", None)``
    """
    if not team_name:
        return team_name, None
    name = team_name.strip()
    m = re.match(r'^(.+?)\s+(\d)$', name)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return name, None


def extract_competition_code(code_match: str) -> Optional[str]:
    """Extrait le code poule depuis le code match.

    ``"EMA001"`` → ``"EMA"``
    ``"PMAA001"`` → ``"PMAA"``
    """
    if not code_match or code_match == "UNKNOWN":
        return None
    m = re.match(r'^([A-Za-z0-9]+?)(\d{2,})$', code_match)
    return m.group(1) if m else None


def team_similarity(name_a: str, name_b: str) -> float:
    """Similarité normalisée entre deux noms d'équipe (0.0–1.0)."""
    a = normalize_name(name_a).upper()
    b = normalize_name(name_b).upper()
    if not a or not b:
        return 0.0

    # Inclusion directe
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))

    # Score mot-à-mot
    wa = set(a.split())
    wb = set(b.split())
    common = wa & wb
    if common:
        word_score = len(common) / max(len(wa), len(wb))
        if word_score > 0.5:
            return word_score

    return SequenceMatcher(None, a, b).ratio()


def team_matches(name_a: str, name_b: str, threshold: float = 0.55) -> bool:
    """True si les deux noms d'équipe se correspondent (matching flou)."""
    a = normalize_name(name_a).upper()
    b = normalize_name(name_b).upper()
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    return team_similarity(a, b) >= threshold


def best_team_match(
    vainqueur: str, nom_a: str, nom_b: str,
) -> Optional[str]:
    """Détermine si le vainqueur correspond à l'équipe A ou B.

    Returns 'A', 'B' ou None.
    """
    v = normalize_name(vainqueur).upper()
    a = normalize_name(nom_a).upper()
    b = normalize_name(nom_b).upper()
    if not v:
        return None

    sim_a = team_similarity(v, a)
    sim_b = team_similarity(v, b)

    if sim_a > sim_b and sim_a >= 0.4:
        return 'A'
    if sim_b > sim_a and sim_b >= 0.4:
        return 'B'

    if v in a:
        return 'A'
    if v in b:
        return 'B'

    return None


def parse_time_str(val: Optional[str]) -> Optional['dt_time']:
    """Convertit ``'14:30'`` ou ``'14h30'`` en ``datetime.time``."""
    from datetime import time as dt_time
    if not val:
        return None
    m = re.match(r'^(\d{1,2})[:hH](\d{2})$', val.strip())
    if not m:
        return None
    try:
        return dt_time(int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def try_enum(enum_cls, val):
    """Tente de convertir une valeur en membre d'un Enum."""
    if not val:
        return None
    try:
        return enum_cls(val)
    except (ValueError, KeyError):
        return None


def saison_year(saison: Optional[str]) -> Optional[int]:
    """``'2024-2025'`` → ``2024``."""
    if not saison:
        return None
    try:
        return int(saison.split("-")[0])
    except (ValueError, IndexError):
        return None
