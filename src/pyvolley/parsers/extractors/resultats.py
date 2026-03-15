"""
Extraction du résultat global, arbitres, sanctions et remarques.

Responsable de : vainqueur, score final, durée, arbitres,
sanctions, remarques, demande non fondée, détection match joué.
"""

from __future__ import annotations

import re
import logging
from typing import Optional

from pyvolley.core.models import (
    Arbitre, Sanction, RoleArbitre, TypeSanction,
)
from pyvolley.parsers.constants import ROLE_ARBITRE_MAP
from pyvolley.parsers.utils import (
    split_nom_prenom, normalize_name, clean_team_name,
)

logger = logging.getLogger(__name__)


_VAINQUEUR_MAIN_PATTERN = re.compile(
    r'Vainqueur:\s*'
    r'([A-Za-zÀ-ÿŒœÆæ0-9][A-Za-zÀ-ÿŒœÆæ0-9\s\-\'\.\/\(\)]+?)'
    r'\s+(\d)/(\d)',
)
_VAINQUEUR_FALLBACK_PATTERN = re.compile(
    r'Vainqueur:\s*([A-Za-zÀ-ÿŒœÆæ0-9][^\n]*)',
)
_VAINQUEUR_SUFFIX_CLEAN_PATTERN = re.compile(
    r'\s+(?:Entraineur|Capitaine|SIGNATURES?)\b.*$',
    re.IGNORECASE,
)
_TRAILING_SCORE_PATTERN = re.compile(r'(\d)/(\d)\s*$')
_DUREE_H_PATTERN = re.compile(r'Durée\s*(\d+h\d+)')
_DUREE_MIN_PATTERN = re.compile(r"Durée.*?(\d+)'")


# =====================================================================
# Résultat global (vainqueur, score, durée)
# =====================================================================


def extract_resultat(lines: list[str], tidx: dict) -> dict:
    """Extrait le vainqueur, le score final et la durée totale."""
    result: dict = {
        "vainqueur": None,
        "score_final": None,
        "duree_totale": None,
    }

    full_text = '\n'.join(lines)

    # Regex principale
    if vm := _VAINQUEUR_MAIN_PATTERN.search(full_text):
        raw_name = vm.group(1).strip()
        raw_name = _VAINQUEUR_SUFFIX_CLEAN_PATTERN.sub('', raw_name).strip()
        result["vainqueur"] = normalize_name(raw_name)
        result["score_final"] = f"{vm.group(2)}/{vm.group(3)}"
    else:
        if v2 := _VAINQUEUR_FALLBACK_PATTERN.search(full_text):
            raw = v2.group(1).strip()
            raw = _VAINQUEUR_SUFFIX_CLEAN_PATTERN.sub('', raw).strip()
            if sm := _TRAILING_SCORE_PATTERN.search(raw):
                result["score_final"] = f"{sm.group(1)}/{sm.group(2)}"
                result["vainqueur"] = normalize_name(raw[:sm.start()].strip())
            elif len(raw) > 3:
                result["vainqueur"] = normalize_name(raw)

    # Fallback : table RESULTATS (dernière ligne)
    tbl = tidx.get('results')
    if tbl and not result["vainqueur"]:
        for row in reversed(tbl):
            if not row:
                continue
            rt = ' '.join(str(c) for c in row if c)
            if 'Vainqueur' in rt:
                if vm := _VAINQUEUR_MAIN_PATTERN.search(rt):
                    result["vainqueur"] = normalize_name(vm.group(1).strip())
                    result["score_final"] = f"{vm.group(2)}/{vm.group(3)}"
                break

    # Nettoyer les noms tronqués
    if result["vainqueur"]:
        result["vainqueur"] = clean_team_name(result["vainqueur"])

    # Durée
    if dm := _DUREE_H_PATTERN.search(full_text):
        result["duree_totale"] = dm.group(1)
    elif dm := _DUREE_MIN_PATTERN.search(full_text):
        result["duree_totale"] = dm.group(1) + "'"

    return result


def is_match_played(resultat: dict) -> bool:
    """Un match est considéré comme joué si un vainqueur est renseigné."""
    return bool(resultat.get("vainqueur"))


def has_detailed_scores(resultat: dict) -> bool:
    """True si la feuille contient un score de sets non nul (ex: 3/1)."""
    sf = resultat.get("score_final", "0/0")
    if not sf:
        return False
    try:
        a, b = sf.split("/")
        return int(a) + int(b) > 0
    except (ValueError, AttributeError):
        return False


def detect_set_target_score(
    competition: Optional[str],
    sets: list,
) -> int:
    """Détecte le score cible par set (25, 21 ou 15).

    1. Mots-clés dans le nom de compétition
    2. Scores réels des sets
    """
    from pyvolley.parsers.constants import (
        COMPETITION_FORMAT_15_KEYWORDS,
        COMPETITION_FORMAT_21_KEYWORDS,
    )

    if competition:
        comp_upper = competition.upper()
        for kw in COMPETITION_FORMAT_15_KEYWORDS:
            if kw in comp_upper:
                return 15
        for kw in COMPETITION_FORMAT_21_KEYWORDS:
            if kw in comp_upper:
                return 21

    max_scores = []
    for s in sets:
        sa = getattr(s, 'score_a', None) or (
            s.get('score_a') if isinstance(s, dict) else None
        )
        sb = getattr(s, 'score_b', None) or (
            s.get('score_b') if isinstance(s, dict) else None
        )
        if sa is not None and sb is not None and (sa > 0 or sb > 0):
            max_scores.append(max(sa, sb))

    if max_scores:
        if all(ms <= 17 for ms in max_scores):
            return 15
        if all(ms <= 23 for ms in max_scores):
            return 21

    return 25


# =====================================================================
# Arbitres
# =====================================================================


def extract_arbitres(tidx: dict) -> list[Arbitre]:
    """Parse les arbitres depuis la table main."""
    arbitres: list[Arbitre] = []

    tbl = tidx.get('main')
    if not tbl:
        return arbitres

    in_arbitre_section = False

    for row in tbl:
        if not row:
            continue
        rt = ' '.join(str(c) for c in row if c)

        if 'Arbitres' in rt and 'NOM' in rt:
            in_arbitre_section = True
            continue

        if not in_arbitre_section:
            continue

        if 'Capitaines' in rt or 'Juges' in rt and 'Lignes' in rt:
            continue

        # Chercher un rôle d'arbitre
        role_found = None
        role_col = None
        for k, cell in enumerate(row):
            if not cell:
                continue
            cs = str(cell).strip()
            for role_text, role_enum in ROLE_ARBITRE_MAP.items():
                if cs == role_text:
                    role_found = role_enum
                    role_col = k
                    break
                if cs.startswith(role_text) and len(cs) > len(role_text):
                    role_found = role_enum
                    role_col = k
                    break
            if role_found:
                break

        if not role_found:
            continue

        nom_complet = None
        licence = None
        ligue = None

        for j in range(len(row)):
            if j == role_col:
                cs = str(row[j]).strip() if row[j] else ""
                for rt_text in ROLE_ARBITRE_MAP:
                    if cs.startswith(rt_text) and len(cs) > len(rt_text):
                        remaining = cs[len(rt_text):].strip()
                        if remaining and ' ' in remaining:
                            nom_complet = remaining
                        break
                continue

            if not row[j]:
                continue
            cs = str(row[j]).strip()
            if not cs:
                continue

            if cs.isdigit() and 4 <= len(cs) <= 7:
                licence = cs
            elif cs.isalpha() and cs.isupper() and 2 <= len(cs) <= 4:
                ligue = cs
            elif ' ' in cs and len(cs) > 3 and cs not in (
                'NOM Prénom', 'Nom Prénom',
            ):
                nom_complet = cs

        if nom_complet:
            nom, prenom = split_nom_prenom(nom_complet)
            if not any(
                a.nom == nom and a.role == role_found for a in arbitres
            ):
                arbitres.append(Arbitre(
                    nom=nom, prenom=prenom,
                    role=role_found,
                    licence=licence,
                    ligue=ligue,
                ))

    return arbitres


# =====================================================================
# Sanctions
# =====================================================================


def extract_sanctions(tidx: dict) -> tuple[list[Sanction], list[str]]:
    """Parse les sanctions. Signale toute sanction détectée."""
    sanctions: list[Sanction] = []
    warnings: list[str] = []

    tbl = tidx.get('main')
    if not tbl:
        return sanctions, warnings

    in_sanctions = False
    raw_data: list[str] = []

    for row in tbl:
        if not row:
            continue
        rt = ' '.join(str(c) for c in row if c).upper()

        if 'SANCTIONS' in rt and ('DEMANDE' in rt or 'EQU' in rt):
            in_sanctions = True
            continue

        if in_sanctions:
            if any(kw in rt for kw in [
                '1ER', '2ÈME', 'MARQUEUR', 'ARBITRE', 'APPROBATION',
            ]):
                break

            mid = len(row) // 2
            has_content = False
            for cell in row:
                if not cell:
                    continue
                cs = str(cell).strip()
                if cs and len(cs) >= 2 and cs.upper() not in (
                    'A', 'P', 'E', 'D', 'A/B', 'EQU.A EQU.B',
                    'SET', 'SCORE',
                ):
                    has_content = True
                    break

            if has_content:
                row_data = ' | '.join(
                    str(c).strip() for c in row if c and str(c).strip()
                )
                raw_data.append(row_data)

                equipe = 'A'
                for j, cell in enumerate(row):
                    if not cell:
                        continue
                    cs = str(cell).strip()
                    if not cs or len(cs) < 2:
                        continue
                    if j >= mid:
                        equipe = 'B'

                    sm = re.search(
                        r'(\d{1,2})\s+(\d)\s+.*?(\d+)[-:](\d+)', cs,
                    )
                    if sm:
                        sanctions.append(Sanction(
                            type=TypeSanction.AVERTISSEMENT,
                            set_numero=int(sm.group(2)),
                            equipe=equipe,
                            joueur_numero=sm.group(1),
                            score_a=int(sm.group(3)),
                            score_b=int(sm.group(4)),
                        ))

    if raw_data:
        warnings.append(
            f"⚠️ SANCTIONS DÉTECTÉES : {'; '.join(raw_data)}. "
            f"Vérifiez le PDF manuellement."
        )

    return sanctions, warnings


# =====================================================================
# Remarques / Demande non fondée
# =====================================================================


def extract_remarques(tidx: dict) -> Optional[str]:
    """Extrait les remarques depuis la table main."""
    tbl = tidx.get('main')
    if not tbl:
        return None

    in_remarques = False
    content: list[str] = []

    for row in tbl:
        if not row:
            continue
        rt = ' '.join(str(c) for c in row if c)
        if 'REMARQUES' in rt:
            in_remarques = True
            parts = rt.split('REMARQUES')
            if len(parts) > 1:
                rem = parts[1].strip()
                if rem and not re.match(r'^[APED\s|/]+$', rem) and len(rem) > 3:
                    content.append(rem)
            continue
        if in_remarques:
            if any(kw in rt for kw in [
                'SANCTIONS', 'APPROBATION', 'Arbitres', 'EQU.A',
                'A/B', 'Set', 'Score',
            ]):
                break
            cleaned = rt.strip()
            if (cleaned and len(cleaned) > 3
                    and not re.match(r'^[APED\s|/]+$', cleaned)
                    and cleaned not in ('EQU.A EQU.B',)):
                content.append(cleaned)

    return ' '.join(content).strip() or None


def extract_demande_non_fondee(tidx: dict) -> Optional[str]:
    """Extrait la demande non fondée depuis la table main."""
    tbl = tidx.get('main')
    if not tbl:
        return None

    for row in tbl:
        if not row:
            continue
        rt = ' '.join(str(c) for c in row if c)
        if 'DEMANDE NON FONDEE' in rt:
            parts = rt.split('DEMANDE NON FONDEE')
            if len(parts) > 1:
                rem = parts[1].replace('REMARQUES', '').strip()
                if rem:
                    return rem
    return None
