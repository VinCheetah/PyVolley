"""
Module d'extraction direct et ultra-rapide des effectifs (Joueurs, Libéros, Officiels, Capitaines).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from pyvolley.core.models import Equipe, Joueur, Officiel
from pyvolley.parsers.layout_config import ParserLayoutConfig
from pyvolley.parsers.extractors.fast.utils import (
    WordTuple,
    group_words_by_line,
    is_digit_token,
    line_tokens,
    parse_name_parts,
    slice_words_in_region,
)

IGNORED_HEADER_TOKENS = {"LICENCE", "OFFICIELS", "LIBEROS", "N°", "JOUEURS", "CAPITAINE"}
CAPTAIN_TOKENS = {"(C)", "C"}


@dataclass
class FastRosterData:
    """Modèle contenant les effectifs extraits pour une équipe."""

    joueurs: List[Joueur] = field(default_factory=list)
    liberos: List[Joueur] = field(default_factory=list)
    officiels: List[Officiel] = field(default_factory=list)
    capitaine: Optional[str] = None
    line_y_centers: Dict[str, float] = field(default_factory=dict)  # licence -> cy


def _parse_joueur_line(tokens: List[str]) -> Optional[Tuple[str, str, str, str, bool]]:
    """Parse une ligne de joueur: N° Nom Prénom Licence [Capitaine (C)]."""
    if len(tokens) < 3:
        return None

    if any(t.upper() in IGNORED_HEADER_TOKENS for t in tokens):
        return None

    is_cap = any(t.upper() in CAPTAIN_TOKENS for t in tokens)
    clean = [t for t in tokens if t.upper() not in CAPTAIN_TOKENS]
    if len(clean) < 3:
        return None

    if not is_digit_token(clean[0], 1, 2) or not is_digit_token(clean[-1], 5, 8):
        return None

    num = clean[0]
    licence = clean[-1]
    nom, prenom = parse_name_parts(clean[1:-1])
    if not nom:
        return None

    return num, nom, prenom, licence, is_cap


def _parse_officiel_line(tokens: List[str]) -> Optional[Tuple[str, str, str, str]]:
    """Parse une ligne d'officiel: Role Nom Prénom Licence."""
    if len(tokens) < 3:
        return None

    if any(t.upper() in IGNORED_HEADER_TOKENS for t in tokens):
        return None

    role = tokens[0].upper().rstrip(".")
    if not role.isalpha() or len(role) > 4:
        return None

    if not is_digit_token(tokens[-1], 5, 8):
        return None

    nom, prenom = parse_name_parts(tokens[1:-1])
    if not nom:
        return None

    return role, nom, prenom, tokens[-1]


def extract_single_team_roster(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    config: ParserLayoutConfig,
    side: str,  # "gauche" ou "droite"
    captain_image_bboxes: Optional[List[Tuple[float, float, float, float]]] = None,
) -> FastRosterData:
    """Extrait les joueurs, libéros, officiels et capitaine pour un côté donné."""
    res = FastRosterData()
    bboxes = config.bboxes

    roster_reg = bboxes.get(f"equipes/{side}/joueurs")
    liberos_reg = bboxes.get(f"equipes/{side}/liberos")
    officiels_reg = bboxes.get(f"equipes/{side}/officiels")

    # 1. Extraction des Joueurs
    if roster_reg:
        r_words = slice_words_in_region(sorted_words, y0_list, roster_reg)
        lines_r = group_words_by_line(r_words, y_step=3.0)

        for y_key in sorted(lines_r.keys()):
            line_w = lines_r[y_key]
            tokens = line_tokens(line_w)
            parsed = _parse_joueur_line(tokens)
            if parsed:
                num, nom, prenom, licence, is_cap = parsed
                joueur = Joueur(
                    numero=num,
                    nom=nom,
                    prenom=prenom,
                    licence=licence,
                    est_capitaine=is_cap,
                    est_libero=False,
                )
                res.joueurs.append(joueur)
                if is_cap and not res.capitaine:
                    res.capitaine = num

                # Stocker le centre Y de la ligne pour le match image macaron
                cy = sum((w[1] + w[3]) * 0.5 for w in line_w) / len(line_w)
                res.line_y_centers[licence] = cy

    # 2. Détection du Capitaine via Image Blocks (Méthode déterministe)
    if captain_image_bboxes and not res.capitaine and roster_reg:
        rx0, ry0, rx1, ry1 = roster_reg.x0, roster_reg.y0, roster_reg.x1, roster_reg.y1
        for img_bbox in captain_image_bboxes:
            ix0, iy0, ix1, iy1 = img_bbox
            cx = (ix0 + ix1) * 0.5
            cy = (iy0 + iy1) * 0.5
            if rx0 <= cx <= rx1 and ry0 <= cy <= ry1:
                for j in res.joueurs:
                    j_cy = res.line_y_centers.get(j.licence)
                    if j_cy is not None and abs(j_cy - cy) <= 6.0:
                        res.capitaine = j.numero
                        j.est_capitaine = True
                        break
                if res.capitaine:
                    break

    # 3. Extraction des Libéros
    if liberos_reg:
        l_words = slice_words_in_region(sorted_words, y0_list, liberos_reg)
        lines_l = group_words_by_line(l_words, y_step=3.0)

        for y_key in sorted(lines_l.keys()):
            tokens = line_tokens(lines_l[y_key])
            parsed = _parse_joueur_line(tokens)
            if parsed:
                num, nom, prenom, licence, _ = parsed
                libero = Joueur(
                    numero=num,
                    nom=nom,
                    prenom=prenom,
                    licence=licence,
                    est_libero=True,
                )
                res.liberos.append(libero)
                for j in res.joueurs:
                    if j.licence == licence:
                        j.est_libero = True

    # 4. Extraction des Officiels
    if officiels_reg:
        o_words = slice_words_in_region(sorted_words, y0_list, officiels_reg)
        lines_o = group_words_by_line(o_words, y_step=3.0)

        for y_key in sorted(lines_o.keys()):
            tokens = line_tokens(lines_o[y_key])
            parsed = _parse_officiel_line(tokens)
            if parsed:
                role, nom, prenom, licence = parsed
                officiel = Officiel(
                    role=role,
                    nom=nom,
                    prenom=prenom,
                    licence=licence,
                )
                res.officiels.append(officiel)

    return res


def extract_fast_rosters(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    config: ParserLayoutConfig,
    nom_gauche: str,
    nom_droite: str,
    gauche_est_equipe_a: bool,
    captain_image_bboxes: Optional[List[Tuple[float, float, float, float]]] = None,
) -> Tuple[Equipe, Equipe, FastRosterData, FastRosterData]:
    """
    Extrait les effectifs des deux équipes et effectue le mapping déterministe A/B.
    Retourne (equipe_a, equipe_b, roster_a, roster_b).
    """
    roster_gauche = extract_single_team_roster(
        sorted_words, y0_list, config, side="gauche", captain_image_bboxes=captain_image_bboxes
    )
    roster_droite = extract_single_team_roster(
        sorted_words, y0_list, config, side="droite", captain_image_bboxes=captain_image_bboxes
    )

    if gauche_est_equipe_a:
        nom_a, roster_a = nom_gauche, roster_gauche
        nom_b, roster_b = nom_droite, roster_droite
    else:
        nom_a, roster_a = nom_droite, roster_droite
        nom_b, roster_b = nom_gauche, roster_gauche

    equipe_a = Equipe(
        nom=nom_a,
        capitaine=roster_a.capitaine,
        joueurs=roster_a.joueurs,
        liberos=roster_a.liberos,
        officiels=roster_a.officiels,
    )
    equipe_b = Equipe(
        nom=nom_b,
        capitaine=roster_b.capitaine,
        joueurs=roster_b.joueurs,
        liberos=roster_b.liberos,
        officiels=roster_b.officiels,
    )

    return equipe_a, equipe_b, roster_a, roster_b
