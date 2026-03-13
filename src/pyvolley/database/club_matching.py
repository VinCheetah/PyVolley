"""
Utilitaires partagés pour le matching de noms de clubs.

Ce module centralise la normalisation et la comparaison de noms de clubs
utilisées par les deux services d'import (Phase 1 CSV et Phase 2 PDF).
"""

import re
import unicodedata


def normalize_club_name(name: str) -> str:
    """Normalise un nom de club pour le matching.

    - Majuscules
    - Supprime les accents
    - Remplace ponctuation par espaces
    - Supprime les numéros d'équipe en fin de nom (ex: " 2", " 3")
    - Normalise SAINT/ST, SAINTE/STE
    - Coalescence d'espaces
    """
    n = name.upper().strip()
    # Supprimer les accents
    n = ''.join(
        c for c in unicodedata.normalize('NFD', n)
        if unicodedata.category(c) != 'Mn'
    )
    # Ponctuation → espaces
    n = re.sub(r'[.\-/\'\",;:()]+', ' ', n)
    # Supprimer numéro d'équipe final (chiffre isolé en fin)
    n = re.sub(r'\s+\d$', '', n.strip())
    # Normaliser SAINT-/SAINTE-
    n = re.sub(r'\bSAINTE?\b', 'ST', n)
    n = re.sub(r'\bSTE\b', 'ST', n)
    # Coalescence espaces
    n = re.sub(r'\s+', ' ', n)
    return n.strip()


def extract_club_core_name(name: str) -> str:
    """Extrait le nom-noyau d'un club en supprimant les suffixes de volley courants.

    Utilisé pour le matching souple entre variantes d'un même club.

    Exemples :
        'LYON PESD VB'       → 'LYON PESD'
        'LYON PESD VOLLEY'   → 'LYON PESD'
        'VBC CHAMALIERES'    → 'VBC CHAMALIERES'  (préfixe, pas suffixe)
        'ASUL LYON VB'       → 'ASUL LYON'
        'E. FOREZIENNE VB'   → 'E FOREZIENNE'
        'TOUVET VOLLEY-BALL' → 'TOUVET'
    """
    n = normalize_club_name(name)
    # Supprimer les suffixes de volley courants en fin de nom
    # Ordonnés du plus long au plus court pour matcher "VOLLEY BALL" avant "VOLLEY"
    volleyball_suffixes = [
        r'\s+VOLLEY\s*BALL$',
        r'\s+VOLLEYBALL$',
        r'\s+VOLLEY$',
        r'\s+VB$',
        r'\s+AVB$',
        r'\s+VBC$',
        r'\s+VC$',
    ]
    for suffix in volleyball_suffixes:
        n = re.sub(suffix, '', n)
    return n.strip()


def levenshtein(s1: str, s2: str) -> int:
    """Distance de Levenshtein entre deux chaînes."""
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if not s2:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr_row.append(min(
                curr_row[j] + 1,       # insertion
                prev_row[j + 1] + 1,   # deletion
                prev_row[j] + cost,    # substitution
            ))
        prev_row = curr_row
    return prev_row[-1]


def club_names_match(name_a: str, name_b: str) -> bool:
    """Détermine si deux noms de clubs désignent probablement le même club.

    Règles de matching :
    1. Noms normalisés identiques → True
    2. Noms-noyaux identiques → True (gère 'LYON VB' vs 'LYON VOLLEY')
    3. L'un est préfixe de l'autre (≥ 5 chars) → True (gère 'AS CALUIRE' vs 'AS CALUIRE VB')
    4. Variantes d'orthographe proches → True (Levenshtein ≤ 2 pour les noms courts)
    """
    na = normalize_club_name(name_a)
    nb = normalize_club_name(name_b)

    # 1. Noms normalisés identiques
    if na == nb:
        return True

    # 2. Noms-noyaux identiques
    core_a = extract_club_core_name(name_a)
    core_b = extract_club_core_name(name_b)
    if core_a == core_b and len(core_a) >= 4:
        return True

    # 3. L'un est préfixe de l'autre (pour les cas avec/sans suffixe VB)
    if len(na) >= 5 and len(nb) >= 5:
        if na.startswith(nb) or nb.startswith(na):
            # Vérifier que le suffixe est un mot de volley courant
            longer, shorter = (na, nb) if len(na) > len(nb) else (nb, na)
            suffix = longer[len(shorter):].strip()
            if not suffix or re.match(
                r'^(VB|VBC|VC|AVB|VOLLEY|VOLLEYBALL|VOLLEY\s*BALL)$', suffix
            ):
                return True

    # 4. Distance d'édition pour les variantes orthographiques proches
    if abs(len(core_a) - len(core_b)) <= 2 and len(core_a) >= 6:
        dist = levenshtein(core_a, core_b)
        if dist <= 2:
            return True

    return False
