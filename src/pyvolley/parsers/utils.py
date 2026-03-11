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


# ── Normalisation des noms de clubs ──


_VB_VARIANTS_PATTERN = re.compile(
    r'\bVOLLEY[\s-]*BALL\b',
    re.IGNORECASE,
)

_TEAM_NUMBER_PATTERN = re.compile(
    r'^(.+?)\s+(0?[1-9]|[1-9]\d?)$',
)


def normalize_club_name(name: str) -> str:
    """Normalise un nom de club.

    - Remplace les variantes « volley-ball », « volley ball » par « VB »
    - Remplace « V.B. » par « VB »
    - Normalise les espaces

    >>> normalize_club_name("SURESNES VOLLEY-BALL CLUB")
    'SURESNES VB CLUB'
    >>> normalize_club_name("US LOGNES VOLLEY-BALL")
    'US LOGNES VB'
    >>> normalize_club_name("AMICALE VILLENEUVE LA GARENNE V.B.")
    'AMICALE VILLENEUVE LA GARENNE VB'
    """
    if not name:
        return name
    # volley-ball / volley ball → VB
    name = _VB_VARIANTS_PATTERN.sub('VB', name)
    # V.B. → VB (handle with or without trailing period)
    name = re.sub(r'\bV\.B\.?(?:\b|\s|$)', 'VB', name)
    # Espaces multiples
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_club_info(team_name: str) -> tuple[str, Optional[int]]:
    """Extrait le nom du club et le numéro d'équipe.

    Gère les numéros avec ou sans zéro initial.

    ``"PARIS UC 2"``  → ``("PARIS UC", 2)``
    ``"PARIS UC 02"`` → ``("PARIS UC", 2)``
    ``"PARIS UC 1"``  → ``("PARIS UC", 1)``
    ``"AS CANNES VB"`` → ``("AS CANNES VB", None)``
    ``"ASNIERES VOLLEY 92"`` → ``("ASNIERES VOLLEY 92", None)``
    ``"VB14"`` → ``("VB14", None)``

    Le numéro d'équipe est détecté uniquement si :
    - C'est un petit nombre (1-9)
    - Le reste du nom fait au moins 3 caractères
    - Les numéros à 2 chiffres (10+) sont considérés comme des codes
      départementaux (ex: « VOLLEY 92 », « VOLLEY 13 »)
    """
    if not team_name:
        return team_name, None
    name = team_name.strip()

    m = _TEAM_NUMBER_PATTERN.match(name)
    if m:
        club_part = m.group(1).strip()
        num_str = m.group(2)
        num = int(num_str)

        # Seuls les petits numéros (1-9) sont des numéros d'équipe
        # Les numéros >= 10 sont probablement des codes départementaux
        if num <= 9 and len(club_part) >= 3:
            normalized = normalize_club_name(club_part)
            return normalized, num

    # Pas de numéro d'équipe détecté
    normalized = normalize_club_name(name)
    return normalized, None


def extract_competition_code(code_match: str) -> Optional[str]:
    """Extrait le code poule depuis le code match.

    Le suffixe numérique est toujours composé de 3 chiffres.
    On ne peut PAS utiliser un quantificateur lazy car les codes
    peuvent contenir des chiffres (ex. ``"CX1001"`` → ``"CX1"``).

    ``"EMA001"`` → ``"EMA"``
    ``"PMAA001"`` → ``"PMAA"``
    ``"CX1001"`` → ``"CX1"``
    ``"BG5006"`` → ``"BG5"``
    """
    if not code_match or code_match == "UNKNOWN":
        return None
    m = re.match(r'^(.+?)(\d{3})$', code_match)
    return m.group(1) if m else None


# ── Détection du niveau de compétition ──


# Mots-clés ordonnés par priorité : les plus spécifiques d'abord
_NIVEAU_KEYWORDS: list[tuple[str, str]] = [
    # ELITE
    (r'\bELITE\b', 'ELITE'),
    (r'\bPRO\s*[AB]?\b', 'ELITE'),
    (r'\bLAM\b', 'ELITE'),          # Ligue A Masculine
    (r'\bLAF\b', 'ELITE'),          # Ligue A Féminine
    (r'\bLBM\b', 'ELITE'),          # Ligue B
    (r'\bLBF\b', 'ELITE'),
    # PRE-NATIONALE (doit être avant NATIONALE pour éviter un match partiel)
    (r'\bPR[EÉ][\s-]*NATIONAL', 'PRE_NATIONALE'),
    (r'\bACCESSION\s+R[EÉ]GIONALE\b', 'PRE_NATIONALE'),
    # NATIONALE
    (r'\bNATIONALE?\s*[1-4]?\b', 'NATIONALE'),
    (r'\bNATIONAL\b', 'NATIONALE'),
    (r'\bCOUPE\s+DE\s+FRANCE\b', 'NATIONALE'),
    # REGIONALE
    (r'\bR[EÉ]GIONALE?\s*[1-4]?\b', 'REGIONALE'),
    (r'\bCHAMPIONNAT\s+R[EÉ]GIONAL', 'REGIONALE'),
    (r'\bTOURNOI\s+R[EÉ]GIONAL', 'REGIONALE'),
    # DEPARTEMENTALE
    (r'\bD[EÉ]PARTEMENTAL', 'DEPARTEMENTALE'),
    # LOISIR
    (r'\bLOISIRS?\b', 'LOISIR'),
    (r'\bBRASSAGES?\b', 'LOISIR'),
    (r'\bCOMPET\s*FUN\b', 'LOISIR'),
    (r'\bCOMPET\s*MOUV\b', 'LOISIR'),
]

# Compiled patterns
_NIVEAU_PATTERNS = [
    (re.compile(pat, re.IGNORECASE), niveau)
    for pat, niveau in _NIVEAU_KEYWORDS
]


def detect_niveau(competition: Optional[str], organisation: Optional[str] = None) -> Optional[str]:
    """Détecte le niveau de compétition depuis le nom de la compétition.

    Analyse le nom de la compétition et/ou l'organisateur pour
    déterminer le niveau (ELITE, NATIONALE, PRE_NATIONALE, REGIONALE,
    DEPARTEMENTALE, LOISIR).

    >>> detect_niveau("EMA - ELITE MASCULINE - POULE A")
    'ELITE'
    >>> detect_niveau("2FA - NATIONALE 2 FEMININE - POULE A")
    'NATIONALE'
    >>> detect_niveau("PFA - CHAMPIONNAT PRE-NATIONAL SENIOR FEMININ : POULE A")
    'PRE_NATIONALE'
    >>> detect_niveau("1FA - CHAMPIONNAT REGIONAL 1 SENIOR FEMININ : POULE A")
    'REGIONALE'
    >>> detect_niveau("AFA - ACCESSION REGIONALE SENIOR FEM POULE A")
    'PRE_NATIONALE'
    >>> detect_niveau("LAR - LOISIR MIXTE ARGENT")
    'LOISIR'
    >>> detect_niveau("18F - M18F 6x6 75", "Comité Seine Paris")
    'DEPARTEMENTALE'
    """
    # Chercher dans le nom de compétition d'abord
    text = competition or ''
    for pattern, niveau in _NIVEAU_PATTERNS:
        if pattern.search(text):
            return niveau

    # Fallback : déduire du type d'organisateur
    if organisation:
        org_upper = organisation.upper()
        if 'NATIONALES' in org_upper or 'NATIONALE' in org_upper:
            return 'NATIONALE'
        if 'LIGUE' in org_upper:
            return 'REGIONALE'
        if 'COMITÉ' in org_upper or 'COMITE' in org_upper:
            return 'DEPARTEMENTALE'

    return None


# ── Extraction de l'organisateur ──


_ORGANISATEUR_PATTERNS = [
    # Compétitions Nationales (avec ou sans SENIORS/JEUNES)
    re.compile(
        r'^(Compétitions?\s+Nationales?(?:\s+(?:SENIORS?|JEUNES?))?)',
        re.IGNORECASE,
    ),
    # Comité + nom (ex: "Comité Seine Paris", "Comité des Hauts-de-Seine",
    # "Comité Nord", "Comité du Rhône Métropole de Lyon")
    # On arrête quand on trouve un mot entièrement en majuscules de 2+ lettres
    # SAUF si c'est un mot de liaison comme "de", "du", "des"
    re.compile(
        r'^(Comit[eé]\s+(?:de\s+(?:la\s+)?|des\s+|du\s+)?[\w\s\'\-]+?)\s+(?=[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]{2,}[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ\s]*\b)',
        re.UNICODE,
    ),
]

# Régions françaises connues pour les Ligues
_LIGUE_REGIONS = [
    'ILE-DE-FRANCE',
    'HAUTS-DE-FRANCE',
    'AUVERGNE-RHÔNE-ALPES',
    'AUVERGNE-RHONE-ALPES',
    'NOUVELLE AQUITAINE',
    'NOUVELLE-AQUITAINE',
    'OCCITANIE',
    'GRAND EST',
    'GRAND-EST',
    'BRETAGNE',
    'NORMANDIE',
    'PAYS DE LA LOIRE',
    'PAYS-DE-LA-LOIRE',
    'CENTRE-VAL DE LOIRE',
    'CENTRE VAL DE LOIRE',
    'BOURGOGNE-FRANCHE-COMTÉ',
    'BOURGOGNE-FRANCHE-COMTE',
    'BOURGOGNE FRANCHE-COMTÉ',
    "PROVENCE-ALPES-CÔTE D'AZUR",
    "PROVENCE-ALPES-COTE D'AZUR",
    'PACA',
    'CORSE',
    'GUADELOUPE',
    'MARTINIQUE',
    'GUYANE',
    'RÉUNION',
    'REUNION',
    'MAYOTTE',
    'SUD',
    'NORD',
]

# Construire un pattern pour matcher "Ligue <REGION>"
_LIGUE_REGION_PATTERN = re.compile(
    r'^(Ligue\s+(?:' + '|'.join(re.escape(r) for r in sorted(_LIGUE_REGIONS, key=len, reverse=True)) + r'))\b',
    re.IGNORECASE,
)


def extract_organisateur(line: str) -> Optional[str]:
    """Extrait le nom de l'organisateur depuis la ligne [3] du header.

    >>> extract_organisateur("Compétitions Nationales SENIORS GRENOBLE V.UNIVERSITE CLUB")
    'Compétitions Nationales SENIORS'
    >>> extract_organisateur("Comité Seine Paris SCUF2 SCNP2")
    'Comité Seine Paris'
    >>> extract_organisateur("Comité des Hauts-de-Seine ACBB 3 ANTONY VOLLEY 3")
    'Comité des Hauts-de-Seine'
    >>> extract_organisateur("Ligue ILE-DE-FRANCE JEANNE D ARC DE ROSNY US LOGNES")
    'Ligue ILE-DE-FRANCE'
    >>> extract_organisateur("Comité du Rhône Métropole de Lyon CISGO 1 CRAPONNE")
    'Comité du Rhône Métropole de Lyon'
    >>> extract_organisateur("Ligue AUVERGNE-RHÔNE-ALPES VB VILLEFRANCHE VC MEXIMIEUX")
    'Ligue AUVERGNE-RHÔNE-ALPES'
    """
    if not line:
        return None
    line = line.strip()

    for pattern in _ORGANISATEUR_PATTERNS:
        m = pattern.match(line)
        if m:
            return m.group(1).strip()

    # Pattern spécial pour les Ligues (utilise la liste connue des régions)
    m = _LIGUE_REGION_PATTERN.match(line)
    if m:
        return m.group(1).strip()

    # Fallback simplifié
    if line.lower().startswith('compétitions') or line.lower().startswith('competitions'):
        parts = line.split()
        # "Compétitions Nationales" + optionally "SENIORS" or "JEUNES"
        end = 2
        if len(parts) > 2 and parts[2].upper() in ('SENIORS', 'JEUNES'):
            end = 3
        return ' '.join(parts[:end])

    if line.lower().startswith('comité') or line.lower().startswith('comite'):
        # Prendre jusqu'au premier mot entièrement majuscule de 2+ chars
        # qui n'est pas un petit mot (de, du, des, la, le)
        parts = line.split()
        small_words = {'de', 'du', 'des', 'la', 'le', 'les', "l'", 'et'}
        end = 1
        for i, p in enumerate(parts[1:], 1):
            if (p.lower() in small_words
                    or not p.isupper()
                    or len(p) < 2
                    or '-' in p):
                end = i + 1
            else:
                break
        return ' '.join(parts[:end])

    if line.lower().startswith('ligue'):
        parts = line.split()
        end = 1
        for i, p in enumerate(parts[1:], 1):
            if '-' in p or p.isupper():
                end = i + 1
            else:
                break
        return ' '.join(parts[:end])

    return None


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
