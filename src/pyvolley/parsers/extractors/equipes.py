"""
Extraction des données d'équipe depuis la feuille de match.

Responsable de : noms d'équipe, joueurs, libéros, capitaines, officiels,
récupération des joueurs manquants (feuille dupliquée).
"""

from __future__ import annotations

import re
import logging
from collections import defaultdict
from typing import Optional

from pyvolley.core.models import Joueur, Officiel, Set
from pyvolley.parsers.constants import (
    JOUEUR_PATTERN, JOUEUR_GLUED_PATTERN, JOUEUR_NO_LICENCE_PATTERN,
)
from pyvolley.parsers.utils import (
    split_nom_prenom, clean_team_name, normalize_name,
)

logger = logging.getLogger(__name__)


# =====================================================================
# Noms d'équipe
# =====================================================================


def extract_equipes(
    tidx: dict, words: list, lines: list[str],
) -> dict:
    """Extrait les noms d'équipe depuis la table joueurs ou le header."""
    eq: dict[str, Optional[str]] = {"equipe_a": None, "equipe_b": None}

    # Méthode 1 : Table joueurs (row 0)
    tbl = tidx.get('players')
    if tbl and tbl[0]:
        names = []
        for cell in tbl[0]:
            if cell:
                cs = str(cell).strip()
                if len(cs) >= 2 and not any(
                    kw in cs for kw in ['N°', 'Nom', 'Licence', 'LIBEROS']
                ):
                    names.append(cs)
        if len(names) >= 2:
            eq["equipe_a"] = names[0]
            eq["equipe_b"] = names[1]
        elif len(names) == 1:
            eq["equipe_a"] = names[0]

    # Nettoyage des noms : artefacts de lettres isolées
    for key in ("equipe_a", "equipe_b"):
        if not eq[key]:
            continue
        val = eq[key]
        assert val is not None  # for type checker
        first_match = re.match(
            r'^([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ])\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ])',
            val,
        )
        if first_match:
            m = re.match(
                r'^((?:[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]\s+)+)([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]{2,})',
                val,
            )
            if m:
                prefix = m.group(1).replace(' ', '')
                val = prefix + ' ' + val[m.end(1):].strip()
        else:
            single = re.match(
                r'^[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]\s+(?=[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]{2,})',
                val,
            )
            if single:
                val = val[single.end():]
        eq[key] = clean_team_name(val)

    # Méthode 3 fallback : mots positionnels
    if not eq["equipe_a"] or not eq["equipe_b"]:
        team_words = sorted(
            [w for w in words if 55 <= w['top'] <= 80],
            key=lambda w: w['x0'],
        )
        if team_words:
            max_x = max(w['x1'] for w in words)
            mid = max_x / 2
            left = ' '.join(w['text'] for w in team_words if w['x0'] < mid)
            right = ' '.join(w['text'] for w in team_words if w['x0'] >= mid)
            if left and not eq["equipe_a"]:
                eq["equipe_a"] = clean_team_name(left.strip())
            if right and not eq["equipe_b"]:
                eq["equipe_b"] = clean_team_name(right.strip())

    return eq


# =====================================================================
# Joueurs (table roster)
# =====================================================================


def extract_joueurs(
    tidx: dict,
) -> tuple[list[Joueur], list[Joueur], bool]:
    """Parse les joueurs depuis la table dédiée.

    Returns:
        ``(joueurs_a, joueurs_b, duplication_detected)``
    """
    joueurs_a: list[Joueur] = []
    joueurs_b: list[Joueur] = []
    duplication_detected = False

    tbl = tidx.get('players')
    if not tbl:
        return joueurs_a, joueurs_b, False

    # Noms d'équipe (Row 0) pour les exclure du parsing
    team_names: set[str] = set()
    if tbl[0]:
        for cell in tbl[0]:
            if cell:
                cs = str(cell).strip()
                if cs:
                    team_names.add(cs)

    for row_idx, row in enumerate(tbl):
        if not row:
            continue
        row_text = ' '.join(str(c) for c in row if c)

        # Ignorer les lignes d'en-tête pures
        if any(kw in row_text for kw in ['Nom Prénom', 'Licence', 'N°']):
            if 'LIBEROS' not in row_text:
                continue
        if 'OFFICIELS' in row_text and 'LIBEROS' not in row_text:
            continue

        is_liberos_row = 'LIBEROS' in row_text
        mid = len(row) // 2

        for cell_idx, cell in enumerate(row):
            if not cell:
                continue
            cs = str(cell).strip()
            if not cs:
                continue
            if cs in team_names:
                continue

            target = joueurs_a if cell_idx < mid else joueurs_b

            if is_liberos_row:
                _parse_liberos_merged_cell(cs, target)
            else:
                dup_count = _parse_player_cell(cs, target)
                if dup_count > 0:
                    duplication_detected = True

    return joueurs_a, joueurs_b, duplication_detected


def _parse_liberos_merged_cell(cs: str, target: list[Joueur]) -> None:
    """Extrait les joueurs depuis une cellule fusionnée LIBEROS."""
    parts = re.split(
        r'L\s*I\s*B\s*E\s*R\s*O\s*S',
        cs, flags=re.IGNORECASE,
    )
    for part in parts:
        part = part.strip()
        if not part:
            continue
        cleaned = re.sub(r'^\d+\s*', '', part)
        if cleaned:
            _add_joueur(cleaned, target)
        _add_joueur(part, target)


def _parse_player_cell(cs: str, target: list[Joueur]) -> int:
    """Parse une cellule de joueurs standard avec déduplication.

    Returns le nombre de lignes dupliquées détectées.
    """
    lines = cs.split('\n')
    seen: set[str] = set()
    total = dup_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        total += 1
        if line in seen:
            dup_count += 1
            continue
        seen.add(line)
        _add_joueur(line, target)

    # Seuil : ≥ 40 % de duplicats avec ≥ 6 lignes → feuille corrompue
    if total >= 6 and dup_count >= total * 0.4:
        return dup_count
    return 0


def _add_joueur(line: str, target: list[Joueur]) -> bool:
    """Tente d'extraire un joueur depuis une ligne de texte."""
    line = line.strip()
    if not line:
        return False

    m = JOUEUR_PATTERN.match(line) or JOUEUR_GLUED_PATTERN.match(line)
    if m:
        numero = m.group(1)
        nom_prenom = m.group(2).strip()
        licence = m.group(3)
        nom, prenom = split_nom_prenom(nom_prenom)
        joueur = Joueur(
            numero=numero, nom=nom, prenom=prenom, licence=licence,
        )
        if not any(j.numero == numero and j.licence == licence for j in target):
            target.append(joueur)
        return True

    m2 = JOUEUR_NO_LICENCE_PATTERN.match(line)
    if m2:
        numero = m2.group(1)
        nom_prenom = m2.group(2).strip()
        nom, prenom = split_nom_prenom(nom_prenom)
        joueur = Joueur(
            numero=numero, nom=nom, prenom=prenom, licence="0",
        )
        if not any(j.numero == numero for j in target):
            target.append(joueur)
        return True

    return False


# =====================================================================
# Récupération joueurs manquants (feuille dupliquée)
# =====================================================================


def recover_joueurs_from_sets(
    joueurs_a: list[Joueur],
    joueurs_b: list[Joueur],
    sets: list[Set],
) -> tuple[list[Joueur], list[Joueur]]:
    """Reconstruit les joueurs manquants à partir des formations et changements.

    Quand une feuille PDF a des joueurs dupliqués, les cellules sont
    tronquées et certains joueurs sont perdus. On retrouve leurs numéros
    dans les formations de départ et les changements.

    Returns ``(recovered_a, recovered_b)`` – joueurs placeholder.
    """

    def _norm(n: str) -> str:
        return n.lstrip('0') or '0'

    roster_a = {_norm(j.numero) for j in joueurs_a if j.numero}
    roster_b = {_norm(j.numero) for j in joueurs_b if j.numero}

    missing_a: set[str] = set()
    missing_b: set[str] = set()

    for s in sets:
        if s.formation_a:
            for num in s.formation_a.as_list():
                if num and _norm(num) not in roster_a:
                    missing_a.add(num)
        if s.formation_b:
            for num in s.formation_b.as_list():
                if num and _norm(num) not in roster_b:
                    missing_b.add(num)
        if s.equipe_a:
            for ch in s.equipe_a.changements:
                for num in [ch.joueur_entrant, ch.joueur_sortant]:
                    if num and _norm(num) not in roster_a:
                        missing_a.add(num)
        if s.equipe_b:
            for ch in s.equipe_b.changements:
                for num in [ch.joueur_entrant, ch.joueur_sortant]:
                    if num and _norm(num) not in roster_b:
                        missing_b.add(num)

    recovered_a = [
        Joueur(numero=num, nom="Inconnu", prenom="Inconnu", licence="0")
        for num in sorted(missing_a)
    ]
    recovered_b = [
        Joueur(numero=num, nom="Inconnu", prenom="Inconnu", licence="0")
        for num in sorted(missing_b)
    ]
    return recovered_a, recovered_b


# =====================================================================
# Libéros (positionnement spatial)
# =====================================================================


def extract_liberos(words: list) -> tuple[list[Joueur], list[Joueur]]:
    """Extrait les libéros depuis la section LIBEROS du PDF."""
    liberos_a: list[Joueur] = []
    liberos_b: list[Joueur] = []

    lib_header = next(
        (w for w in words if w['text'].upper() == 'LIBEROS' and w['x0'] > 500),
        None,
    )
    if not lib_header:
        return liberos_a, liberos_b

    off_header = next(
        (w for w in words if w['text'].upper() == 'OFFICIELS' and w['x0'] > 500),
        None,
    )
    y_start = lib_header['bottom']
    y_end = off_header['top'] if off_header else y_start + 35

    zone_words = [
        w for w in words
        if y_start - 2 <= w['top'] <= y_end and w['x0'] > 500
    ]
    zone_words.sort(key=lambda w: (w['top'], w['x0']))

    x_thresh = 700
    lines_a: dict[int, list] = defaultdict(list)
    lines_b: dict[int, list] = defaultdict(list)
    for w in zone_words:
        key = round(w['top'] / 3) * 3
        if w['x0'] < x_thresh:
            lines_a[key].append(w)
        else:
            lines_b[key].append(w)

    def _build_joueur(line_words: list) -> Optional[Joueur]:
        if not line_words:
            return None
        texts = [w['text'] for w in sorted(line_words, key=lambda w: w['x0'])]
        numero, licence = None, None
        name_parts: list[str] = []
        for t in texts:
            t = t.strip()
            if not t:
                continue
            if t.isdigit() and len(t) <= 2 and numero is None:
                numero = t
            elif t.isdigit() and len(t) >= 6:
                licence = t
            elif t.upper() not in ('LIBEROS',):
                name_parts.append(t)
        if not numero or not licence or not name_parts:
            return None
        nom, prenom = split_nom_prenom(' '.join(name_parts))
        return Joueur(
            numero=numero, nom=nom, prenom=prenom,
            licence=licence, est_libero=True,
        )

    for key in sorted(lines_a):
        if j := _build_joueur(lines_a[key]):
            liberos_a.append(j)
    for key in sorted(lines_b):
        if j := _build_joueur(lines_b[key]):
            liberos_b.append(j)

    return liberos_a, liberos_b


def mark_liberos(joueurs: list[Joueur], liberos: list[Joueur]) -> None:
    """Marque les joueurs qui sont des libéros."""
    lib_ids = {(lib.numero, lib.licence) for lib in liberos}
    lib_nums = {lib.numero for lib in liberos}
    for j in joueurs:
        if (j.numero, j.licence) in lib_ids or j.numero in lib_nums:
            j.est_libero = True


def merge_liberos(joueurs: list[Joueur], liberos: list[Joueur]) -> list[Joueur]:
    """Fusionne les libéros dans la liste des joueurs, sans doublons."""
    existing_ids = {(j.numero, j.licence) for j in joueurs}
    merged = list(joueurs)
    for lib in liberos:
        if (lib.numero, lib.licence) not in existing_ids:
            lib.est_libero = True
            merged.append(lib)
    return merged


# =====================================================================
# Officiels d'équipe (positionnement spatial)
# =====================================================================


def extract_officiels(words: list) -> tuple[list[Officiel], list[Officiel]]:
    """Extrait les officiels d'équipe sous la section OFFICIELS."""
    off_a: list[Officiel] = []
    off_b: list[Officiel] = []

    header = next(
        (w for w in words if w['text'].upper() == 'OFFICIELS' and w['x0'] > 500),
        None,
    )
    if not header:
        return off_a, off_b

    y_start = header['bottom'] - 2
    sig = next(
        (w for w in words
         if w['text'].upper() in ('SIGNATURES', 'Capitaine')
         and w['x0'] > 500),
        None,
    )
    y_end = sig['top'] if sig else y_start + 50

    zone_words = [
        w for w in words
        if y_start <= w['top'] <= y_end and w['x0'] > 570
    ]
    zone_words.sort(key=lambda w: (w['top'], w['x0']))

    x_thresh = 700
    lines_left: dict[int, list] = defaultdict(list)
    lines_right: dict[int, list] = defaultdict(list)
    for w in zone_words:
        key = round(w['top'] / 3) * 3
        if w['x0'] < x_thresh:
            lines_left[key].append(w)
        else:
            lines_right[key].append(w)

    def _build_off(line_words: list) -> Optional[Officiel]:
        if not line_words:
            return None
        texts = [w['text'] for w in sorted(line_words, key=lambda w: w['x0'])]
        role, licence = None, None
        name_parts: list[str] = []
        for t in texts:
            tc = t.strip()
            if not tc:
                continue
            if tc.upper() in ('EA', 'EB', 'MA', 'MB', 'KA', 'KB'):
                role = tc.upper()
            elif tc.isdigit() and len(tc) >= 4:
                licence = tc
            elif tc.upper() not in ('OFFICIELS', 'SIGNATURES'):
                name_parts.append(tc)
        if not role or not name_parts:
            return None
        nom, prenom = split_nom_prenom(' '.join(name_parts))
        return Officiel(role=role, nom=nom, prenom=prenom, licence=licence)

    for key in sorted(lines_left):
        if o := _build_off(lines_left[key]):
            off_a.append(o)
    for key in sorted(lines_right):
        if o := _build_off(lines_right[key]):
            off_b.append(o)

    return off_a, off_b


# =====================================================================
# Capitaines
# =====================================================================


def detect_capitaines(
    images: list, chars: list, words: list,
    tidx: dict,
) -> tuple[Optional[str], Optional[str]]:
    """Détecte les capitaines (3 méthodes en cascade).

    1. Cercles-images dans le roster
    2. Table SIGNATURES
    3. Marqueurs caractères (C, ©)
    """
    cap_a, cap_b = _capitaines_from_images(images, chars, words)
    if not cap_a or not cap_b:
        ca2, cb2 = _capitaines_from_signatures(tidx)
        cap_a = cap_a or ca2
        cap_b = cap_b or cb2
    if not cap_a or not cap_b:
        ca3, cb3 = _capitaines_from_chars(chars, words)
        cap_a = cap_a or ca3
        cap_b = cap_b or cb3
    return cap_a, cap_b


def mark_capitaine(joueurs: list[Joueur], cap_num: Optional[str]) -> None:
    """Marque le joueur capitaine dans la liste."""
    if not cap_num:
        return
    for j in joueurs:
        if j.numero == cap_num or j.numero == cap_num.lstrip('0'):
            j.est_capitaine = True
            break


def _capitaines_from_images(
    images: list, chars: list, words: list,
) -> tuple[Optional[str], Optional[str]]:
    """Détecte les capitaines via les cercles-images dans le roster."""
    cap_a: Optional[str] = None
    cap_b: Optional[str] = None

    n_headers = [w for w in words if w['text'] == 'N°' and w['x0'] > 500]
    roster_y_start = min(w['top'] for w in n_headers) if n_headers else 270
    lib_headers = [
        w for w in words
        if w['text'].upper() == 'LIBEROS' and w['x0'] > 500
    ]
    roster_y_end = min(w['top'] for w in lib_headers) if lib_headers else 400

    captain_imgs = [
        img for img in images
        if img['x0'] > 550
        and roster_y_start - 5 < img['top'] < roster_y_end + 5
        and 5 < img['x1'] - img['x0'] < 22
        and 5 < img['bottom'] - img['top'] < 22
    ]

    x_split = 680
    for img in captain_imgs:
        side = 'A' if img['x0'] < x_split else 'B'
        img_center_y = (img['top'] + img['bottom']) / 2

        nearby_digits = [
            c for c in chars
            if abs(c['top'] - img_center_y) < 12
            and c['text'].isdigit()
            and img['x0'] - 3 < c['x0'] < img['x1'] + 3
        ]
        if not nearby_digits:
            continue

        rows: dict[int, list] = defaultdict(list)
        for c in nearby_digits:
            row_key = round(c['top'] / 3) * 3
            rows[row_key].append(c)

        best_key = min(rows.keys(), key=lambda k: abs(k - img_center_y))
        best_row = sorted(rows[best_key], key=lambda c: c['x0'])
        num = ''.join(c['text'] for c in best_row[:2])

        if num:
            if side == 'A' and not cap_a:
                cap_a = num
            elif side == 'B' and not cap_b:
                cap_b = num

    return cap_a, cap_b


def _capitaines_from_signatures(
    tidx: dict,
) -> tuple[Optional[str], Optional[str]]:
    """Fallback : capitaines depuis SIGNATURES."""
    cap_a, cap_b = None, None
    tbl = tidx.get('signatures')
    if not tbl:
        return cap_a, cap_b

    for i, row in enumerate(tbl):
        if not row:
            continue
        rt = ' '.join(str(c) for c in row if c)
        if 'Capitaine' not in rt:
            continue

        parts = re.findall(r'Capitaine\s+N°\s*(\d{1,2})', rt)
        if len(parts) >= 2:
            cap_a, cap_b = parts[0], parts[1]
        elif len(parts) == 1:
            cap_a = parts[0]

        if i + 1 < len(tbl) and tbl[i + 1]:
            nr = tbl[i + 1]
            mid = len(nr) // 2
            for j, cell in enumerate(nr):
                if cell:
                    cs = str(cell).strip()
                    if cs.isdigit() and len(cs) <= 2:
                        if j < mid and not cap_a:
                            cap_a = cs
                        elif j >= mid and not cap_b:
                            cap_b = cs

    return cap_a, cap_b


def _capitaines_from_chars(
    chars: list, words: list,
) -> tuple[Optional[str], Optional[str]]:
    """Fallback 3 : capitaines via marqueurs 'C' ou '©' dans le roster."""
    cap_a: Optional[str] = None
    cap_b: Optional[str] = None

    n_headers = [w for w in words if w['text'] == 'N°' and w['x0'] > 500]
    roster_y_start = min(w['top'] for w in n_headers) if n_headers else 270
    lib_headers = [
        w for w in words
        if w['text'].upper() == 'LIBEROS' and w['x0'] > 500
    ]
    roster_y_end = min(w['top'] for w in lib_headers) if lib_headers else 400

    captain_markers = {'C', '©', 'Ⓒ', '✪', '★'}
    marker_chars = [
        c for c in chars
        if c['text'] in captain_markers
        and c['x0'] > 550
        and roster_y_start - 5 < c['top'] < roster_y_end + 5
    ]

    x_split = 680
    for mc in marker_chars:
        side = 'A' if mc['x0'] < x_split else 'B'
        digit_chars = sorted(
            [c for c in chars
             if abs(c['top'] - mc['top']) < 6
             and c['text'].isdigit()
             and mc['x0'] - 20 < c['x0'] < mc['x0'] + 20
             and c is not mc],
            key=lambda c: c['x0'],
        )
        num = ''.join(c['text'] for c in digit_chars[:2])
        if num:
            if side == 'A' and not cap_a:
                cap_a = num
            elif side == 'B' and not cap_b:
                cap_b = num

    return cap_a, cap_b
