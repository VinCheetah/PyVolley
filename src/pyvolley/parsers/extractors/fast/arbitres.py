"""
Module d'extraction direct et ultra-rapide du corps arbitral (Arbitres, Marqueurs, Resp. Salle, Juges).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pyvolley.core.models import Arbitre, RoleArbitre
from pyvolley.parsers.layout_config import ParserLayoutConfig
from pyvolley.parsers.extractors.fast.utils import (
    WordTuple,
    group_words_by_line,
    is_digit_token,
    line_tokens,
    parse_name_parts,
    slice_words_in_region,
)

ROLE_MAP = {
    "1ER": RoleArbitre.PREMIER,
    "1": RoleArbitre.PREMIER,
    "2ÈME": RoleArbitre.SECOND,
    "2EME": RoleArbitre.SECOND,
    "2": RoleArbitre.SECOND,
    "MARQUEUR": RoleArbitre.MARQUEUR,
    "MARQUEUR ASSISTANT": RoleArbitre.MARQUEUR_ASSISTANT,
    "MARQUEUR ASS.": RoleArbitre.MARQUEUR_ASSISTANT,
    "MARQ. ASS.": RoleArbitre.MARQUEUR_ASSISTANT,
    "MARQ.ASS.": RoleArbitre.MARQUEUR_ASSISTANT,
    "RESPONSABLE DE SALLE": RoleArbitre.RESPONSABLE_SALLE,
    "RESPONSABLE SALLE": RoleArbitre.RESPONSABLE_SALLE,
    "RESP. SALLE": RoleArbitre.RESPONSABLE_SALLE,
    "R. SALLE": RoleArbitre.RESPONSABLE_SALLE,
    "R.SALLE": RoleArbitre.RESPONSABLE_SALLE,
    "JUGE DE LIGNE": RoleArbitre.JUGE_LIGNE,
    "JUGE LIGNE": RoleArbitre.JUGE_LIGNE,
    "JUGES LIGNES": RoleArbitre.JUGE_LIGNE,
}

DEFAULT_ROLES = [
    RoleArbitre.PREMIER,
    RoleArbitre.SECOND,
    RoleArbitre.MARQUEUR,
    RoleArbitre.MARQUEUR_ASSISTANT,
    RoleArbitre.RESPONSABLE_SALLE,
    RoleArbitre.JUGE_LIGNE,
]


def extract_fast_arbitres(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    config: ParserLayoutConfig,
) -> List[Arbitre]:
    """
    Extrait l'ensemble des membres du corps arbitral depuis la zone dédiée.
    """
    arbitres: List[Arbitre] = []
    arb_reg = config.bboxes.get("arbitres")
    if not arb_reg:
        return arbitres

    arb_words = slice_words_in_region(sorted_words, y0_list, arb_reg)
    if not arb_words:
        return arbitres

    lines_arb = group_words_by_line(arb_words, y_step=3.0)
    row_idx = 0

    for y_key in sorted(lines_arb.keys()):
        tokens = line_tokens(lines_arb[y_key])
        if len(tokens) < 3 or not is_digit_token(tokens[-1], 5, 8):
            continue

        licence = tokens[-1]
        body = tokens[:-1]

        # Détection de la ligue (ex: BRE, PDL, IDF, etc.)
        ligue: Optional[str] = None
        if len(body) >= 2 and body[-1].isalpha() and body[-1].isupper() and 2 <= len(body[-1]) <= 4:
            ligue = body[-1]
            body = body[:-1]

        if not body:
            continue

        role: Optional[RoleArbitre] = None
        body_upper = [t.upper() for t in body]
        joined_upper = " ".join(body_upper)

        if body_upper[0].startswith("1"):
            role = RoleArbitre.PREMIER
            body = body[1:]
        elif body_upper[0].startswith("2"):
            role = RoleArbitre.SECOND
            body = body[1:]
        elif joined_upper.startswith("RESPONSABLE DE SALLE"):
            role = RoleArbitre.RESPONSABLE_SALLE
            body = body[3:]
        elif joined_upper.startswith("RESPONSABLE SALLE") or joined_upper.startswith("RESP. SALLE") or joined_upper.startswith("R. SALLE"):
            role = RoleArbitre.RESPONSABLE_SALLE
            body = body[2:]
        elif body_upper[0] == "R.SALLE":
            role = RoleArbitre.RESPONSABLE_SALLE
            body = body[1:]
        elif joined_upper.startswith("MARQUEUR ASSISTANT"):
            role = RoleArbitre.MARQUEUR_ASSISTANT
            body = body[2:]
        elif joined_upper.startswith("MARQUEUR ASS.") or joined_upper.startswith("MARQ. ASS.") or joined_upper.startswith("MARQ.ASS."):
            role = RoleArbitre.MARQUEUR_ASSISTANT
            body = body[2:]
        elif body_upper[0].startswith("MARQ") and len(body_upper[0]) > 4 and "ASS" in body_upper[0]:
            role = RoleArbitre.MARQUEUR_ASSISTANT
            body = body[1:]
        elif joined_upper.startswith("MARQUEUR") or joined_upper.startswith("MARQ."):
            role = RoleArbitre.MARQUEUR
            body = body[1:]
        elif joined_upper.startswith("JUGE DE LIGNE"):
            role = RoleArbitre.JUGE_LIGNE
            body = body[3:]
        elif joined_upper.startswith("JUGE LIGNE") or joined_upper.startswith("JUGES LIGNES"):
            role = RoleArbitre.JUGE_LIGNE
            body = body[2:]

        if not role:
            role = DEFAULT_ROLES[row_idx] if row_idx < len(DEFAULT_ROLES) else RoleArbitre.SECOND

        nom, prenom = parse_name_parts(body)
        if nom or prenom or licence:
            arbitres.append(
                Arbitre(
                    nom=nom,
                    prenom=prenom,
                    role=role,
                    ligue=ligue,
                    licence=licence,
                )
            )
            row_idx += 1

    return arbitres
