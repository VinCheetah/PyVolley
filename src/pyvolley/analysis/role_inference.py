"""Heuristic role inference from rotations and substitutions.

This module infers likely player roles with a flexible scoring approach.
It is intentionally tolerant to noisy/incomplete sheets:
- strong signal: synchronized opposite-position substitutions (passe-pointe)
- medium signal: libero replacement patterns
- contextual signal: role propagation from starting rotations
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from ..core.models import Match, SetTeamData
from .models import RoleInference
from .role_solver import TeamRoleSolver, extract_team_context

from pyvolley.core.constants import (
    ROLE_SETTER,
    ROLE_OPPOSITE,
    ROLE_MIDDLE,
    ROLE_OUTSIDE,
    ROLE_LIBERO,
    ALL_SPECIFIC_ROLES as ALL_ROLES,
)

_FRONT_POSITIONS = {2, 3, 4}
_BACK_POSITIONS = {1, 5, 6}


@dataclass(slots=True)
class _RoleAccumulator:
    scores: dict[str, float] = field(
        default_factory=lambda: {role: 0.0 for role in ALL_ROLES}
    )
    hints: list[str] = field(default_factory=list)

    def add(self, role: str, amount: float, hint: Optional[str] = None) -> None:
        if amount <= 0:
            return
        self.scores[role] = self.scores.get(role, 0.0) + amount
        if hint and len(self.hints) < 24:
            self.hints.append(hint)


def _norm(numero: Optional[str]) -> str:
    if numero is None:
        return ""
    return numero.lstrip("0") or "0"


def _is_opposite_position(pos_a: Optional[int], pos_b: Optional[int]) -> bool:
    if pos_a is None or pos_b is None:
        return False
    if not (1 <= pos_a <= 6 and 1 <= pos_b <= 6):
        return False
    return (pos_a - pos_b) % 6 == 3


def _opposite_position(pos: int) -> int:
    return ((pos + 2) % 6) + 1


def _find_position(formation: dict[int, str], player_numero: str) -> Optional[int]:
    for pos, numero in formation.items():
        if numero == player_numero:
            return pos
    return None


def _compact_hints(hints: list[str], max_items: int = 6) -> list[str]:
    seen: set[str] = set()
    compact: list[str] = []
    for hint in hints:
        if hint in seen:
            continue
        seen.add(hint)
        compact.append(hint)
        if len(compact) >= max_items:
            break
    return compact


def _role_score(accumulators: dict[str, _RoleAccumulator], numero: str, role: str) -> float:
    entry = accumulators.get(numero)
    if entry is None:
        return 0.0
    return entry.scores.get(role, 0.0)


def _assignment_orientation_score(
    accumulators: dict[str, _RoleAccumulator],
    setters: list[str],
    opposites: list[str],
) -> float:
    score = 0.0
    for numero in setters:
        setter_s = _role_score(accumulators, numero, ROLE_SETTER)
        opposite_s = _role_score(accumulators, numero, ROLE_OPPOSITE)
        score += setter_s - (0.55 * opposite_s)
    for numero in opposites:
        setter_s = _role_score(accumulators, numero, ROLE_SETTER)
        opposite_s = _role_score(accumulators, numero, ROLE_OPPOSITE)
        score += opposite_s - (0.55 * setter_s)
    return score


def _sharpen_setter_opposite_contrast(
    accumulators: dict[str, _RoleAccumulator],
    player_is_libero: dict[str, bool],
) -> None:
    """Reduce setter/opposite overlap to better separate both roles.

    This pass runs after primary evidence collection and applies only to
    non-libero players.
    """
    for numero, accumulator in accumulators.items():
        if player_is_libero.get(numero, False):
            continue

        setter_s = accumulator.scores.get(ROLE_SETTER, 0.0)
        opposite_s = accumulator.scores.get(ROLE_OPPOSITE, 0.0)

        if setter_s <= 0.0 or opposite_s <= 0.0:
            continue

        if setter_s >= opposite_s * 1.22:
            accumulator.scores[ROLE_OPPOSITE] *= 0.52
            accumulator.hints.append("coherence role: passeur priorise")
        elif opposite_s >= setter_s * 1.22:
            accumulator.scores[ROLE_SETTER] *= 0.52
            accumulator.hints.append("coherence role: pointu priorise")
        elif max(setter_s, opposite_s) >= 6.0:
            # Keep uncertainty but avoid fully mixed identities.
            accumulator.scores[ROLE_SETTER] *= 0.82
            accumulator.scores[ROLE_OPPOSITE] *= 0.82
            accumulator.hints.append("coherence role: inversion ambigue")


def _collect_libero_evidence(
    td: SetTeamData,
    set_numero: int,
    player_is_libero: dict[str, bool],
    accumulators: dict[str, _RoleAccumulator],
    middle_hints: dict[str, float],
) -> None:
    for ch in td.changements:
        entrant = _norm(ch.joueur_entrant)
        sortant = _norm(ch.joueur_sortant)
        position = ch.position

        if (
            entrant
            and player_is_libero.get(entrant, False)
            and sortant
            and not player_is_libero.get(sortant, False)
        ):
            if position in _BACK_POSITIONS:
                middle_hints[sortant] += 2.0
                accumulators[sortant].add(
                    ROLE_MIDDLE,
                    2.0,
                    f"sortie pour libero en zone arriere (set {set_numero})",
                )
            elif position in _FRONT_POSITIONS:
                accumulators[sortant].add(
                    ROLE_OUTSIDE,
                    0.8,
                    f"remplacement front pour libero (set {set_numero})",
                )

        if (
            sortant
            and player_is_libero.get(sortant, False)
            and entrant
            and not player_is_libero.get(entrant, False)
            and position in _FRONT_POSITIONS
        ):
            middle_hints[entrant] += 1.0
            accumulators[entrant].add(
                ROLE_MIDDLE,
                1.0,
                f"retour depuis remplacement libero (set {set_numero})",
            )


def _collect_passe_pointe_evidence(
    td: SetTeamData,
    set_numero: int,
    accumulators: dict[str, _RoleAccumulator],
    setter_opposite_pairs: dict[tuple[str, str], int],
    setter_anchor_hint: Optional[str] = None,
    opposite_anchor_hint: Optional[str] = None,
) -> None:
    by_score: dict[tuple[int, int], list] = defaultdict(list)

    for ch in td.changements:
        if ch.score_a is None or ch.score_b is None:
            continue
        by_score[(ch.score_a, ch.score_b)].append(ch)

    for (score_a, score_b), changes in by_score.items():
        if len(changes) < 2:
            continue

        for i, first in enumerate(changes):
            for second in changes[i + 1 :]:
                if not _is_opposite_position(first.position, second.position):
                    continue

                front = None
                back = None
                if first.position in _FRONT_POSITIONS and second.position in _BACK_POSITIONS:
                    front, back = first, second
                elif second.position in _FRONT_POSITIONS and first.position in _BACK_POSITIONS:
                    front, back = second, first
                if front is None or back is None:
                    continue

                front_out = _norm(front.joueur_sortant)
                front_in = _norm(front.joueur_entrant)
                back_out = _norm(back.joueur_sortant)
                back_in = _norm(back.joueur_entrant)
                hint = (
                    f"inversion passe-pointe detectee (set {set_numero}, "
                    f"score {score_a}-{score_b})"
                )
                setters_a = [n for n in (front_out, back_in) if n]
                opposites_a = [n for n in (front_in, back_out) if n]
                setters_b = [n for n in (front_in, back_out) if n]
                opposites_b = [n for n in (front_out, back_in) if n]

                use_assignment_a: Optional[bool] = None
                anchor_votes_a = 0.0
                anchor_votes_b = 0.0
                if setter_anchor_hint:
                    if setter_anchor_hint in setters_a:
                        use_assignment_a = True
                        anchor_votes_a += 1.8
                    elif setter_anchor_hint in setters_b:
                        use_assignment_a = False
                        anchor_votes_b += 1.8
                if use_assignment_a is None and opposite_anchor_hint:
                    if opposite_anchor_hint in opposites_a:
                        use_assignment_a = True
                        anchor_votes_a += 1.5
                    elif opposite_anchor_hint in opposites_b:
                        use_assignment_a = False
                        anchor_votes_b += 1.5

                dynamic_a = _assignment_orientation_score(
                    accumulators,
                    setters_a,
                    opposites_a,
                ) + anchor_votes_a
                dynamic_b = _assignment_orientation_score(
                    accumulators,
                    setters_b,
                    opposites_b,
                ) + anchor_votes_b

                if use_assignment_a is None:
                    delta = dynamic_a - dynamic_b
                    if delta >= 2.2:
                        use_assignment_a = True
                    elif delta <= -2.2:
                        use_assignment_a = False

                if use_assignment_a is None:
                    # Ambiguous direction (entry/exit can flip on reverse swap).
                    for numero in sorted(set(setters_a + setters_b)):
                        accumulators[numero].add(ROLE_SETTER, 2.2, hint)
                    for numero in sorted(set(opposites_a + opposites_b)):
                        accumulators[numero].add(ROLE_OPPOSITE, 2.2, hint)
                else:
                    chosen_setters = setters_a if use_assignment_a else setters_b
                    chosen_opposites = opposites_a if use_assignment_a else opposites_b

                    confidence_boost = 0.0
                    chosen_dynamic = dynamic_a if use_assignment_a else dynamic_b
                    alt_dynamic = dynamic_b if use_assignment_a else dynamic_a
                    if abs(chosen_dynamic - alt_dynamic) >= 3.0:
                        confidence_boost += 2.0
                    if anchor_votes_a > 0.0 or anchor_votes_b > 0.0:
                        confidence_boost += 1.2

                    for numero in chosen_setters:
                        accumulators[numero].add(ROLE_SETTER, 14.5 + confidence_boost, hint)
                    for numero in chosen_opposites:
                        accumulators[numero].add(ROLE_OPPOSITE, 14.5 + confidence_boost, hint)

                    if len(chosen_setters) >= 1 and len(chosen_opposites) >= 1:
                        setter_opposite_pairs[(chosen_setters[0], chosen_opposites[0])] += 2
                    if len(chosen_setters) >= 2 and len(chosen_opposites) >= 2:
                        setter_opposite_pairs[(chosen_setters[1], chosen_opposites[1])] += 2


def _pick_anchor(
    candidates: list[str],
    accumulators: dict[str, _RoleAccumulator],
    role: str,
    min_score: float,
) -> Optional[str]:
    if not candidates:
        return None
    best = max(candidates, key=lambda numero: accumulators[numero].scores.get(role, 0.0))
    if accumulators[best].scores.get(role, 0.0) < min_score:
        return None
    return best


def _select_setter_for_formation(
    formation: dict[int, str],
    accumulators: dict[str, _RoleAccumulator],
    player_is_libero: dict[str, bool],
    setter_anchor: Optional[str],
    opposite_anchor: Optional[str],
) -> tuple[Optional[str], float, str]:
    candidates = [
        numero
        for numero in set(formation.values())
        if numero and not player_is_libero.get(numero, False)
    ]
    if not candidates:
        return None, 0.0, ""

    if setter_anchor and setter_anchor in candidates:
        return setter_anchor, 4.0, "ancre passeur detectee"

    if opposite_anchor and opposite_anchor in candidates:
        opposite_pos = _find_position(formation, opposite_anchor)
        if opposite_pos is not None:
            deduced_setter = formation.get(_opposite_position(opposite_pos))
            if deduced_setter and not player_is_libero.get(deduced_setter, False):
                return deduced_setter, 2.8, "deduction via pointu ancre"

    best_by_score = max(
        candidates,
        key=lambda numero: accumulators[numero].scores.get(ROLE_SETTER, 0.0),
    )
    best_score = accumulators[best_by_score].scores.get(ROLE_SETTER, 0.0)
    if best_score >= 3.0:
        return best_by_score, 2.6, "coherence des remplacements"

    # Soft fallback: when no clear setter signal exists, use position 1 as hypothesis.
    pos_one = formation.get(1)
    if pos_one and not player_is_libero.get(pos_one, False):
        return pos_one, 1.4, "hypothese serveur de depart"

    return None, 0.0, ""


def _propagate_middle_outside_roles(
    set_numero: int,
    formation: dict[int, str],
    setter_pos: int,
    accumulators: dict[str, _RoleAccumulator],
    player_is_libero: dict[str, bool],
    middle_hints: dict[str, float],
) -> None:
    relative_players: dict[int, str] = {}
    for pos, player_numero in formation.items():
        if not player_numero or player_is_libero.get(player_numero, False):
            continue
        rel = (pos - setter_pos) % 6
        if rel in {1, 2, 4, 5}:
            relative_players[rel] = player_numero

    if not all(rel in relative_players for rel in (1, 2, 4, 5)):
        return

    option_a_middle = [relative_players[2], relative_players[5]]
    option_b_middle = [relative_players[1], relative_players[4]]

    def _middle_score(players: list[str]) -> float:
        return sum(
            middle_hints.get(numero, 0.0)
            + accumulators[numero].scores.get(ROLE_MIDDLE, 0.0) * 0.15
            for numero in players
        )

    score_a = _middle_score(option_a_middle)
    score_b = _middle_score(option_b_middle)

    if abs(score_a - score_b) < 0.75:
        middle_rel = (2, 5)
        outside_rel = (1, 4)
        middle_weight = 0.9
        outside_weight = 0.9
        hint = f"schema rotation ambigu (set {set_numero})"
    elif score_a >= score_b:
        middle_rel = (2, 5)
        outside_rel = (1, 4)
        middle_weight = 1.8
        outside_weight = 1.6
        hint = f"schema rotation A privilegie (set {set_numero})"
    else:
        middle_rel = (1, 4)
        outside_rel = (2, 5)
        middle_weight = 1.8
        outside_weight = 1.6
        hint = f"schema rotation B privilegie (set {set_numero})"

    for rel in middle_rel:
        numero = relative_players[rel]
        accumulators[numero].add(ROLE_MIDDLE, middle_weight, hint)
    for rel in outside_rel:
        numero = relative_players[rel]
        accumulators[numero].add(ROLE_OUTSIDE, outside_weight, hint)


def infer_team_roles(
    match: Match,
    side: str,
    player_priors: Optional[dict[str, dict[str, float]]] = None,
) -> dict[str, RoleInference]:
    """Infer likely roles for each player number of one side.

    Returns a mapping keyed by normalized jersey number.
    Uses volleyball compositional constraints, teammate rotation pairing,
    and optional player priors.
    """
    ctx = extract_team_context(match, side)
    solver = TeamRoleSolver(ctx, player_priors=player_priors)
    return solver.solve()

