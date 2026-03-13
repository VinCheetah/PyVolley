"""
Construction des arbres de bracket pour les compétitions jeunes.

Supporte deux formats :
- Standard : QF → SF → Finale + classement 9-12
- Challenge : Poules de brassage → cross-brackets croisés
"""

from collections import defaultdict


def _winner_loser(m):
    """Retourne (winner_id, loser_id) pour un match joué."""
    if not m.match_joue:
        return None, None
    sa, sb = (m.sets_equipe_a or 0), (m.sets_equipe_b or 0)
    if sa > sb:
        return m.equipe_a_id, m.equipe_b_id
    return m.equipe_b_id, m.equipe_a_id


def build_bracket_tree(bracket_matchs_sorted: list) -> dict | None:
    """Build structured bracket tree from 12 sorted matches (3 rounds × 4).

    Returns a dict with upper/lower QF, SF, final, bronze, consolation &
    placement matches, properly mapped by team flow analysis.
    """
    if len(bracket_matchs_sorted) < 12:
        return None

    round1 = bracket_matchs_sorted[0:4]  # QF
    round2 = bracket_matchs_sorted[4:8]  # SF + consolation
    round3 = bracket_matchs_sorted[8:12]  # Finals + placement

    # ── QF results ──
    qf_winners: dict[int, int] = {}
    qf_losers: dict[int, int] = {}
    for i, m in enumerate(round1):
        w, l = _winner_loser(m)
        if w:
            qf_winners[i] = w
        if l:
            qf_losers[i] = l

    qf_winner_set = set(qf_winners.values())
    qf_loser_set = set(qf_losers.values())

    # ── Classify R2 as SF or consolation ──
    sf_matches: list = []
    consolation_matches: list = []
    for m in round2:
        teams = {m.equipe_a_id, m.equipe_b_id}
        if teams <= qf_winner_set:
            sf_matches.append(m)
        elif teams <= qf_loser_set:
            consolation_matches.append(m)
        else:
            sf_matches.append(m)  # fallback

    # ── Map QF → SF by team tracking ──
    qf_to_sf: dict[int, int] = {}
    for si, sf in enumerate(sf_matches):
        sf_teams = {sf.equipe_a_id, sf.equipe_b_id}
        for qi, wid in qf_winners.items():
            if wid in sf_teams:
                qf_to_sf[qi] = si

    upper_qf_idx = sorted(qi for qi, si in qf_to_sf.items() if si == 0)
    lower_qf_idx = sorted(qi for qi, si in qf_to_sf.items() if si == 1)
    if len(upper_qf_idx) != 2:
        upper_qf_idx, lower_qf_idx = [0, 1], [2, 3]

    # ── Map consolation to QF pairs (by losers) ──
    upper_consolation = lower_consolation = None
    upper_losers = {qf_losers.get(i) for i in upper_qf_idx} - {None}
    lower_losers = {qf_losers.get(i) for i in lower_qf_idx} - {None}
    for c in consolation_matches:
        c_teams = {c.equipe_a_id, c.equipe_b_id}
        if c_teams <= upper_losers:
            upper_consolation = c
        elif c_teams <= lower_losers:
            lower_consolation = c

    # ── Classify R3 by team provenance ──
    sf_w_set, sf_l_set = set(), set()
    for m in sf_matches:
        w, l = _winner_loser(m)
        if w:
            sf_w_set.add(w)
        if l:
            sf_l_set.add(l)

    c_w_set, c_l_set = set(), set()
    for m in consolation_matches:
        w, l = _winner_loser(m)
        if w:
            c_w_set.add(w)
        if l:
            c_l_set.add(l)

    final_match = bronze_match = place_5_6 = place_7_8 = None
    for m in round3:
        teams = {m.equipe_a_id, m.equipe_b_id}
        if teams <= sf_w_set:
            final_match = m
        elif teams <= sf_l_set:
            bronze_match = m
        elif teams <= c_w_set:
            place_5_6 = m
        elif teams <= c_l_set:
            place_7_8 = m

    return {
        "qf_upper": [round1[i] for i in upper_qf_idx],
        "qf_lower": [round1[i] for i in lower_qf_idx],
        "sf_upper": sf_matches[0] if sf_matches else None,
        "sf_lower": sf_matches[1] if len(sf_matches) > 1 else None,
        "final": final_match,
        "bronze": bronze_match,
        "consolation_upper": upper_consolation,
        "consolation_lower": lower_consolation,
        "place_5_6": place_5_6,
        "place_7_8": place_7_8,
    }


def build_challenge_bracket(cross_poules_data: list) -> dict | None:
    """Build challenge bracket from 2 cross-bracket poules.

    Challenge format: 2 brassage pools of 4 → 2 cross-bracket rounds.
    Round 1 (lower code poule) = 4 semi-finals.
    Round 2 (higher code poule) = 4 placement finals.

    Returns dict with ``upper`` and ``lower`` mini-brackets, each having
    ``semi1``, ``semi2``, ``final``, ``bronze`` match objects.
    """
    if len(cross_poules_data) != 2:
        return None

    sorted_cross = sorted(cross_poules_data, key=lambda p: p["poule_code"])
    semis_matchs = sorted(
        sorted_cross[0]["matchs"], key=lambda m: m.code_match or ""
    )
    finals_matchs = sorted(
        sorted_cross[1]["matchs"], key=lambda m: m.code_match or ""
    )

    # Map semi match → (winner_id, loser_id)
    semi_wl: dict[int, tuple] = {}
    for sm in semis_matchs:
        w, l = _winner_loser(sm)
        semi_wl[sm.id] = (w, l)

    # For each finals match, find which semi matches' WINNERS appear in it
    winner_feeds: dict[int, list] = defaultdict(list)
    for fm in finals_matchs:
        fm_teams = {fm.equipe_a_id, fm.equipe_b_id}
        for sm in semis_matchs:
            w, _ = semi_wl.get(sm.id, (None, None))
            if w and w in fm_teams:
                winner_feeds[fm.id].append(sm)

    # Group: finals matchs pairing two semi-winners vs two semi-losers
    mini_brackets = []
    used_finals: set[int] = set()

    for fm in finals_matchs:
        if fm.id in used_finals:
            continue
        if fm.id in winner_feeds and len(winner_feeds[fm.id]) == 2:
            pair_semis = winner_feeds[fm.id]
            pair_losers = set()
            for sm in pair_semis:
                _, l = semi_wl.get(sm.id, (None, None))
                if l:
                    pair_losers.add(l)

            loser_fm = None
            for ofm in finals_matchs:
                if ofm.id != fm.id and ofm.id not in used_finals:
                    ofm_teams = {ofm.equipe_a_id, ofm.equipe_b_id}
                    if ofm_teams <= pair_losers:
                        loser_fm = ofm
                        break

            mini_brackets.append(
                {
                    "semi1": pair_semis[0],
                    "semi2": pair_semis[1],
                    "final": fm,
                    "bronze": loser_fm,
                }
            )
            used_finals.add(fm.id)
            if loser_fm:
                used_finals.add(loser_fm.id)

    if len(mini_brackets) != 2:
        return None

    mini_brackets.sort(key=lambda mb: mb["final"].code_match or "")

    return {
        "lower": mini_brackets[0],  # places 5-8
        "upper": mini_brackets[1],  # places 1-4
        "semis_poule": sorted_cross[0],
        "finals_poule": sorted_cross[1],
    }
