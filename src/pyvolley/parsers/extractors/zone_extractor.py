"""
Module d'extraction par zones géométriques hiérarchisées (ZoneExtractor).

Reconstruit la structure hiérarchique de données pour les outils d'inspection (LayoutEditor) et tests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pyvolley.parsers.layout_config import LayoutRegion, ParserLayoutConfig, DEFAULT_FFVB_LAYOUT
from pyvolley.parsers.extractors.fast.utils import (
    WordTuple,
    extract_text_in_region,
    normalize_words,
    slice_words_in_region,
)
from pyvolley.parsers.extractors.fast.header import extract_fast_header, extract_team_marker
from pyvolley.parsers.extractors.fast.rosters import extract_single_team_roster
from pyvolley.parsers.extractors.fast.arbitres import extract_fast_arbitres
from pyvolley.parsers.extractors.fast.resultats import extract_fast_resultats


def extract_text_in_zone(words: List[Any], region: LayoutRegion) -> str:
    """Extrait et ordonne la chaîne de caractères présente dans une zone rectangulaire."""
    sorted_words, y0_list = normalize_words(words)
    return extract_text_in_region(sorted_words, y0_list, region)


def extract_hierarchical_data(
    words: List[Any],
    config: Optional[ParserLayoutConfig] = None,
    drawings: Optional[List[dict]] = None,
    image_blocks: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """
    Génère un dictionnaire hiérarchique structuré pour l'inspection et les tests.
    """
    active_config = config or DEFAULT_FFVB_LAYOUT
    sorted_words, y0_list = normalize_words(words)

    hdr = extract_fast_header(sorted_words, y0_list, active_config, image_blocks=image_blocks)
    roster_gauche = extract_single_team_roster(sorted_words, y0_list, active_config, side="gauche")
    roster_droite = extract_single_team_roster(sorted_words, y0_list, active_config, side="droite")
    arbitres = extract_fast_arbitres(sorted_words, y0_list, active_config)
    res_data = extract_fast_resultats(sorted_words, y0_list, active_config)

    result: Dict[str, Any] = {
        "marqueur_gauche": "A" if hdr.gauche_est_equipe_a else "B",
        "technique_marqueur": hdr.technique_marqueur,
        "gauche_est_equipe_a": hdr.gauche_est_equipe_a,
        "header": {
            "match_code": hdr.match_code,
            "competition": hdr.competition,
            "organisateur": hdr.organisateur,
            "journee": hdr.journee,
            "ville": hdr.ville,
            "salle": hdr.salle,
            "date": hdr.raw_date,
            "equipes": {
                "gauche": hdr.nom_gauche,
                "droite": hdr.nom_droite,
            },
        },
        "equipes": {
            "gauche": {
                "joueurs": [
                    {
                        "numero": j.numero,
                        "nom": j.nom,
                        "prenom": j.prenom,
                        "licence": j.licence,
                        "est_capitaine": j.est_capitaine,
                    }
                    for j in roster_gauche.joueurs
                ],
                "liberos": [
                    {
                        "numero": j.numero,
                        "nom": j.nom,
                        "prenom": j.prenom,
                        "licence": j.licence,
                    }
                    for j in roster_gauche.liberos
                ],
                "officiels": [
                    {
                        "role": o.role,
                        "nom": o.nom,
                        "prenom": o.prenom,
                        "licence": o.licence,
                    }
                    for o in roster_gauche.officiels
                ],
            },
            "droite": {
                "joueurs": [
                    {
                        "numero": j.numero,
                        "nom": j.nom,
                        "prenom": j.prenom,
                        "licence": j.licence,
                        "est_capitaine": j.est_capitaine,
                    }
                    for j in roster_droite.joueurs
                ],
                "liberos": [
                    {
                        "numero": j.numero,
                        "nom": j.nom,
                        "prenom": j.prenom,
                        "licence": j.licence,
                    }
                    for j in roster_droite.liberos
                ],
                "officiels": [
                    {
                        "role": o.role,
                        "nom": o.nom,
                        "prenom": o.prenom,
                        "licence": o.licence,
                    }
                    for o in roster_droite.officiels
                ],
            },
        },
        "arbitres": [
            {
                "role": a.role.value if hasattr(a.role, "value") else str(a.role),
                "nom": a.nom,
                "prenom": a.prenom,
                "ligue": a.ligue or "",
                "licence": a.licence,
            }
            for a in arbitres
        ],
        "resultats": {
            "vainqueur": res_data.vainqueur,
            "score_final": res_data.score_final,
            "debut": res_data.heure_debut,
            "fin": res_data.heure_fin,
            "duree_totale": res_data.duree_totale,
            "raw_text": res_data.raw_text,
            "sets": [
                {
                    "numero": s.numero,
                    "points_a": s.points_a,
                    "points_b": s.points_b,
                    "duree": s.duree,
                }
                for s in res_data.sets_summary.values()
            ],
        },
        "remarques": res_data.remarques,
    }

    return result
