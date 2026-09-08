"""
Module d'extraction direct et ultra-rapide des sets (Formations I à VI, Remplacements, Temps Morts, Services).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from pyvolley.core.models import (
    Changement,
    Formation,
    Set,
    SetTeamData,
    TimeOut,
)
from pyvolley.parsers.layout_config import ParserLayoutConfig
from pyvolley.parsers.extractors.fast.resultats import SetSummary
from pyvolley.parsers.extractors.fast.utils import (
    RE_DIGITS,
    RE_SUB_SCORE,
    WordTuple,
    extract_text_in_region,
    parse_time_token,
    slice_words_in_box,
    slice_words_in_region,
)


def _extract_team_set_data(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    config: ParserLayoutConfig,
    s_num: int,
    team_key: str,  # "equipe_a" ou "equipe_b"
    is_team_a: bool,
) -> Tuple[SetTeamData, bool]:
    """
    Extrait les données d'une équipe pour un set donné :
    Formation (I..VI), Remplaçants & Scores de remplacement, Temps Morts et Rotations de service.
    Retourne (SetTeamData, has_x_in_pos1).
    """
    bboxes = config.bboxes
    prefix = f"sets/set{s_num}/{team_key}"

    starters: Dict[int, str] = {}
    changements: List[Changement] = []
    pos_boxes_x: List[Tuple[float, float]] = []
    has_x_turn1 = False

    # 1. Extraction des 6 cases de position (pos1 à pos6)
    for pos_idx in range(1, 7):
        pos_reg = bboxes.get(f"{prefix}/pos{pos_idx}")
        if not pos_reg:
            continue

        pos_boxes_x.append((pos_reg.x0 - 2.0, pos_reg.x1 + 2.0))
        p_words = slice_words_in_region(sorted_words, y0_list, pos_reg)
        if not p_words:
            continue

        p_words.sort(key=lambda w: (round(w[1] / 2.5) * 2.5, w[0]))

        start_num = ""
        sub_num = ""
        scores: List[str] = []

        for w in p_words:
            txt = w[4].strip()
            if ":" in txt or "-" in txt:
                scores.append(txt)
            elif txt.isdigit():
                if len(txt) <= 2:
                    if not start_num:
                        start_num = txt
                    elif not sub_num:
                        sub_num = txt
                elif len(txt) <= 4:
                    scores.append(txt)

        if start_num:
            starters[pos_idx] = start_num

        if sub_num and start_num and sub_num != start_num:
            # 1er changement (entrée du remplaçant)
            sc1 = scores[0] if len(scores) >= 1 else ""
            sa1, sb1 = 0, 0
            if sc1:
                m1 = RE_SUB_SCORE.search(sc1)
                if m1:
                    s_own1, s_opp1 = int(m1.group(1)), int(m1.group(2))
                    sa1 = s_own1 if is_team_a else s_opp1
                    sb1 = s_opp1 if is_team_a else s_own1

            changements.append(
                Changement(
                    joueur_entrant=sub_num,
                    joueur_sortant=start_num,
                    position=pos_idx,
                    score_a=sa1,
                    score_b=sb1,
                )
            )

            # 2e changement optionnel (retour du titulaire)
            if len(scores) >= 2:
                sc2 = scores[1]
                m2 = RE_SUB_SCORE.search(sc2)
                if m2:
                    s_own2, s_opp2 = int(m2.group(1)), int(m2.group(2))
                    sa2 = s_own2 if is_team_a else s_opp2
                    sb2 = s_opp2 if is_team_a else s_own2
                    changements.append(
                        Changement(
                            joueur_entrant=start_num,
                            joueur_sortant=sub_num,
                            position=pos_idx,
                            score_a=sa2,
                            score_b=sb2,
                        )
                    )

    # 2. Formation
    formation = Formation(
        position_1=starters.get(1),
        position_2=starters.get(2),
        position_3=starters.get(3),
        position_4=starters.get(4),
        position_5=starters.get(5),
        position_6=starters.get(6),
    ) if starters else None

    # 3. Temps Morts (Timeouts)
    timeouts: List[TimeOut] = []
    to_reg = bboxes.get(f"{prefix}/timeouts")
    if to_reg:
        to_words = slice_words_in_region(sorted_words, y0_list, to_reg)
        for w in to_words:
            txt = w[4]
            for m in RE_SUB_SCORE.finditer(txt):
                s_own, s_opp = int(m.group(1)), int(m.group(2))
                if s_own <= 45 and s_opp <= 45:
                    sa = s_own if is_team_a else s_opp
                    sb = s_opp if is_team_a else s_own
                    timeouts.append(TimeOut(score_a=sa, score_b=sb))

    # 4. Rotations de service
    services_dict: Dict[int, List[int]] = {}
    srv_reg = bboxes.get(f"{prefix}/services")
    if srv_reg:
        srv_words = slice_words_in_region(sorted_words, y0_list, srv_reg)
        if srv_words:
            if len(pos_boxes_x) < 6:
                col_w = max(1.0, (srv_reg.x1 - srv_reg.x0) / 6.0)
                pos_boxes_x = [(srv_reg.x0 + (i - 1) * col_w, srv_reg.x0 + i * col_w) for i in range(1, 7)]

            services_by_col: Dict[int, List[int]] = {i: [] for i in range(1, 7)}
            srv_words.sort(key=lambda w: (round(w[1] / 2.5) * 2.5, w[0]))

            for w in srv_words:
                txt = w[4].strip().upper()
                cx = (w[0] + w[2]) * 0.5

                if "X" in txt:
                    if pos_boxes_x and pos_boxes_x[0][0] <= cx <= pos_boxes_x[0][1]:
                        has_x_turn1 = True

                if txt.isdigit() and len(txt) <= 2:
                    val = int(txt)
                    if 0 <= val <= 99:
                        for col_idx, (cx0, cx1) in enumerate(pos_boxes_x, 1):
                            if cx0 <= cx <= cx1:
                                services_by_col[col_idx].append(val)
                                break

            services_dict = {p: sc for p, sc in services_by_col.items() if sc}

    team_data = SetTeamData(
        formation=formation,
        timeouts=timeouts,
        changements=changements,
        services=services_dict,
    )

    return team_data, has_x_turn1


def extract_fast_sets(
    sorted_words: List[WordTuple],
    y0_list: List[float],
    config: ParserLayoutConfig,
    gauche_est_equipe_a: bool,
    sets_summary: Dict[int, SetSummary],
) -> List[Set]:
    """
    Extrait l'ensemble des 5 sets joués de façon entièrement déterministe et ultra-rapide (< 1ms).
    """
    sets_list: List[Set] = []
    bboxes = config.bboxes

    for s_num in range(1, 6):
        set_summary = sets_summary.get(s_num)

        # Heures début / fin
        debut_reg = bboxes.get(f"sets/set{s_num}/debut")
        fin_reg = bboxes.get(f"sets/set{s_num}/fin")

        debut_str = extract_text_in_region(sorted_words, y0_list, debut_reg)
        fin_str = extract_text_in_region(sorted_words, y0_list, fin_reg)

        h_debut = parse_time_token(debut_str)
        h_fin = parse_time_token(fin_str)

        # Extraction des deux équipes du set
        # Dans layout_config :
        # set1 : equipe_a (gauche), equipe_b (droite)
        # set2 : equipe_b (gauche), equipe_a (droite)
        # set3 : equipe_a (gauche), equipe_b (droite)
        # set4 : equipe_b (gauche), equipe_a (droite)
        # set5 : equipe_b (gauche), equipe_a (droite)
        key_a = "equipe_a" if gauche_est_equipe_a else "equipe_b"
        key_b = "equipe_b" if gauche_est_equipe_a else "equipe_a"

        data_a, a_has_x = _extract_team_set_data(
            sorted_words, y0_list, config, s_num=s_num, team_key=key_a, is_team_a=True
        )
        data_b, b_has_x = _extract_team_set_data(
            sorted_words, y0_list, config, s_num=s_num, team_key=key_b, is_team_a=False
        )

        score_a = set_summary.points_a if set_summary else None
        score_b = set_summary.points_b if set_summary else None
        duree_min = None
        if set_summary and set_summary.duree:
            d_clean = set_summary.duree.lower().replace("min", "").replace("'", "").strip()
            if d_clean.isdigit():
                duree_min = int(d_clean)

        # Détermination du service initial
        service_initial: Optional[str] = None
        if a_has_x:
            service_initial = "B"
        elif b_has_x:
            service_initial = "A"

        # Vérification si le set a été joué
        has_formation_a = data_a.formation is not None and any(data_a.formation.as_list())
        has_formation_b = data_b.formation is not None and any(data_b.formation.as_list())
        has_scores = score_a is not None and score_b is not None

        if not (has_scores or has_formation_a or has_formation_b):
            continue

        set_obj = Set(
            numero=s_num,
            score_a=score_a,
            score_b=score_b,
            debut=h_debut,
            fin=h_fin,
            duree_minutes=duree_min,
            service_initial=service_initial,
            equipe_a=data_a,
            equipe_b=data_b,
        )
        sets_list.append(set_obj)

    return sets_list
