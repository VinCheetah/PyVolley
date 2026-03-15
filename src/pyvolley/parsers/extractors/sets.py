"""
Extraction des sections SET et construction des objets Set.

Responsable de : sections SET (formations, changements, timeouts, service),
table RESULTATS, construction finale des Sets avec mapping left/right → A/B.
"""

from __future__ import annotations

import re
import logging
from typing import Optional

from pyvolley.core.models import (
    Set, SetTeamData, Formation, TimeOut, Changement,
)
from pyvolley.parsers.constants import ROWS_PER_SET
from pyvolley.parsers.utils import (
    team_similarity, best_team_match, team_matches, parse_time_str,
)

logger = logging.getLogger(__name__)


_SET_SECTION_PATTERN = re.compile(r'S\s*E\s*T\s*(\d)')
_SET_HEADER_TIME_PATTERN = re.compile(r'(Début|Fin):\s*(\d{1,2}:\d{2})')
_SET_HEADER_TIME_PARTIAL_PATTERN = re.compile(r'(Début|Fin):\s*(\d{1,2}):?')
_SET_HEADER_NEXT_HOUR_PATTERN = re.compile(r'^(\d{1,2})\b')
_SET_SUB_SCORE_PATTERN = re.compile(r'^(\d{1,2}):(\d{1,2})$')
_ROMAN_MAP = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6}


# =====================================================================
# Parse toutes les sections SET
# =====================================================================


def extract_all_sets(tidx: dict) -> list[dict]:
    """Parse tous les sets depuis les tables main et secondary.

    Architecture FFVB :
        - Table main     : Sets 1, 3, 5  (positions ~0, ~10, ~20)
        - Table secondary : Sets 2, 4   (positions ~0, ~10)

    Certains vieux PDFs (pré-2024) ont un bug d'extraction où le chiffre
    '5' est lu comme '1' par pdfplumber.  On corrige via la position
    ordinale dans chaque table.
    """
    EXPECTED_MAIN = {0: 1, 1: 3, 2: 5}
    EXPECTED_SEC = {0: 2, 1: 4}

    sets: list[dict] = []
    for key, expected_map in [('main', EXPECTED_MAIN), ('secondary', EXPECTED_SEC)]:
        tbl = tidx.get(key)
        if not tbl:
            continue
        sections = _find_set_sections(tbl)
        sections.sort(key=lambda x: x[1])
        for ordinal, (raw_num, start_row) in enumerate(sections):
            set_num = expected_map.get(ordinal, raw_num)
            if raw_num != set_num:
                logger.debug(
                    "SET number corrected: raw=%d → expected=%d "
                    "(table=%s, ordinal=%d, row=%d)",
                    raw_num, set_num, key, ordinal, start_row,
                )
            sd = _parse_set_section(tbl, start_row, set_num)
            if sd:
                sets.append(sd)
    sets.sort(key=lambda s: s['numero'])
    return sets


def _find_set_sections(table: list) -> list[tuple[int, int]]:
    sections: list[tuple[int, int]] = []
    for i, row in enumerate(table):
        if not row:
            continue
        for cell in row:
            if not cell:
                continue
            cs = str(cell).replace('\n', ' ').strip()
            if m := _SET_SECTION_PATTERN.search(cs):
                sections.append((int(m.group(1)), i))
                break
    return sections


def _parse_set_section(
    table: list, start: int, set_num: int,
) -> Optional[dict]:
    """Parse une section de set (10 lignes dans la table).

    Rows :
      +0 : Header (noms d'équipe, heures, service S/R)
      +1 : Positions (I II III IV V VI)
      +2 : Formation de départ (numéros)
      +3 : Remplaçants (Joueur N°)
      +4 : Score au remplacement
      +5 : Score supplémentaire
      +6-9 : Tours au service + Timeouts
    """
    sd: dict = {
        'numero': set_num,
        'heure_debut': None, 'heure_fin': None,
        'service_initial_side': None,
        'left_team_name': None, 'right_team_name': None,
        'formation_left': None, 'formation_right': None,
        'changements_left': [], 'changements_right': [],
        'timeouts_left': [], 'timeouts_right': [],
        'services_left': {}, 'services_right': {},
    }

    if start + ROWS_PER_SET > len(table):
        return sd

    n_cols = len(table[start]) if table[start] else 0

    # Row +0 : Header
    _parse_set_header(table[start], sd, n_cols)

    # Row +1 : Position columns — detect 3-block structure for set 5
    pos_left, pos_right, _pos_left_dup = _find_position_columns(
        table[start + 1], n_cols,
    )

    # Row +2 : Formations
    sd['formation_left'] = _extract_formation(table[start + 2], pos_left)
    sd['formation_right'] = _extract_formation(table[start + 2], pos_right)

    # Rows +3..+5 : Substitutions
    _parse_substitutions(table, start, pos_left, pos_right, sd)

    # Rows +6..+9 : Service & timeouts
    _parse_service_timeouts(table, start, pos_left, pos_right, sd, n_cols)

    return sd


# =====================================================================
# Détails set header
# =====================================================================


def _parse_set_header(row: list, sd: dict, n_cols: int) -> None:
    """Parse le header du set pour extraire heures, noms, service."""
    if not row:
        return

    team_cells: list[tuple[int, str]] = []
    for i, cell in enumerate(row):
        if not cell:
            continue
        cs = str(cell).strip()
        if len(cs) < 5:
            continue
        if 'Début' in cs or 'Fin' in cs or 'Pts' in cs:
            team_cells.append((i, cs))

    cells_to_process = team_cells[:2] if len(team_cells) >= 2 else team_cells

    if len(cells_to_process) >= 2:
        mid_col = (cells_to_process[0][0] + cells_to_process[1][0]) // 2
    else:
        mid_col = n_cols // 2

    for i, cs in cells_to_process:
        side = 'left' if i <= mid_col else 'right'

        name = re.split(r'\s+(?:Début|Fin):', cs)[0].strip()
        if name:
            if side == 'left':
                sd['left_team_name'] = name
            else:
                sd['right_team_name'] = name

        if tm := _SET_HEADER_TIME_PATTERN.search(cs):
            if tm.group(1) == 'Début':
                sd['heure_debut'] = tm.group(2)
            else:
                sd['heure_fin'] = tm.group(2)
        elif tp := _SET_HEADER_TIME_PARTIAL_PATTERN.search(cs):
            partial = tp.group(2).rstrip(':')
            completed = _complete_time(row, i, partial)
            if completed:
                if tp.group(1) == 'Début':
                    sd['heure_debut'] = completed
                else:
                    sd['heure_fin'] = completed

        stripped = cs.rstrip()
        if stripped.endswith(' S'):
            sd['service_initial_side'] = side
        elif stripped.endswith(' R'):
            sd['service_initial_side'] = 'right' if side == 'left' else 'left'


def _complete_time(row: list, col_i: int, partial: str) -> Optional[str]:
    for off in range(1, 4):
        j = col_i + off
        if j < len(row) and row[j]:
            cs = str(row[j]).strip()
            if m := _SET_HEADER_NEXT_HOUR_PATTERN.match(cs):
                return f"{partial}:{m.group(1).zfill(2)}"
    return None


# =====================================================================
# Colonnes de position (I–VI)
# =====================================================================


def _find_position_columns(
    header_row: Optional[list], n_cols: int,
) -> tuple[list[int], list[int], list[int]]:
    """Trouve les colonnes I..VI pour gauche, droite et éventuel 3ème bloc.

    Le SET 5 a une structure «gauche-droite-gauche» avec 3 blocs de
    positions I-VI (18 colonnes au total).

    Returns:
        ``(pos_left, pos_right, pos_left_dup)``
    """
    if not header_row:
        return [], [], []

    hits: list[tuple[int, int]] = []
    for i, cell in enumerate(header_row):
        if not cell:
            continue
        cell_text = str(cell).strip()
        if cell_text in _ROMAN_MAP:
            hits.append((i, _ROMAN_MAP[cell_text]))

    if len(hits) >= 18:
        # ── 3 blocs de I-VI : structure SET 5 ──
        hits.sort(key=lambda x: x[0])
        gaps = [
            (hits[k + 1][0] - hits[k][0], k) for k in range(len(hits) - 1)
        ]
        gaps.sort(reverse=True)
        split_indices = sorted([gaps[0][1], gaps[1][1]])

        block1 = hits[:split_indices[0] + 1]
        block2 = hits[split_indices[0] + 1:split_indices[1] + 1]
        block3 = hits[split_indices[1] + 1:]

        left = sorted(block1, key=lambda x: x[1])
        right = sorted(block2, key=lambda x: x[1])
        left_dup = sorted(block3, key=lambda x: x[1])

        logger.debug(
            "SET 5 detected: 3 blocks of positions — "
            "left=%s, right=%s, left_dup=%s (ignored)",
            [i for i, _ in left[:6]],
            [i for i, _ in right[:6]],
            [i for i, _ in left_dup[:6]],
        )

        return (
            [i for i, _ in left[:6]],
            [i for i, _ in right[:6]],
            [i for i, _ in left_dup[:6]],
        )

    if len(hits) >= 12:
        hits.sort(key=lambda x: x[0])
        max_gap, split_idx = 0, 5
        for k in range(len(hits) - 1):
            gap = hits[k + 1][0] - hits[k][0]
            if gap > max_gap:
                max_gap, split_idx = gap, k

        left = sorted(hits[:split_idx + 1], key=lambda x: x[1])
        right = sorted(hits[split_idx + 1:], key=lambda x: x[1])
        return [i for i, _ in left[:6]], [i for i, _ in right[:6]], []

    # Fallback heuristique
    if n_cols >= 40:
        return [13, 15, 18, 20, 22, 24], [31, 33, 35, 37, 39, 41], []
    elif n_cols >= 25:
        return [1, 3, 5, 7, 9, 11], [14, 16, 18, 20, 22, 24], []
    return [], [], []


# =====================================================================
# Formation de départ
# =====================================================================


def _extract_formation(
    row: Optional[list], cols: list[int],
) -> Optional[Formation]:
    if not row or len(cols) < 6:
        return None
    vals: list[Optional[str]] = []
    for c in cols:
        if c < len(row) and row[c]:
            v = str(row[c]).strip()
            if v.isdigit() and len(v) <= 2:
                vals.append(v)
            elif v.lstrip('-').isdigit() and v.startswith('-'):
                vals.append(None)
            else:
                vals.append(None)
        else:
            vals.append(None)
    if sum(1 for v in vals if v) < 4:
        return None
    return Formation(
        position_1=vals[0], position_2=vals[1], position_3=vals[2],
        position_4=vals[3],
        position_5=vals[4] if len(vals) > 4 else None,
        position_6=vals[5] if len(vals) > 5 else None,
    )


# =====================================================================
# Remplacements (rows +3..+5)
# =====================================================================


def _parse_substitutions(
    table: list, start: int,
    pos_left: list[int], pos_right: list[int], sd: dict,
) -> None:
    """Parse les remplacements (rows +3 à +5).

    Un changement lie deux joueurs pour tout le set.
    - Row +3 : numéro du remplaçant (entrant)
    - Row +4 : score du changement ALLER
    - Row +5 : score du changement RETOUR (aller-retour)

    Les scores sont en format demandeur:adversaire → convertis en left:right.
    """
    n = len(table)
    sub_row = table[start + 3] if start + 3 < n else None
    score_row_aller = table[start + 4] if start + 4 < n else None
    score_row_retour = table[start + 5] if start + 5 < n else None

    if not sub_row:
        return

    for cols, changes, form, is_right in [
        (pos_left, sd['changements_left'], sd['formation_left'], False),
        (pos_right, sd['changements_right'], sd['formation_right'], True),
    ]:
        for pos_idx, col in enumerate(cols):
            if col >= len(sub_row) or not sub_row[col]:
                continue
            entrant = str(sub_row[col]).strip()
            if not entrant or not entrant.isdigit():
                continue

            sortant = None
            if form:
                form_list = form.as_list()
                if pos_idx < len(form_list) and form_list[pos_idx]:
                    sortant = form_list[pos_idx]

            # Changement ALLER
            sa_aller, sb_aller = None, None
            if score_row_aller and col < len(score_row_aller) and score_row_aller[col]:
                sm = _SET_SUB_SCORE_PATTERN.match(str(score_row_aller[col]).strip())
                if sm:
                    sa_aller, sb_aller = int(sm.group(1)), int(sm.group(2))
                    if is_right:
                        sa_aller, sb_aller = sb_aller, sa_aller

            changes.append({
                'joueur_entrant': entrant,
                'joueur_sortant': sortant,
                'position': pos_idx + 1,
                'score_left': sa_aller,
                'score_right': sb_aller,
            })

            # Changement RETOUR
            if score_row_retour and col < len(score_row_retour) and score_row_retour[col]:
                sm = _SET_SUB_SCORE_PATTERN.match(str(score_row_retour[col]).strip())
                if sm:
                    sa_ret, sb_ret = int(sm.group(1)), int(sm.group(2))
                    if is_right:
                        sa_ret, sb_ret = sb_ret, sa_ret
                    changes.append({
                        'joueur_entrant': sortant or entrant,
                        'joueur_sortant': entrant,
                        'position': pos_idx + 1,
                        'score_left': sa_ret,
                        'score_right': sb_ret,
                    })


# =====================================================================
# Service & Timeouts (rows +6..+9)
# =====================================================================


def _parse_service_timeouts(
    table: list, start: int,
    pos_left: list[int], pos_right: list[int],
    sd: dict, n_cols: int,
) -> None:
    """Parse les tours au service, scores de service et timeouts."""
    n = len(table)

    if pos_right:
        mid_col = pos_right[0]
    elif pos_left:
        mid_col = pos_left[-1] + 3
    else:
        mid_col = n_cols // 2

    pos_left_set = set(pos_left)
    pos_right_set = set(pos_right)

    for offset in range(4):
        idx = start + 6 + offset
        if idx >= n:
            break
        row = table[idx]
        if not row:
            continue

        for pos_idx, col in enumerate(pos_left):
            if col < len(row) and row[col]:
                val = str(row[col]).strip()
                if val.isdigit():
                    pos_num = pos_idx + 1
                    sd['services_left'].setdefault(pos_num, []).append(int(val))

        for pos_idx, col in enumerate(pos_right):
            if col < len(row) and row[col]:
                val = str(row[col]).strip()
                if val.isdigit():
                    pos_num = pos_idx + 1
                    sd['services_right'].setdefault(pos_num, []).append(int(val))

        for i, cell in enumerate(row):
            if not cell or i in pos_left_set or i in pos_right_set:
                continue
            cs = str(cell).strip()
            if cs == 'T':
                side = 'left' if i < mid_col else 'right'
                for d in range(1, 4):
                    nxt = idx + d
                    if nxt >= n or nxt >= start + ROWS_PER_SET:
                        break
                    nr = table[nxt]
                    if not nr or i >= len(nr) or not nr[i]:
                        continue
                    sm = _SET_SUB_SCORE_PATTERN.match(str(nr[i]).strip())
                    if sm:
                        sa, sb = int(sm.group(1)), int(sm.group(2))
                        if side == 'right':
                            sa, sb = sb, sa
                        if side == 'left':
                            sd['timeouts_left'].append(
                                {'score_left': sa, 'score_right': sb},
                            )
                        else:
                            sd['timeouts_right'].append(
                                {'score_left': sa, 'score_right': sb},
                            )


# =====================================================================
# Table RESULTATS
# =====================================================================


def extract_resultats_table(
    tidx: dict,
) -> tuple[list[dict], Optional[str]]:
    """Parse la table RESULTATS pour les scores/stats par set.

    Returns ``(data_par_set, duree_totale)``.
    """
    tbl = tidx.get('results')
    if not tbl:
        return [], None

    # Durées par set
    durations: dict[int, int] = {}
    for row in tbl:
        if not row or len(row) <= 4 or not row[4]:
            continue
        for dm in re.finditer(r'(\d)\s+(\d+)\'', str(row[4])):
            durations[int(dm.group(1))] = int(dm.group(2))
        if durations:
            break

    # Durée totale
    duree_totale: Optional[str] = None
    for i, row in enumerate(tbl):
        if not row:
            continue
        rt = ' '.join(str(c) for c in row if c)
        if 'Début' in rt and 'Fin' in rt and 'Durée' in rt:
            if i + 1 < len(tbl) and tbl[i + 1]:
                for cell in tbl[i + 1]:
                    if not cell:
                        continue
                    cs = str(cell).strip()
                    if re.match(r'^\d+h\d+$', cs):
                        duree_totale = cs
                        break
                    if re.match(r"^\d+'$", cs):
                        duree_totale = cs
                        break
            break

    # Données par set
    data: list[dict] = []
    set_num = 0
    for row_idx in range(3, min(8, len(tbl))):
        row = tbl[row_idx]
        if not row:
            continue

        nums = []
        for c in row:
            if c is not None:
                s = str(c).strip().replace("'", "")
                if s.isdigit():
                    nums.append(int(s))
        if len(nums) < 3:
            continue
        if any(v > 50 for v in nums):
            continue

        set_num += 1
        d = {
            'numero': set_num,
            'timeouts_a': _safe_int(row, 0),
            'remplacements_a': _safe_int(row, 1),
            'sets_gagnes_a': _safe_int(row, 2),
            'points_a': _safe_int(row, 3),
            'duree_minutes': durations.get(set_num),
            'points_b': _safe_int(row, 6),
            'sets_gagnes_b': _safe_int(row, 7),
            'remplacements_b': _safe_int(row, 8),
            'timeouts_b': _safe_int(row, 9),
        }
        data.append(d)

    return data, duree_totale


def _safe_int(row: list, idx: int) -> Optional[int]:
    if idx >= len(row) or row[idx] is None:
        return None
    s = str(row[idx]).strip().replace("'", "")
    return int(s) if s.isdigit() else None


# =====================================================================
# Construction des Sets (cross-validation left/right → A/B)
# =====================================================================


def build_sets(
    detailed: list[dict],
    resultats: list[dict],
    resultat: dict,
    nom_a: str,
    nom_b: str,
) -> tuple[list[Set], list[str]]:
    """Construit les objets Set avec mapping left/right → A/B."""
    warnings: list[str] = []

    nb = 0
    if sc := resultat.get("score_final"):
        try:
            a, b = sc.split("/")
            nb = int(a) + int(b)
        except Exception:
            pass
    if not nb:
        scored_res = sum(
            1 for r in resultats
            if (r.get('points_a') or 0) > 0 or (r.get('points_b') or 0) > 0
        )
        scored_det = sum(
            1 for d in detailed
            if d.get('heure_debut') or d.get('formation_left')
        )
        nb = scored_res or scored_det or max(len(detailed), len(resultats), 0)
        nb = min(nb, 5)

    # ── Détection inversion colonnes RESULTATS ──
    results_swap = False
    vainqueur = resultat.get("vainqueur", "")
    if vainqueur and resultats:
        best = best_team_match(vainqueur, nom_a, nom_b)
        a_wins = best == 'A'
        b_wins = best == 'B'

        total_ga = sum(r.get('sets_gagnes_a', 0) or 0 for r in resultats)
        total_gb = sum(r.get('sets_gagnes_b', 0) or 0 for r in resultats)
        if b_wins and total_ga > total_gb:
            results_swap = True
            logger.debug(
                "Colonnes RESULTATS inversées (corrigé) : "
                "vainqueur '%s' = equipe_b, G table: A=%d B=%d",
                vainqueur, total_ga, total_gb,
            )
        elif a_wins and total_gb > total_ga:
            results_swap = True
            logger.debug(
                "Colonnes RESULTATS inversées (corrigé) : "
                "vainqueur '%s' = equipe_a, G table: A=%d B=%d",
                vainqueur, total_ga, total_gb,
            )
        elif not a_wins and not b_wins:
            if not team_matches(vainqueur, nom_a, threshold=0.40) and \
               not team_matches(vainqueur, nom_b, threshold=0.40):
                warnings.append(
                    f"Vainqueur '{vainqueur}' ne correspond ni à "
                    f"'{nom_a}' ni à '{nom_b}'"
                )

    sets: list[Set] = []
    for i in range(nb):
        sn = i + 1
        det = next((s for s in detailed if s['numero'] == sn), None)
        res = next((r for r in resultats if r.get('numero') == sn), None)

        # Scores
        if not results_swap:
            score_a = res.get('points_a') if res else None
            score_b = res.get('points_b') if res else None
        else:
            score_a = res.get('points_b') if res else None
            score_b = res.get('points_a') if res else None

        duree = None
        if res and res.get('duree_minutes'):
            duree = res['duree_minutes']

        debut_t = parse_time_str(det.get('heure_debut') if det else None)
        fin_t = parse_time_str(det.get('heure_fin') if det else None)

        # Mapping left/right → A/B
        swap = False
        left_name = det.get('left_team_name', '') if det else ''
        right_name = det.get('right_team_name', '') if det else ''
        if left_name or right_name:
            sim_no_swap = 0.0
            sim_swap = 0.0
            if left_name:
                sim_no_swap += team_similarity(left_name, nom_a)
                sim_swap += team_similarity(left_name, nom_b)
            if right_name:
                sim_no_swap += team_similarity(right_name, nom_b)
                sim_swap += team_similarity(right_name, nom_a)
            swap = sim_swap > sim_no_swap

        if det:
            if not swap:
                form_a = det['formation_left']
                form_b = det['formation_right']
                to_a_raw = det['timeouts_left']
                to_b_raw = det['timeouts_right']
                ch_a = det['changements_left']
                ch_b = det['changements_right']
                srv_a = det.get('services_left', {})
                srv_b = det.get('services_right', {})
                srv_side = det.get('service_initial_side')
                srv = 'A' if srv_side == 'left' else (
                    'B' if srv_side == 'right' else None
                )
            else:
                form_a = det['formation_right']
                form_b = det['formation_left']
                to_a_raw = det['timeouts_right']
                to_b_raw = det['timeouts_left']
                ch_a = det['changements_right']
                ch_b = det['changements_left']
                srv_a = det.get('services_right', {})
                srv_b = det.get('services_left', {})
                srv_side = det.get('service_initial_side')
                srv = 'B' if srv_side == 'left' else (
                    'A' if srv_side == 'right' else None
                )
        else:
            form_a = form_b = None
            to_a_raw = to_b_raw = []
            ch_a = ch_b = []
            srv_a = srv_b = {}
            srv = None
            if score_a is None and score_b is None:
                warnings.append(f"Set {sn}: aucune donnée de score")

        def _map_scores(
            sl: Optional[int], sr: Optional[int],
        ) -> tuple[Optional[int], Optional[int]]:
            if not swap:
                return sl, sr
            return sr, sl

        changements_a = [
            Changement(
                joueur_entrant=c['joueur_entrant'],
                joueur_sortant=c.get('joueur_sortant'),
                position=c.get('position'),
                score_a=_map_scores(c.get('score_left'), c.get('score_right'))[0],
                score_b=_map_scores(c.get('score_left'), c.get('score_right'))[1],
            ) for c in ch_a
        ]
        changements_b = [
            Changement(
                joueur_entrant=c['joueur_entrant'],
                joueur_sortant=c.get('joueur_sortant'),
                position=c.get('position'),
                score_a=_map_scores(c.get('score_left'), c.get('score_right'))[0],
                score_b=_map_scores(c.get('score_left'), c.get('score_right'))[1],
            ) for c in ch_b
        ]

        timeouts_a = [
            TimeOut(
                score_a=_map_scores(d.get('score_left'), d.get('score_right'))[0],
                score_b=_map_scores(d.get('score_left'), d.get('score_right'))[1],
            ) for d in to_a_raw
        ]
        timeouts_b = [
            TimeOut(
                score_a=_map_scores(d.get('score_left'), d.get('score_right'))[0],
                score_b=_map_scores(d.get('score_left'), d.get('score_right'))[1],
            ) for d in to_b_raw
        ]

        s = Set(
            numero=sn,
            score_a=score_a, score_b=score_b,
            debut=debut_t, fin=fin_t,
            duree_minutes=duree,
            service_initial=srv,
            equipe_a=SetTeamData(
                formation=form_a,
                timeouts=timeouts_a,
                changements=changements_a,
                services=srv_a,
            ),
            equipe_b=SetTeamData(
                formation=form_b,
                timeouts=timeouts_b,
                changements=changements_b,
                services=srv_b,
            ),
        )
        sets.append(s)

    return sets, warnings
