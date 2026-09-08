"""
Normalisation unifiée des catégories d'âge, genres et divisions pour le volleyball FFVB.

Fournit une source de vérité unique pour :
- La normalisation des catégories d'âge (M9 à Senior, Vétéran, Jeunes)
- La détection du genre (MASCULIN, FEMININ, MIXTE)
- L'extraction et le formatage des divisions (1, 2, 3...)
- Les calculs d'âge limite et de bornes d'année de naissance
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date as dt_date
from typing import Optional


# Catégories canoniques ordonnées
CANONICAL_CATEGORIES: tuple[str, ...] = (
    "M9",
    "M11",
    "M13",
    "M15",
    "M18",
    "M21",
    "SENIOR",
    "VETERAN",
    "JEUNES",
)

# Limites d'âge maximales pour chaque catégorie jeune
CATEGORY_AGE_LIMITS: dict[str, int] = {
    "M9": 9,
    "M11": 11,
    "M13": 13,
    "M15": 15,
    "M18": 18,
    "M21": 21,
}

_RE_SPACES = re.compile(r"\s+")
_RE_CATEGORY_M_OR_U = re.compile(r"\b(?:M|U)\s*([0-9]{1,2})\b", re.IGNORECASE)


def normalize_text_upper(value: Optional[str]) -> str:
    """Supprime les accents, normalise les espaces et met en majuscules."""
    if not value:
        return ""
    norm = unicodedata.normalize("NFD", value)
    without_accents = "".join(
        ch for ch in norm if unicodedata.category(ch) != "Mn"
    )
    return _RE_SPACES.sub(" ", without_accents).strip().upper()


def normalize_genre(value: Optional[str], as_short: bool = False) -> Optional[str]:
    """Détecte et normalise le genre d'une compétition ou équipe."""
    if not value:
        return None
    upper = normalize_text_upper(value)
    if any(x in upper for x in ("MASCULIN", "MASC", "HOMME")):
        return "M" if as_short else "MASCULIN"
    if any(x in upper for x in ("FEMININ", "FEM", "DAME")):
        return "F" if as_short else "FEMININ"
    if "MIXTE" in upper:
        return "MIXTE"
    # Vérification par mot isolé 'M' ou 'F'
    if re.search(r"\bM\b", upper):
        return "M" if as_short else "MASCULIN"
    if re.search(r"\bF\b", upper):
        return "F" if as_short else "FEMININ"
    return None


def normalize_categorie(value: Optional[str], default_to_senior: bool = False) -> Optional[str]:
    """Normalise une catégorie d'âge vers une des catégories canoniques FFVB.

    Mappe :
    - U18, CADET, CADETTE, M17, M18 → M18
    - U15, MINIME, M14, M15 → M15
    - U13, BENJAMIN, BENJAMINE, M12, M13 → M13
    - U11, POUSSIN, POUSSINE, M10, M11 → M11
    - U9, PUPILLE, M8, M9 → M9
    - U21, U20, ESPOIR, M20, M21 → M21
    - SENIOR → SENIOR
    - VETERAN → VETERAN
    - JEUNE, JEUNES → JEUNES
    - Compétitions adultes sans mention jeune → SENIOR
    """
    if not value:
        return "SENIOR" if default_to_senior else None

    upper = normalize_text_upper(value)

    if "SENIOR" in upper:
        return "SENIOR"
    if "VETERAN" in upper:
        return "VETERAN"

    # Recherche explicite de Mxx ou Uxx
    match = _RE_CATEGORY_M_OR_U.search(upper)
    if match:
        num = int(match.group(1))
        if num <= 9:
            return "M9"
        elif num <= 11:
            return "M11"
        elif num <= 13:
            return "M13"
        elif num <= 15:
            return "M15"
        elif num <= 18:
            return "M18"
        elif num <= 21:
            return "M21"
        return "SENIOR"

    # Mots-clés des anciennes appellations fédérales
    if any(w in upper for w in ("CADET", "CADETTE")):
        return "M18"
    if "MINIME" in upper:
        return "M15"
    if any(w in upper for w in ("BENJAMIN", "BENJAMINE")):
        return "M13"
    if any(w in upper for w in ("POUSSIN", "POUSSINE")):
        return "M11"
    if any(w in upper for w in ("PUPILLE", "BABY")):
        return "M9"
    if any(w in upper for w in ("ESPOIR", "JUNIOR")):
        return "M21"
    if "JEUNE" in upper:
        return "JEUNES"

    # Compétitions adultes / seniors (Régionale, Nationale, etc.) sans mot jeune
    if any(w in upper for w in (
        "REGIONAL", "REGIONALE", "NATIONALE", "NATIONAL", "ELITE",
        "PRENATIONALE", "PRENATIONAL", "PREREGIONALE", "PREREGIONAL",
        "DEPARTEMENTALE", "DEPARTEMENTAL", "PRO A", "PRO B", "LIGUE A", "LIGUE B",
    )):
        return "SENIOR"

    return "SENIOR" if default_to_senior else None


def is_youth_category(categorie: Optional[str]) -> bool:
    """Retourne True si la catégorie correspond à une catégorie jeune."""
    cat = normalize_categorie(categorie)
    return cat in {"M9", "M11", "M13", "M15", "M18", "M21", "JEUNES"}


def category_age_limit(categorie: Optional[str]) -> Optional[int]:
    """Retourne la limite d'âge en années pour une catégorie jeune, ou None."""
    cat = normalize_categorie(categorie)
    return CATEGORY_AGE_LIMITS.get(cat or "")


def extract_division_number(text: Optional[str]) -> Optional[str]:
    """Extrait un numéro de division canonique (ex: '1', '2', '3') depuis un texte.

    Exemples :
    - 'REGIONALE 1' → '1'
    - 'R1M' → '1'
    - 'NATIONALE 2' → '2'
    - 'NM2' → '2'
    - 'D1F' → '1'
    - 'DEPARTEMENTALE 3' → '3'
    """
    if not text:
        return None
    upper = normalize_text_upper(text)

    # 1. Après le mot du niveau : 'NATIONALE 2', 'REGIONALE 1', 'DEPARTEMENTALE 3'
    pattern_level_num = re.search(
        r"\b(?:NATIONAL(?:E|AUX|ES?)?|R[EÉ]GIONAL(?:E|AUX|ES?)?|D[EÉ]PARTEMENTAL(?:E|AUX|ES?)?|PR[EÉ]NATIONAL(?:E|AUX|ES?)?|PR[EÉ]R[EÉ]GIONAL(?:E|AUX|ES?)?)\s+([1-4])\b",
        upper,
    )
    if pattern_level_num:
        return pattern_level_num.group(1)

    # 2. Format condensé de division : 'R1', 'R2', 'N1', 'N2', 'N3', 'D1', 'D2', 'D3', 'D4'
    pattern_code = re.search(r"\b[RND]([1-4])\b", upper)
    if pattern_code:
        return pattern_code.group(1)

    # 3. Format de code poule avec chiffre : '2FA', '3MA', 'R1M', 'D2F'
    pattern_prefix = re.match(r"^[A-Z]?([1-4])[MF]", upper)
    if pattern_prefix:
        return pattern_prefix.group(1)

    # 4. Chiffre isolé en fin de nom : 'CHAMPIONNAT REGIONAL M15 MASCULINS 2' → '2'
    pattern_end_digit = re.search(r"\b([1-4])\s*$", upper)
    if pattern_end_digit:
        return pattern_end_digit.group(1)

    return None


def estimate_birth_year_min(
    category_label: Optional[str],
    season_end_year: int,
) -> Optional[int]:
    """Calcule l'année de naissance minimale estimée pour une catégorie jeune.

    Pour une saison se terminant en 2025 et une catégorie M18 :
    2025 - 18 = 2007 (les joueurs sont nés au plus tôt en 2007).
    """
    limit = category_age_limit(category_label)
    if limit is None:
        return None
    return season_end_year - limit


def compute_max_age(birth_year_min: Optional[int], reference_year: Optional[int] = None) -> Optional[int]:
    """Calcule l'âge maximal estimé aujourd'hui d'après l'année de naissance minimale."""
    if birth_year_min is None:
        return None
    ref_year = reference_year or dt_date.today().year
    return max(0, ref_year - birth_year_min)
