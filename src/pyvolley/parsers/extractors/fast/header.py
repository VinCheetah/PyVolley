"""
Module d'extraction direct et ultra-rapide pour l'en-tête (Header) de la feuille de match FFVB.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as datetime_date, time as datetime_time
from typing import Any, Dict, List, Optional, Tuple

from pyvolley.core.models import Categorie, Genre, Niveau
from pyvolley.parsers.layout_config import ParserLayoutConfig
from pyvolley.parsers.utils import detect_niveau, try_enum
from pyvolley.parsers.extractors.fast.utils import (
    WordTuple,
    extract_text_in_region,
    parse_date_heure,
    slice_words_in_box,
)
from pyvolley.shared.categorisation import (
    normalize_genre,
    normalize_categorie,
    extract_division_number,
)
from pyvolley.shared.niveau import classify_level

MD5_ICON_A = "02ef4187ffc068afb86d0e896c92a6f6"
MD5_ICON_B = "a86a6115ce7f42ec4286e37e69883aa6"


@dataclass
class HeaderData:
    """Modèle contenant toutes les métadonnées de l'en-tête du match."""

    match_code: str
    competition: str
    organisateur: Optional[str]
    journee: Optional[str]
    ville: Optional[str]
    salle: Optional[str]
    date: Optional[datetime_date]
    heure: Optional[datetime_time]
    genre: Optional[Genre]
    categorie: Optional[Categorie]
    niveau: Optional[Niveau]
    nom_gauche: str
    nom_droite: str
    gauche_est_equipe_a: bool
    technique_marqueur: str
    raw_date: str = ""
    division: Optional[str] = None
    niveau_badge: Optional[str] = None
    niveau_rank: Optional[int] = None
    raw_division_cat: str = ""


def extract_team_marker(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    image_blocks: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, str]:
    """
    Détermine si l'équipe côté gauche est l'Équipe A ou l'Équipe B.
    Retourne (gauche_est_equipe_a, technique_utilisee).
    """
    if image_blocks:
        for img in image_blocks:
            bbox = img.get("bbox", [0, 0, 0, 0])
            x0, y0, x1, y1 = bbox[0], bbox[1], bbox[2], bbox[3]
            w = x1 - x0
            if 395 <= x0 <= 420 and 50 <= y0 <= 75 and 8 <= w <= 25:
                digest = img.get("digest")
                md5_hex = digest.hex() if isinstance(digest, bytes) else str(digest)
                if md5_hex == MD5_ICON_A:
                    return True, "MD5 Image Icon (Macaron PNG A)"
                elif md5_hex == MD5_ICON_B:
                    return False, "MD5 Image Icon (Macaron PNG B)"

    # Fallback textuel sur l'en-tête gauche
    header_marker_words = slice_words_in_box(sorted_words, y0_list, 100.0, 50.0, 135.0, 75.0)
    for w in header_marker_words:
        txt = w[4].upper().strip()
        if txt in ("A", "(A)"):
            return True, "Texte d'en-tête (Marqueur A)"
        elif txt in ("B", "(B)"):
            return False, "Texte d'en-tête (Marqueur B)"

    return True, "Position par défaut (Gauche = A)"


def extract_fast_header(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    config: ParserLayoutConfig,
    image_blocks: Optional[List[Dict[str, Any]]] = None,
) -> HeaderData:
    """
    Extrait l'ensemble des champs d'en-tête et résout l'équipe A/B en un seul appel rapide (< 0.5ms).
    """
    reg = config.bboxes

    match_code = extract_text_in_region(sorted_words, y0_list, reg.get("header/match_code")) or "INCONNU"
    competition = extract_text_in_region(sorted_words, y0_list, reg.get("header/competition")) or "Compétition FFVB"
    organisateur = extract_text_in_region(sorted_words, y0_list, reg.get("header/organisateur")) or None
    journee = extract_text_in_region(sorted_words, y0_list, reg.get("header/journee")) or None
    ville = extract_text_in_region(sorted_words, y0_list, reg.get("header/ville")) or None
    salle = extract_text_in_region(sorted_words, y0_list, reg.get("header/salle")) or None
    raw_date = extract_text_in_region(sorted_words, y0_list, reg.get("header/date")) or ""
    div_cat_str = extract_text_in_region(sorted_words, y0_list, reg.get("header/division_categorie")) or ""

    nom_gauche = extract_text_in_region(sorted_words, y0_list, reg.get("header/equipes/gauche")) or "Équipe Gauche"
    nom_droite = extract_text_in_region(sorted_words, y0_list, reg.get("header/equipes/droite")) or "Équipe Droite"

    # Parsing date & heure
    parsed_date, parsed_time = parse_date_heure(raw_date)

    # Genre & Catégorie extraits directement de la feuille de match
    genre_str = normalize_genre(div_cat_str) or normalize_genre(competition)
    genre = try_enum(Genre, genre_str)

    cat_str = normalize_categorie(div_cat_str) or normalize_categorie(competition)
    categorie = try_enum(Categorie, cat_str)

    # Division depuis la feuille de match ou le nom de compétition
    div_num = extract_division_number(div_cat_str) or extract_division_number(competition)

    # Classification de niveau exhaustive
    classification = classify_level(
        competition_name=competition,
        categorie=cat_str,
        division=div_num,
        raw_division_cat=div_cat_str,
    )
    niveau = try_enum(Niveau, classification.categorie_principale)

    # Marqueur Équipe A/B
    gauche_est_a, technique = extract_team_marker(sorted_words, y0_list, image_blocks)

    return HeaderData(
        match_code=match_code,
        competition=competition,
        organisateur=organisateur,
        journee=journee,
        ville=ville,
        salle=salle,
        date=parsed_date,
        heure=parsed_time,
        genre=genre,
        categorie=categorie,
        niveau=niveau,
        nom_gauche=nom_gauche,
        nom_droite=nom_droite,
        gauche_est_equipe_a=gauche_est_a,
        technique_marqueur=technique,
        raw_date=raw_date,
        division=classification.division,
        niveau_badge=classification.label,
        niveau_rank=classification.rank,
        raw_division_cat=div_cat_str,
    )
