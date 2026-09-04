"""
Utilitaires liés aux matchs pour l'interface web.

Contient la construction des données de simulation, l'évolution de scores,
et la hiérarchie des niveaux de volley.
"""

from typing import Optional, Any

from pyvolley.analysis.joueur_stats import build_set_timeline
from pyvolley.shared.helpers import normalize_numero


def _build_player_identity_lookup(match_db) -> dict[str, dict[str, dict[str, str]]]:
    lookup: dict[str, dict[str, dict[str, str]]] = {"A": {}, "B": {}}

    for participation in (getattr(match_db, "participations", None) or []):
        side = None
        if participation.equipe_id == getattr(match_db, "equipe_a_id", None):
            side = "A"
        elif participation.equipe_id == getattr(match_db, "equipe_b_id", None):
            side = "B"
        if side is None:
            continue

        numero_raw = (participation.numero_maillot or "").strip()
        numero_norm = normalize_numero(numero_raw)
        if not numero_norm:
            continue

        joueur = getattr(participation, "joueur", None)
        lookup[side][numero_norm] = {
            "team": side,
            "numero": numero_raw or numero_norm,
            "nom": getattr(joueur, "nom", "") if joueur else "",
            "prenom": getattr(joueur, "prenom", "") if joueur else "",
        }

    return lookup


def _get_player_at_position_at_score(td, position: int, at_score_sum: int) -> Optional[str]:
    """Numéro du joueur à une position en appliquant les changements jusqu'au score donné."""
    if not td or not td.formation:
        return None

    current = td.formation.as_list()[position - 1]
    changements = sorted(
        td.changements,
        key=lambda c: (c.score_a or 0) + (c.score_b or 0),
    )

    for ch in changements:
        ch_score = (ch.score_a or 0) + (ch.score_b or 0)
        if ch.position == position and ch_score <= at_score_sum:
            current = ch.joueur_entrant

    return current


def _resolve_server_identity(core_set, turn, lookup: dict[str, dict[str, dict[str, str]]]) -> dict[str, str]:
    td = core_set.team_data(turn.team)
    score_sum_start = (turn.score_a_start or 0) + (turn.score_b_start or 0)
    numero_raw = _get_player_at_position_at_score(td, turn.position, score_sum_start)
    numero_norm = normalize_numero(numero_raw)

    if numero_norm and numero_norm in lookup.get(turn.team, {}):
        return dict(lookup[turn.team][numero_norm])

    fallback = {
        "team": turn.team,
        "numero": numero_raw or numero_norm or "",
        "nom": "",
        "prenom": "",
    }
    return fallback


def build_simulation_data(
    match, participants_a, participants_b, officiels_a, officiels_b
) -> dict:
    """Construit les données JSON pour le visualiseur de simulation embarqué."""
    equipe_a_name = match.equipe_a.nom if match.equipe_a else "Équipe A"
    equipe_b_name = match.equipe_b.nom if match.equipe_b else "Équipe B"

    # Joueurs
    joueurs_a = [
        {
            "numero": p.numero_maillot or "?",
            "nom": p.joueur.nom if p.joueur else "?",
            "prenom": p.joueur.prenom if p.joueur else "",
            "est_capitaine": p.est_capitaine,
            "est_libero": p.est_libero,
        }
        for p in participants_a
    ]
    joueurs_b = [
        {
            "numero": p.numero_maillot or "?",
            "nom": p.joueur.nom if p.joueur else "?",
            "prenom": p.joueur.prenom if p.joueur else "",
            "est_capitaine": p.est_capitaine,
            "est_libero": p.est_libero,
        }
        for p in participants_b
    ]

    # Officiels
    off_a = [{"role": o.role, "nom": o.nom, "prenom": o.prenom} for o in officiels_a]
    off_b = [{"role": o.role, "nom": o.nom, "prenom": o.prenom} for o in officiels_b]

    # Arbitres
    arbitres = [
        {
            "nom": am.arbitre.nom if am.arbitre else "?",
            "prenom": am.arbitre.prenom if am.arbitre else "",
            "role": am.role,
        }
        for am in (match.arbitrages or [])
    ]

    # Sets
    sets_data = []
    for s in match.sets or []:
        set_entry = {
            "numero": s.numero,
            "score_a": s.score_a or 0,
            "score_b": s.score_b or 0,
            "heure_debut": s.heure_debut,
            "heure_fin": s.heure_fin,
            "duree_minutes": s.duree_minutes,
            "service_initial": s.service_initial,
            "services_a": s.services_a or {},
            "services_b": s.services_b or {},
            "formation_a": {},
            "formation_b": {},
            "changements_a": [],
            "changements_b": [],
            "timeouts_a": [],
            "timeouts_b": [],
        }

        for f in s.formations or []:
            key = f"formation_{f.equipe.lower()}"
            set_entry[key] = {
                f"position_{i}": getattr(f, f"position_{i}", "") or ""
                for i in range(1, 7)
            }

        for c in s.changements or []:
            entry = {
                "joueur_entrant": c.joueur_entrant,
                "joueur_sortant": c.joueur_sortant,
                "position": c.position,
                "score_a": c.score_a,
                "score_b": c.score_b,
            }
            if c.equipe == "A":
                set_entry["changements_a"].append(entry)
            else:
                set_entry["changements_b"].append(entry)

        for t in s.timeouts or []:
            entry = {"score_a": t.score_a, "score_b": t.score_b}
            if t.equipe == "A":
                set_entry["timeouts_a"].append(entry)
            else:
                set_entry["timeouts_b"].append(entry)

        sets_data.append(set_entry)

    # Sanctions
    sanctions = [
        {
            "type": s.type_sanction,
            "equipe": s.equipe,
            "set_numero": s.set_numero,
            "joueur_numero": s.joueur_numero,
            "score_a": s.score_a,
            "score_b": s.score_b,
        }
        for s in (match.sanctions or [])
    ]

    return {
        "code_match": match.code_match,
        "date": str(match.date_match) if match.date_match else "",
        "lieu": match.salle or "",
        "salle": match.salle or "",
        "competition": match.competition.nom if match.competition else "",
        "journee": match.journee or "",
        "duree_totale": match.duree_totale or "",
        "equipe_a": {"nom": equipe_a_name, "joueurs": joueurs_a, "officiels": off_a},
        "equipe_b": {"nom": equipe_b_name, "joueurs": joueurs_b, "officiels": off_b},
        "sets_a": match.sets_equipe_a,
        "sets_b": match.sets_equipe_b,
        "vainqueur": match.vainqueur or "",
        "sets": sets_data,
        "arbitres": arbitres,
        "sanctions": sanctions,
    }


def build_match_score_evolution(matchs, equipe) -> list[dict[str, Any]]:
    """Construit la série chronologique des scores de matchs d'une équipe.

    Chaque point représente un match joué avec le score du point de vue de
    l'équipe, son résultat (V/D), l'adversaire et l'URL de navigation.
    """
    points: list[dict[str, Any]] = []

    for m in matchs:
        if not m.match_joue or not m.date_match:
            continue

        is_team_a = m.equipe_a_id == equipe.id
        if not is_team_a and m.equipe_b_id != equipe.id:
            continue

        sets_for = m.sets_equipe_a if is_team_a else m.sets_equipe_b
        sets_against = m.sets_equipe_b if is_team_a else m.sets_equipe_a
        if sets_for is None or sets_against is None:
            continue

        opponent = m.equipe_b if is_team_a else m.equipe_a
        won = sets_for > sets_against

        points.append(
            {
                "date": str(m.date_match),
                "adversaire": opponent.nom if opponent else "?",
                "resultat": "V" if won else "D",
                "score": f"{sets_for}-{sets_against}",
                "sets_for": int(sets_for),
                "sets_against": int(sets_against),
                "match_id": int(m.id),
                "match_url": f"/matchs/{m.id}",
                "competition": m.competition.nom if m.competition else "",
            }
        )

    points.sort(key=lambda p: (p["date"], p["match_id"]))
    return points


def build_niveau_evolution(matchs, equipe) -> list[dict[str, Any]]:
    """Alias de compatibilité vers la série d'évolution des scores."""
    return build_match_score_evolution(matchs, equipe)


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _safe_int(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _team_advantage(score_a: int, score_b: int, team: str) -> int:
    diff = score_a - score_b
    return diff if team == "A" else -diff


def _point_at_or_before(points: list[dict[str, Any]], x_value: int) -> dict[str, Any]:
    if not points:
        return {"x": 0, "score_a": 0, "score_b": 0, "y": 0}

    selected = points[0]
    for point in points:
        point_x = int(point.get("x") or 0)
        if point_x <= x_value:
            selected = point
            continue
        break
    return selected


def _points_in_window(points: list[dict[str, Any]], start_x: int, end_x: int) -> list[dict[str, Any]]:
    return [
        p
        for p in points
        if start_x < int(p.get("x") or 0) <= end_x and p.get("winner") in {"A", "B"}
    ]


def _impact_polarity_label(score: float) -> str:
    if score >= 12:
        return "positif"
    if score <= -12:
        return "negatif"
    return "neutre"


def _impact_strength_label(score_abs: float) -> str:
    if score_abs >= 65:
        return "fort"
    if score_abs >= 38:
        return "modere"
    if score_abs >= 18:
        return "leger"
    return "faible"


def _analyze_coach_decision_event(
    points: list[dict[str, Any]],
    event: dict[str, Any],
    set_numero: int,
    event_index: int,
    team_names: dict[str, str],
) -> Optional[dict[str, Any]]:
    team = str(event.get("team") or "").upper()
    decision_type = str(event.get("type") or "").lower()
    if team not in {"A", "B"} or decision_type not in {"timeout", "sub"}:
        return None
    if not points:
        return None

    total_points = int(points[-1].get("x") or 0)
    event_x = int(event.get("x") or 0)
    event_x = max(0, min(event_x, total_points))

    point_at_event = _point_at_or_before(points, event_x)
    score_a = _safe_int(
        event.get("score_a") if event.get("score_a") is not None else point_at_event.get("score_a"),
    )
    score_b = _safe_int(
        event.get("score_b") if event.get("score_b") is not None else point_at_event.get("score_b"),
    )

    target_window = max(4, min(12, int(round(max(1, total_points) * 0.18))))
    window_before = min(target_window, event_x)
    window_after = min(target_window, max(0, total_points - event_x))

    before_start_x = event_x - window_before
    after_end_x = event_x + window_after

    before_points = _points_in_window(points, before_start_x, event_x)
    after_points = _points_in_window(points, event_x, after_end_x)

    before_count = len(before_points)
    after_count = len(after_points)
    before_wins = sum(1 for p in before_points if p.get("winner") == team)
    after_wins = sum(1 for p in after_points if p.get("winner") == team)

    before_rate = (before_wins / before_count) if before_count > 0 else 0.5
    after_rate = (after_wins / after_count) if after_count > 0 else 0.5

    point_before_start = _point_at_or_before(points, before_start_x)
    point_after_end = _point_at_or_before(points, after_end_x)

    adv_before_start = _team_advantage(
        int(point_before_start.get("score_a") or 0),
        int(point_before_start.get("score_b") or 0),
        team,
    )
    adv_at_event = _team_advantage(score_a, score_b, team)
    adv_after_end = _team_advantage(
        int(point_after_end.get("score_a") or 0),
        int(point_after_end.get("score_b") or 0),
        team,
    )

    slope_before = (adv_at_event - adv_before_start) / max(1, before_count)
    slope_after = (adv_after_end - adv_at_event) / max(1, after_count)

    delta_rate_pct = (after_rate - before_rate) * 100.0
    delta_slope = slope_after - slope_before
    delta_adv = adv_after_end - adv_at_event

    score_gap = abs(score_a - score_b)
    closeness = _clamp(1.0 - (score_gap / 10.0), 0.0, 1.0)
    set_progress = _clamp(event_x / max(1, total_points), 0.0, 1.0)
    sample_coverage = _clamp(
        (before_count + after_count) / float(max(1, target_window * 2)),
        0.0,
        1.0,
    )

    swing_norm = delta_adv / max(2.0, target_window * 0.8)
    raw_score = (
        ((after_rate - before_rate) * 72.0)
        + (delta_slope * 42.0)
        + (swing_norm * 24.0)
    )

    adaptive_factor = 0.75 + (0.35 * closeness) + (0.25 * set_progress)
    stability_factor = 0.55 + (0.45 * sample_coverage)
    impact_score = _clamp(raw_score * adaptive_factor * stability_factor, -100.0, 100.0)

    polarity = _impact_polarity_label(impact_score)
    strength = _impact_strength_label(abs(impact_score))
    confidence_pct = round((0.45 + (0.55 * sample_coverage)) * 100.0, 1)

    decision_id = f"S{set_numero}-{team}-{decision_type.upper()}-{event_index:02d}"
    decision = {
        "id": decision_id,
        "event_index": event_index,
        "set_numero": set_numero,
        "team": team,
        "team_name": team_names.get(team, f"Équipe {team}"),
        "type": decision_type,
        "type_label": "Changement" if decision_type == "sub" else "Temps mort",
        "score_a": score_a,
        "score_b": score_b,
        "x": event_x,
        "context": {
            "set_total_points": total_points,
            "window_target_points": target_window,
            "window_before_points": before_count,
            "window_after_points": after_count,
            "score_gap_abs": score_gap,
            "set_progress_pct": round(set_progress * 100.0, 1),
        },
        "trend_before": {
            "win_rate_pct": round(before_rate * 100.0, 1),
            "slope": round(slope_before, 3),
            "advantage_delta": round(adv_at_event - adv_before_start, 2),
            "advantage_at_event": round(float(adv_at_event), 2),
        },
        "trend_after": {
            "win_rate_pct": round(after_rate * 100.0, 1),
            "slope": round(slope_after, 3),
            "advantage_delta": round(adv_after_end - adv_at_event, 2),
            "advantage_at_window_end": round(float(adv_after_end), 2),
        },
        "trend_delta": {
            "win_rate_pct": round(delta_rate_pct, 1),
            "slope": round(delta_slope, 3),
            "advantage": round(float(delta_adv), 2),
        },
        "impact_score": round(impact_score, 1),
        "impact_label": polarity,
        "impact_strength": strength,
        "confidence_pct": confidence_pct,
        "adaptive_factor": round(adaptive_factor, 3),
    }

    if decision_type == "sub":
        decision["entrant"] = event.get("entrant")
        decision["sortant"] = event.get("sortant")

    return decision


def _build_set_coach_decisions(
    points: list[dict[str, Any]],
    events: list[dict[str, Any]],
    set_numero: int,
    team_names: dict[str, str],
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for sorted_index, event in enumerate(events, start=1):
        event_index = _safe_int(event.get("event_index")) or sorted_index
        decision = _analyze_coach_decision_event(points, event, set_numero, event_index, team_names)
        if decision is None:
            continue
        decisions.append(decision)

    return sorted(
        decisions,
        key=lambda item: (
            int(item.get("x") or 0),
            0 if item.get("type") == "timeout" else 1,
            int(item.get("event_index") or 0),
        ),
    )


def _build_coach_decision_summary(
    decisions: list[dict[str, Any]],
    team_names: dict[str, str],
) -> dict[str, Any]:
    ordered_decisions = sorted(
        decisions,
        key=lambda item: (
            int(item.get("set_numero") or 0),
            int(item.get("x") or 0),
            0 if item.get("type") == "timeout" else 1,
            int(item.get("event_index") or 0),
        ),
    )

    by_team: dict[str, dict[str, Any]] = {}
    for side in ("A", "B"):
        team_decisions = [d for d in ordered_decisions if d.get("team") == side]
        scores = [float(d.get("impact_score") or 0.0) for d in team_decisions]
        avg_score = round((sum(scores) / len(scores)), 1) if scores else 0.0
        avg_delta = round(
            sum(float(d.get("trend_delta", {}).get("win_rate_pct") or 0.0) for d in team_decisions) / len(team_decisions),
            1,
        ) if team_decisions else 0.0

        best = max(team_decisions, key=lambda item: float(item.get("impact_score") or 0.0), default=None)
        worst = min(team_decisions, key=lambda item: float(item.get("impact_score") or 0.0), default=None)

        by_team[side] = {
            "team": side,
            "team_name": team_names.get(side, f"Équipe {side}"),
            "count": len(team_decisions),
            "positive": sum(1 for score in scores if score >= 12),
            "negative": sum(1 for score in scores if score <= -12),
            "neutral": sum(1 for score in scores if -12 < score < 12),
            "average_impact_score": avg_score,
            "average_trend_delta_win_rate_pct": avg_delta,
            "best_decision_id": best.get("id") if best else None,
            "worst_decision_id": worst.get("id") if worst else None,
        }

    all_scores = [float(d.get("impact_score") or 0.0) for d in ordered_decisions]
    average_score = round((sum(all_scores) / len(all_scores)), 1) if all_scores else 0.0
    score_spread = round((max(all_scores) - min(all_scores)), 1) if all_scores else 0.0

    top_impacts = sorted(ordered_decisions, key=lambda item: abs(float(item.get("impact_score") or 0.0)), reverse=True)[:5]

    return {
        "total_decisions": len(ordered_decisions),
        "total_substitutions": sum(1 for d in ordered_decisions if d.get("type") == "sub"),
        "total_timeouts": sum(1 for d in ordered_decisions if d.get("type") == "timeout"),
        "average_impact_score": average_score,
        "score_spread": score_spread,
        "by_team": by_team,
        "top_impacts": top_impacts,
        "decisions": ordered_decisions,
    }


def _build_fallback_points_from_events(set_db, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a synthetic point timeline from score landmarks when service timeline is missing."""
    set_numero = _safe_int(getattr(set_db, "numero", 0))
    final_a = _safe_int(getattr(set_db, "score_a", 0))
    final_b = _safe_int(getattr(set_db, "score_b", 0))

    landmarks: list[tuple[int, int]] = [(0, 0)]
    for event in sorted(
        events,
        key=lambda item: (
            _safe_int(item.get("x")),
            0 if item.get("type") == "timeout" else 1,
            _safe_int(item.get("event_index")),
        ),
    ):
        score_a = _safe_int(event.get("score_a"))
        score_b = _safe_int(event.get("score_b"))
        if score_a < 0 or score_b < 0:
            continue
        landmarks.append((score_a, score_b))

    landmarks.append((final_a, final_b))

    point_index = 0
    current_a = 0
    current_b = 0
    points: list[dict[str, Any]] = [{"x": 0, "y": 0, "score_a": 0, "score_b": 0, "set_numero": set_numero}]

    def _append_point(winner: str) -> None:
        nonlocal point_index, current_a, current_b
        point_index += 1
        if winner == "A":
            current_a += 1
        else:
            current_b += 1
        points.append(
            {
                "x": point_index,
                "y": current_a - current_b,
                "score_a": current_a,
                "score_b": current_b,
                "winner": winner,
                "phase": "fallback",
                "set_numero": set_numero,
                "server": None,
            }
        )

    for target_a, target_b in landmarks[1:]:
        if target_a < current_a or target_b < current_b:
            continue

        remaining_a = target_a - current_a
        remaining_b = target_b - current_b

        while remaining_a > 0 or remaining_b > 0:
            if remaining_b == 0:
                winner = "A"
            elif remaining_a == 0:
                winner = "B"
            elif remaining_a == remaining_b:
                winner = "A" if point_index % 2 == 0 else "B"
            else:
                winner = "A" if remaining_a > remaining_b else "B"

            _append_point(winner)

            if winner == "A":
                remaining_a -= 1
            else:
                remaining_b -= 1

    while current_a < final_a:
        _append_point("A")
    while current_b < final_b:
        _append_point("B")

    return points


def build_momentum_data(match_db, match_core) -> dict[str, Any]:
    """Construit les données de momentum à partir de la timeline service-order.

    Le calcul est aligné avec ``analysis.joueur_stats.build_set_timeline``.
    """
    team_a_name = match_db.equipe_a.nom if match_db.equipe_a else "Équipe A"
    team_b_name = match_db.equipe_b.nom if match_db.equipe_b else "Équipe B"
    team_names = {"A": team_a_name, "B": team_b_name}
    player_lookup = _build_player_identity_lookup(match_db)

    core_sets_by_num = {s.numero: s for s in (match_core.sets or [])}
    sets_payload: list[dict[str, Any]] = []
    coach_decisions_all: list[dict[str, Any]] = []

    for set_db in sorted((match_db.sets or []), key=lambda s: s.numero):
        core_set = core_sets_by_num.get(set_db.numero)
        turns = build_set_timeline(core_set) if core_set else []

        events: list[dict[str, Any]] = []
        event_counter = 0
        for timeout in (set_db.timeouts or []):
            if timeout.score_a is None or timeout.score_b is None:
                continue
            event_counter += 1
            events.append(
                {
                    "type": "timeout",
                    "team": timeout.equipe,
                    "score_a": timeout.score_a,
                    "score_b": timeout.score_b,
                    "x": timeout.score_a + timeout.score_b,
                    "y": timeout.score_a - timeout.score_b,
                    "event_index": event_counter,
                }
            )

        for change in (set_db.changements or []):
            if change.score_a is None or change.score_b is None:
                continue
            event_counter += 1
            events.append(
                {
                    "type": "sub",
                    "team": change.equipe,
                    "score_a": change.score_a,
                    "score_b": change.score_b,
                    "x": change.score_a + change.score_b,
                    "y": change.score_a - change.score_b,
                    "entrant": change.joueur_entrant,
                    "sortant": change.joueur_sortant,
                    "event_index": event_counter,
                }
            )

        events.sort(key=lambda item: (item["x"], 0 if item["type"] == "timeout" else 1))

        score_a = 0
        score_b = 0
        point_index = 0
        points: list[dict[str, Any]] = [{"x": 0, "y": 0, "score_a": 0, "score_b": 0}]

        used_fallback = not (turns and core_set)
        if turns and core_set:
            for turn in turns:
                server_info = _resolve_server_identity(core_set, turn, player_lookup)
                service_points = max(0, int(turn.points_scored or 0))
                for _ in range(service_points):
                    point_index += 1
                    if turn.team == "A":
                        score_a += 1
                    else:
                        score_b += 1
                    points.append(
                        {
                            "x": point_index,
                            "y": score_a - score_b,
                            "score_a": score_a,
                            "score_b": score_b,
                            "winner": turn.team,
                            "phase": "service",
                            "set_numero": set_db.numero,
                            "server": server_info,
                        }
                    )

                if not turn.is_set_winner:
                    point_index += 1
                    if turn.team == "A":
                        score_b += 1
                        winner = "B"
                    else:
                        score_a += 1
                        winner = "A"
                    points.append(
                        {
                            "x": point_index,
                            "y": score_a - score_b,
                            "score_a": score_a,
                            "score_b": score_b,
                            "winner": winner,
                            "phase": "sideout",
                            "set_numero": set_db.numero,
                            "server": server_info,
                        }
                    )
        else:
            points = _build_fallback_points_from_events(set_db, events)

        set_coach_decisions = _build_set_coach_decisions(points, events, set_db.numero, team_names)
        coach_decisions_all.extend(set_coach_decisions)

        decisions_by_event_index = {
            int(decision.get("event_index") or 0): decision
            for decision in set_coach_decisions
        }
        for event in events:
            decision = decisions_by_event_index.get(int(event.get("event_index") or 0))
            if decision is None:
                continue
            event["decision_id"] = decision.get("id")
            event["impact_score"] = decision.get("impact_score")
            event["impact_label"] = decision.get("impact_label")
            event["confidence_pct"] = decision.get("confidence_pct")
            event["trend_delta_win_rate_pct"] = decision.get("trend_delta", {}).get("win_rate_pct")

        sets_payload.append(
            {
                "numero": set_db.numero,
                "is_fallback": used_fallback,
                "score_a_final": set_db.score_a or score_a,
                "score_b_final": set_db.score_b or score_b,
                "points": points,
                "events": events,
                "coach_decisions": set_coach_decisions,
            }
        )

    coach_analysis = _build_coach_decision_summary(coach_decisions_all, team_names)

    return {
        "teams": {"A": team_a_name, "B": team_b_name},
        "sets": sets_payload,
        "coach_analysis": coach_analysis,
    }
