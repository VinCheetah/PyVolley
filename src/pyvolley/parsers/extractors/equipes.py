"""
Extraction des données d'équipe depuis la feuille de match.

Responsable de : noms d'équipe, joueurs, libéros, capitaines, officiels,
récupération des joueurs manquants (feuille dupliquée).
"""

from __future__ import annotations

import re
import logging
from collections import defaultdict
from typing import Optional, Any

from pyvolley.core.models import Joueur, Officiel, Set
from pyvolley.parsers.constants import (
    JOUEUR_PATTERN, JOUEUR_GLUED_PATTERN, JOUEUR_NO_LICENCE_PATTERN,
)
from pyvolley.parsers.utils import (
    split_nom_prenom, clean_team_name, normalize_name,
)

logger = logging.getLogger(__name__)


_TEAM_NAME_DOUBLE_LETTER_PATTERN = re.compile(
    r'^([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ])\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ])',
)
_TEAM_NAME_PREFIX_PATTERN = re.compile(
    r'^((?:[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]\s+)+)([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]{2,})',
)
_TEAM_NAME_SINGLE_LETTER_PATTERN = re.compile(
    r'^[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]\s+(?=[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]{2,})',
)

_LIBEROS_ROW_PATTERN = re.compile(
    r'L\s*I\s*B\s*E\s*R\s*O\s*S|L\d*I\d*B\d*E?\d*R\d*O\d*S',
    re.IGNORECASE,
)
_LIBEROS_CLEAN_SPLIT_PATTERN = re.compile(
    r'L\s*I\s*B\s*E\s*R\s*O\s*S',
    re.IGNORECASE,
)
_LIBEROS_GARBLED_PATTERN = re.compile(
    r'(\d*)L\d*I\d*B\d*E?\d*R\d*O\d*S',
    re.IGNORECASE,
)
_LIBEROS_TRAILING_GARBLED_PATTERN = re.compile(
    r'\d{3,}L\d*I\d*B\d*E?\d*R\d*O\d*S$',
)
_LIBEROS_HEADER_GARBLED_PATTERN = re.compile(r'^LIBER\d*O?\d*S$')
_LIBEROS_HEADER_INLINE_PATTERN = re.compile(
    r'^LIBER\d*O?\d*S$',
    re.IGNORECASE,
)
_DIGITS_LEADING_ALPHA_PATTERN = re.compile(r'^\d{4,}[A-Z]')


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
        first_match = _TEAM_NAME_DOUBLE_LETTER_PATTERN.match(val)
        if first_match:
            m = _TEAM_NAME_PREFIX_PATTERN.match(val)
            if m:
                prefix = m.group(1).replace(' ', '')
                val = prefix + ' ' + val[m.end(1):].strip()
        else:
            single = _TEAM_NAME_SINGLE_LETTER_PATTERN.match(val)
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

        # Détection de la ligne LIBEROS : propre ou garbled
        is_liberos_row = bool(_LIBEROS_ROW_PATTERN.search(row_text))
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
            cross_target = joueurs_b if cell_idx < mid else joueurs_a

            if is_liberos_row:
                _parse_liberos_merged_cell(cs, target, cross_target)
            else:
                dup_count = _parse_player_cell(cs, target)
                if dup_count > 0:
                    duplication_detected = True

    return joueurs_a, joueurs_b, duplication_detected


def _parse_liberos_merged_cell(
    cs: str,
    target: list[Joueur],
    cross_target: list[Joueur] | None = None,
) -> None:
    """Extrait les joueurs depuis une cellule fusionnée LIBEROS.

    Gère :
    - Le texte propre ``LIBEROS  09 DUPONT JEAN 1234567``
    - Le texte garbled ``23128L3I1BER1O2S DEBEAUMOREL CLAIRE 1796348``
      où les derniers chiffres de la licence précédente et le numéro
      du libéro sont intercalés avec les lettres de LIBEROS.

    Parameters:
        cs: Le texte de la cellule.
        target: Liste des joueurs de l'équipe associée à cette cellule.
        cross_target: Liste des joueurs de l'AUTRE équipe (pour les cas
            garbled de type 2 où le libéro après le marqueur appartient
            à l'équipe adverse).
    """
    if cross_target is None:
        cross_target = target

    # ── Détection du marqueur LIBEROS (propre ou garbled) ──
    # Pattern propre : L I B E R O S éventuellement espacé
    clean_split = _LIBEROS_CLEAN_SPLIT_PATTERN.split(cs)
    if len(clean_split) > 1:
        # Cas propre : traiter les parties avant/après LIBEROS
        for part in clean_split:
            part = part.strip()
            if not part:
                continue
            cleaned = re.sub(r'^\d+\s*', '', part)
            if cleaned:
                _add_joueur(cleaned, target, est_libero=True)
            _add_joueur(part, target, est_libero=True)
        return

    # ── Cas garbled : chiffres intercalés avec LIBEROS ──
    # Ex: "LIBER2O9S CARMONA LUBIN 2777789"
    # Ex: "23128L3I1BER1O2S DEBEAUMOREL CLAIRE 1796348"
    # Ex: "10 ROCHET JULIEN 22425L4I5BER0O9S CHAREYRON LUCAS 1837707"
    garbled_match = _LIBEROS_GARBLED_PATTERN.search(cs)
    if garbled_match:
        leading_digits = garbled_match.group(1)
        before = cs[:garbled_match.start()].strip()
        after = cs[garbled_match.end():].strip()

        # Partie avant : potentiel dernier joueur normal (non-libéro)
        if before:
            _add_joueur(before, target)

        # Déterminer l'équipe du libéro « after » :
        # Type 2 : chiffres de tête >= 5 (fragment de licence) →
        #          le libéro après le garble appartient à l'AUTRE équipe
        # Type 1 : pas de chiffres de tête → même équipe
        is_type2 = len(leading_digits) >= 5
        libero_target = cross_target if is_type2 else target

        # Partie après : libéro(s)
        if after:
            # Tenter d'extraire le numéro du libéro depuis le garble
            # Les chiffres dans le garble peuvent contenir le numéro
            garble_text = garbled_match.group(0)
            # Chiffres APRÈS les leading_digits (dans le corps du garble)
            body = garble_text[len(leading_digits):]
            digits_in_body = re.findall(r'\d', body)
            libero_num = None
            if digits_in_body:
                if len(digits_in_body) >= 2:
                    libero_num = ''.join(digits_in_body[-2:])
                    libero_num = libero_num.lstrip('0') or '0'
                else:
                    libero_num = digits_in_body[-1]

            # Essayer de parser la partie après comme un joueur complet
            if not _add_joueur(after, libero_target, est_libero=True):
                # Sinon, ajouter le numéro extrait + nom après
                if libero_num:
                    full_line = f"{libero_num} {after}"
                    _add_joueur(full_line, libero_target, est_libero=True)
        return

    # ── Fallback : traiter comme une cellule de joueurs quelconque ──
    for line in cs.split('\n'):
        line = line.strip()
        if line and 'LIBEROS' not in line.upper():
            _add_joueur(line, target, est_libero=True)


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


def _add_joueur(
    line: str,
    target: list[Joueur],
    *,
    est_libero: bool = False,
) -> bool:
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
            est_libero=est_libero,
        )
        if not any(j.numero == numero and j.licence == licence for j in target):
            target.append(joueur)
        elif est_libero:
            # Marquer le joueur existant comme libéro
            for j in target:
                if j.numero == numero and j.licence == licence:
                    j.est_libero = True
                    break
        return True

    m2 = JOUEUR_NO_LICENCE_PATTERN.match(line)
    if m2:
        numero = m2.group(1)
        nom_prenom = m2.group(2).strip()
        nom, prenom = split_nom_prenom(nom_prenom)
        joueur = Joueur(
            numero=numero, nom=nom, prenom=prenom, licence="0",
            est_libero=est_libero,
        )
        if not any(j.numero == numero for j in target):
            target.append(joueur)
        elif est_libero:
            for j in target:
                if j.numero == numero:
                    j.est_libero = True
                    break
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


def correct_team_assignment(
    joueurs_a: list[Joueur],
    joueurs_b: list[Joueur],
    sets: list[Set],
) -> None:
    """Corrige l'affectation d'équipe des joueurs à partir des formations.

    Les feuilles dupliquées/garbled peuvent assigner un joueur à la
    mauvaise équipe (tout le contenu du LIBEROS row finit dans cell 0
    → équipe A). Cette fonction utilise les formations de chaque set
    pour détecter et corriger ces erreurs.

    Limitations :
    - Ne déplace PAS les joueurs marqués ``est_libero=True`` (les
      libéros n'apparaissent souvent pas dans les formations).
    - Ne déplace PAS si le numéro existe dans les formations des
      DEUX équipes (ambiguïté, ex: même numéro dans les 2 équipes).
    - Requiert au moins 2 sets avec formation pour être fiable.

    Modifie les listes en place.
    """

    def _norm(n: str) -> str:
        return n.lstrip('0') or '0'

    # Construire les ensembles de numéros réellement utilisés par chaque équipe
    used_a: set[str] = set()
    used_b: set[str] = set()
    for s in sets:
        if s.formation_a:
            for num in s.formation_a.as_list():
                if num:
                    used_a.add(_norm(num))
        if s.formation_b:
            for num in s.formation_b.as_list():
                if num:
                    used_b.add(_norm(num))
        if s.equipe_a:
            for ch in s.equipe_a.changements:
                for num in [ch.joueur_entrant, ch.joueur_sortant]:
                    if num:
                        used_a.add(_norm(num))
        if s.equipe_b:
            for ch in s.equipe_b.changements:
                for num in [ch.joueur_entrant, ch.joueur_sortant]:
                    if num:
                        used_b.add(_norm(num))

    if not used_a and not used_b:
        return

    # Collecter les numéros présents dans les DEUX rosters
    nums_in_a = {_norm(j.numero) for j in joueurs_a if j.numero}
    nums_in_b = {_norm(j.numero) for j in joueurs_b if j.numero}

    # Déplacer les joueurs mal assignés
    to_move_a_to_b: list[Joueur] = []
    to_move_b_to_a: list[Joueur] = []

    for j in joueurs_a:
        if j.est_libero:
            continue  # Les libéros ne sont pas dans les formations
        n = _norm(j.numero) if j.numero else ''
        if not n:
            continue
        # Ne pas déplacer si le numéro existe déjà dans l'autre équipe
        if n in nums_in_b:
            continue
        in_a = n in used_a
        in_b = n in used_b
        if in_b and not in_a:
            to_move_a_to_b.append(j)

    for j in joueurs_b:
        if j.est_libero:
            continue
        n = _norm(j.numero) if j.numero else ''
        if not n:
            continue
        if n in nums_in_a:
            continue
        in_a = n in used_a
        in_b = n in used_b
        if in_a and not in_b:
            to_move_b_to_a.append(j)

    for j in to_move_a_to_b:
        joueurs_a.remove(j)
        joueurs_b.append(j)
        logger.debug(
            "Joueur #%s %s réassigné A→B (formation)",
            j.numero, j.nom,
        )

    for j in to_move_b_to_a:
        joueurs_b.remove(j)
        joueurs_a.append(j)
        logger.debug(
            "Joueur #%s %s réassigné B→A (formation)",
            j.numero, j.nom,
        )


# =====================================================================
# Helpers pour la gestion de duplication
# =====================================================================


def _is_garbled_word(text: str) -> bool:
    """Détecte un mot garbled (superposition de deux lignes dupliquées).

    Les feuilles dupliquées produisent des mots comme ``CJUALRIMA``,
    ``AELMICOEREL``, ``22787478768897`` qui sont le résultat de la
    superposition de deux lignes de texte identiques décalées.
    """
    if not text or len(text) < 4:
        return False
    # Texte purement numérique très long (2 licences superposées)
    if text.isdigit() and len(text) > 9:
        return True
    # Texte alphanumérique mixte suspect (début ou fin avec des chiffres intercalés)
    if _DIGITS_LEADING_ALPHA_PATTERN.match(text) and len(text) > 10:
        return True
    # Noms garbled : ratio voyelles/consonnes anormal, alternance inhabituelles
    alpha = re.sub(r'[^A-Za-z]', '', text)
    if len(alpha) >= 8:
        # Si plus de 60% de caractères uniques sont des lettres majuscules
        # et la longueur est suspecte vs un nom normal
        upper = sum(1 for c in alpha if c.isupper())
        if upper == len(alpha) and len(alpha) > 12:
            # Vérifier si c'est un motif de superposition (AABB)
            # Les mots garbled ont souvent des paires de lettres : CCHHEENN
            pairs = sum(1 for i in range(len(alpha) - 1) if alpha[i] == alpha[i + 1])
            if pairs >= len(alpha) * 0.3:
                return True
    return False


def _dedup_word_lines(
    lines: dict[int, list],
) -> dict[int, list]:
    """Déduplique les lignes de mots qui ont le même contenu textuel.

    Les feuilles dupliquées produisent deux lignes identiques à des
    positions y très proches. On garde la première occurrence.
    """
    seen_content: set[str] = set()
    result: dict[int, list] = {}
    for key in sorted(lines):
        content = ' '.join(
            w['text'] for w in sorted(lines[key], key=lambda w: w['x0'])
        )
        if content in seen_content:
            continue
        seen_content.add(content)
        result[key] = lines[key]
    return result


# =====================================================================
# Libéros (positionnement spatial)
# =====================================================================


def extract_liberos(
    words: list,
) -> tuple[list[Joueur], list[Joueur]]:
    """Extrait les libéros depuis la section LIBEROS du PDF.

    Détecte le header LIBEROS même garbled (ex: ``LIBER2O9S``,
    ``23128L3I1BER1O2S``) et utilise les positions spatiales pour
    séparer équipe A / équipe B.

    Pour les feuilles garbled/dupliquées, utilise une stratégie de
    restriction par colonne :
    - Type 1 (LIBER…S sans chiffres de tête) : le libéro Team A
      est déjà extrait par la table → on cherche seulement Team B.
    - Type 2 (chiffres+L…S) : le libéro Team B est déjà extrait
      par la table → on cherche seulement Team A.
    """
    liberos_a: list[Joueur] = []
    liberos_b: list[Joueur] = []

    # Chercher le header LIBEROS — propre ou garbled
    lib_header = None
    garbled = False
    for w in words:
        if w['x0'] <= 500:
            continue
        text_up = w['text'].upper()
        # Propre
        if text_up == 'LIBEROS':
            lib_header = w
            break
        # Garbled : commence par LIBER et finit par S, avec chiffres intercalés
        if _LIBEROS_HEADER_GARBLED_PATTERN.match(text_up):
            lib_header = w
            garbled = True
            break
        # Garbled type 2 : chiffres de licence + LIBEROS intercalé
        if _LIBEROS_TRAILING_GARBLED_PATTERN.search(text_up):
            lib_header = w
            garbled = True
            break

    if not lib_header:
        return liberos_a, liberos_b

    off_header = next(
        (w for w in words if w['text'].upper() == 'OFFICIELS' and w['x0'] > 500),
        None,
    )

    if not garbled:
        # ── Cas propre : extraction normale par zone spatiale ──
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
            if _is_garbled_word(w['text']):
                continue
            key = round(w['top'] / 3) * 3
            if w['x0'] < x_thresh:
                lines_a[key].append(w)
            else:
                lines_b[key].append(w)

        lines_a = _dedup_word_lines(lines_a)
        lines_b = _dedup_word_lines(lines_b)

        for key in sorted(lines_a):
            if j := _build_libero(lines_a[key]):
                liberos_a.append(j)
        for key in sorted(lines_b):
            if j := _build_libero(lines_b[key]):
                liberos_b.append(j)

    else:
        # ── Cas garbled : extraction sélective par colonne ──
        # La ligne du header est traitée par _parse_liberos_merged_cell.
        # On cherche les lignes PROPRES en dessous pour les libéros
        # non encore trouvés.
        #
        # Stratégie : déterminer le « type » du garble pour choisir
        # quelle colonne (Team A / Team B) contient les données fiables.
        #
        # Type 1 (LIBER2O9S) : pas de chiffres avant LIBER
        #   → le libéro de Team A est déjà extrait par la table
        #   → on cherche seulement Team B (x > 700) dans la zone
        #
        # Type 2 (23128L3I1BER1O2S) : chiffres de licence avant LIBER
        #   → le libéro de Team B est déjà extrait par la table
        #   → on cherche seulement Team A (x < 700) dans la zone
        header_y = lib_header['top']
        y_end = off_header['top'] if off_header else header_y + 35

        # Déterminer le type de garble
        garble_text = lib_header['text'].upper()
        garble_m = _LIBEROS_GARBLED_PATTERN.search(garble_text)
        leading_digits = garble_m.group(1) if garble_m else ''
        is_type2 = len(leading_digits) >= 5

        zone_words = [
            w for w in words
            if header_y + 1 <= w['top'] <= y_end and w['x0'] > 500
        ]

        x_thresh = 700
        lines_a: dict[int, list] = defaultdict(list)
        lines_b: dict[int, list] = defaultdict(list)

        for w in zone_words:
            # Exclure les mots garbled
            if _is_garbled_word(w['text']):
                continue
            # Exclure les fragments char-par-char
            if len(w['text']) == 1 and w['text'].isalpha():
                continue

            key = round(w['top'] / 3) * 3
            if w['x0'] < x_thresh:
                lines_a[key].append(w)
            else:
                lines_b[key].append(w)

        lines_a = _dedup_word_lines(lines_a)
        lines_b = _dedup_word_lines(lines_b)

        if is_type2:
            # Type 2 : Team B libéro extrait par table, chercher Team A
            for key in sorted(lines_a):
                if j := _build_libero(lines_a[key]):
                    liberos_a.append(j)
            # Aussi extraire Team B si la ligne contient les DEUX côtés
            # (ligne propre avec données complètes des deux équipes)
            for key in sorted(lines_b):
                if key in lines_a:
                    # Ligne qui a aussi des données Team A → ligne propre
                    if j := _build_libero(lines_b[key]):
                        liberos_b.append(j)
        else:
            # Type 1 : Team A libéro extrait par table, chercher Team B
            for key in sorted(lines_b):
                if j := _build_libero(lines_b[key]):
                    liberos_b.append(j)
            # Aussi extraire Team A si la ligne contient les DEUX côtés
            for key in sorted(lines_a):
                if key in lines_b:
                    if j := _build_libero(lines_a[key]):
                        liberos_a.append(j)

    return liberos_a, liberos_b


def _build_libero(line_words: list) -> Optional[Joueur]:
    """Construit un Joueur libéro depuis une liste de mots spatiaux."""
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
        elif t.upper() not in ('LIBEROS',) and not _LIBEROS_HEADER_INLINE_PATTERN.match(t):
            name_parts.append(t)
    if not numero or not licence or not name_parts:
        return None
    nom, prenom = split_nom_prenom(' '.join(name_parts))
    return Joueur(
        numero=numero, nom=nom, prenom=prenom,
        licence=licence, est_libero=True,
    )


def mark_liberos(joueurs: list[Joueur], liberos: list[Joueur]) -> None:
    """Marque les joueurs qui sont des libéros."""
    lib_ids = {(lib.numero, lib.licence) for lib in liberos}
    lib_nums = {lib.numero for lib in liberos}
    for j in joueurs:
        if (j.numero, j.licence) in lib_ids or j.numero in lib_nums:
            j.est_libero = True


def merge_liberos(joueurs: list[Joueur], liberos: list[Joueur]) -> list[Joueur]:
    """Fusionne les libéros dans la liste des joueurs, sans doublons.

    Gère les cas de chevauchement entre joueurs, libéros et entraîneurs
    en utilisant le couple (numéro, licence) comme clé d'unicité.
    Les joueurs « placeholder » (licence=0, nom=Inconnu) sont remplacés
    par les vraies données du libéro si disponibles.
    """
    existing_ids = {(j.numero, j.licence) for j in joueurs}
    existing_nums = {j.numero for j in joueurs}
    merged = list(joueurs)

    for lib in liberos:
        if (lib.numero, lib.licence) in existing_ids:
            # Le joueur existe déjà — juste marquer comme libéro
            for j in merged:
                if j.numero == lib.numero and j.licence == lib.licence:
                    j.est_libero = True
                    break
        elif lib.numero in existing_nums:
            # Même numéro mais licence différente : vérifier si c'est un placeholder
            for j in merged:
                if j.numero == lib.numero and j.licence == '0' and j.nom == 'Inconnu':
                    # Remplacer le placeholder par les vraies données
                    j.nom = lib.nom
                    j.prenom = lib.prenom
                    j.licence = lib.licence
                    j.est_libero = True
                    break
            else:
                # Numéro identique mais données différentes : garder les deux
                lib.est_libero = True
                merged.append(lib)
        else:
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
    images: Optional[list],
    chars: Optional[list],
    words: list,
    tidx: dict,
    page: Optional[Any] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Détecte les capitaines (3 méthodes en cascade).

    1. Table SIGNATURES
    2. Cercles-images dans le roster
    3. Marqueurs caractères (C, ©)

    Si ``images`` / ``chars`` sont ``None``, ils sont chargés à la demande
    depuis ``page`` uniquement si nécessaire.
    """
    cap_a, cap_b = _capitaines_from_signatures(tidx)
    if cap_a and cap_b:
        return cap_a, cap_b

    if images is None and page is not None:
        images = page.images
    if chars is None and page is not None:
        chars = page.chars

    safe_images = images or []
    safe_chars = chars or []

    if safe_images and safe_chars:
        ca2, cb2 = _capitaines_from_images(safe_images, safe_chars, words)
        cap_a = cap_a or ca2
        cap_b = cap_b or cb2

    if not cap_a or not cap_b:
        ca3, cb3 = _capitaines_from_chars(safe_chars, words)
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
