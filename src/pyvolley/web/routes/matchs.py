"""
Routes web — Matchs (liste et détail).
"""

import json
from collections import defaultdict
from statistics import mean
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select, or_

from pyvolley.web.templateconfig import templates
from pyvolley.web.helpers.time_filter import build_time_filter
from pyvolley.web.helpers.match_utils import build_simulation_data, build_momentum_data
from pyvolley.shared.helpers import parse_optional_int
from pyvolley.api.dependencies import get_match_repo, get_saison_repo
from pyvolley.database.repositories import MatchRepository, SaisonRepository
from pyvolley.database.models import MatchDB, JoueurMatchStatsDB
from pyvolley.database.converters import match_db_to_core
from pyvolley.analysis.joueur_stats import build_set_timeline

router = APIRouter()


def _to_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _pct(part: float, whole: float) -> float:
    if whole <= 0:
        return 0.0
    return (part / whole) * 100.0


def _normalize_numero(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.isdigit():
        return str(int(raw))
    return raw


def _summarize_team_players(items: list[dict]) -> dict:
    if not items:
        return {
            "players": 0,
            "liberos": 0,
            "points_joues": 0,
            "points_gagnes": 0,
            "points_perdus": 0,
            "points_gagnes_service": 0,
            "services": 0,
            "max_serie": 0,
            "sets_joues": 0,
            "temps_total": 0.0,
            "temps_moyen": 0.0,
            "changements": 0,
            "temps_morts_provoques": 0,
            "sanctions": 0,
            "efficacite_pct": 0.0,
            "service_win_pct": 0.0,
            "points_gagnes_sideout": 0,
            "break_points": 0,
            "break_opportunities": 0,
            "break_point_ratio_pct": 0.0,
            "sideout_points": 0,
            "sideout_successes": 0,
            "sideout_attempts": 0,
            "sideout_efficacite_pct": 0.0,
            "first_sideout_successes": 0,
            "first_sideout_attempts": 0,
            "first_sideout_efficacite_pct": 0.0,
            "sideout_contribution_pct": 0.0,
            "service_turns": 0,
            "receiving_turns": 0,
            "sets_with_timeline": 0,
            "sets_total": 0,
            "phase_coverage_pct": 0.0,
        }

    points_joues = 0
    points_gagnes = 0
    points_perdus = 0
    points_gagnes_service = 0
    services = 0
    max_serie = 0
    sets_joues = 0
    changements = 0
    temps_morts_provoques = 0
    sanctions = 0
    liberos = 0
    temps = []

    for item in items:
        stats = item.get("stats", {})
        points_joues += _to_int(stats.get("points_joues"))
        points_gagnes += _to_int(stats.get("points_gagnes"))
        points_perdus += _to_int(stats.get("points_perdus"))
        points_gagnes_service += _to_int(stats.get("points_gagnes_service"))
        services += _to_int(stats.get("services") or stats.get("nb_services"))
        max_serie = max(max_serie, _to_int(stats.get("max_serie") or stats.get("meilleure_serie")))
        sets_joues += _to_int(stats.get("sets_joues"))
        changements += _to_int(stats.get("nb_changements_total"))
        temps_morts_provoques += _to_int(stats.get("temps_morts_provoques"))
        sanctions += len(stats.get("sanctions") or [])
        if stats.get("est_libero"):
            liberos += 1
        if stats.get("temps_jeu_estime") is not None:
            temps.append(_to_float(stats.get("temps_jeu_estime")))

    temps_total = round(sum(temps), 1)
    points_gagnes_sideout = max(0, points_gagnes - points_gagnes_service)
    return {
        "players": len(items),
        "liberos": liberos,
        "points_joues": points_joues,
        "points_gagnes": points_gagnes,
        "points_perdus": points_perdus,
        "points_gagnes_service": points_gagnes_service,
        "services": services,
        "max_serie": max_serie,
        "sets_joues": sets_joues,
        "temps_total": temps_total,
        "temps_moyen": round(mean(temps), 1) if temps else 0.0,
        "changements": changements,
        "temps_morts_provoques": temps_morts_provoques,
        "sanctions": sanctions,
        "efficacite_pct": round(_pct(points_gagnes, points_joues), 1),
        "service_win_pct": round(_pct(points_gagnes_service, services), 1),
        "points_gagnes_sideout": points_gagnes_sideout,
        "break_points": points_gagnes_service,
        "break_opportunities": services,
        "break_point_ratio_pct": round(_pct(points_gagnes_service, services), 1),
        "sideout_points": points_gagnes_sideout,
        "sideout_successes": 0,
        "sideout_attempts": 0,
        "sideout_efficacite_pct": 0.0,
        "first_sideout_successes": 0,
        "first_sideout_attempts": 0,
        "first_sideout_efficacite_pct": 0.0,
        "sideout_contribution_pct": round(_pct(points_gagnes_sideout, points_gagnes), 1),
        "service_turns": 0,
        "receiving_turns": 0,
        "sets_with_timeline": 0,
        "sets_total": 0,
        "phase_coverage_pct": 0.0,
    }


def _summarize_team_from_sets(match: MatchDB, side: str, participant_count: int = 0) -> dict:
    points_gagnes = 0
    points_perdus = 0
    services = 0
    changements = 0
    sets_joues = 0
    temps_total = 0.0

    for set_ in (match.sets or []):
        score_for = _to_int(set_.score_a if side == "A" else set_.score_b)
        score_against = _to_int(set_.score_b if side == "A" else set_.score_a)
        points_gagnes += score_for
        points_perdus += score_against
        sets_joues += 1

        if set_.duree_minutes is not None:
            temps_total += _to_float(set_.duree_minutes)

        services_dict = set_.services_a if side == "A" else set_.services_b
        if isinstance(services_dict, dict):
            services += sum(len(v) for v in services_dict.values() if isinstance(v, list))

        changements += sum(1 for c in (set_.changements or []) if c.equipe == side)

    points_joues = points_gagnes + points_perdus
    return {
        "players": participant_count,
        "liberos": 0,
        "points_joues": points_joues,
        "points_gagnes": points_gagnes,
        "points_perdus": points_perdus,
        "points_gagnes_service": 0,
        "services": services,
        "max_serie": 0,
        "sets_joues": sets_joues,
        "temps_total": round(temps_total, 1),
        "temps_moyen": round((temps_total / sets_joues), 1) if sets_joues else 0.0,
        "changements": changements,
        "temps_morts_provoques": 0,
        "sanctions": sum(1 for s in (match.sanctions or []) if s.equipe == side),
        "efficacite_pct": round(_pct(points_gagnes, points_joues), 1),
        "service_win_pct": 0.0,
        "points_gagnes_sideout": 0,
        "break_points": 0,
        "break_opportunities": services,
        "break_point_ratio_pct": 0.0,
        "sideout_points": 0,
        "sideout_successes": 0,
        "sideout_attempts": 0,
        "sideout_efficacite_pct": 0.0,
        "first_sideout_successes": 0,
        "first_sideout_attempts": 0,
        "first_sideout_efficacite_pct": 0.0,
        "sideout_contribution_pct": 0.0,
        "service_turns": 0,
        "receiving_turns": 0,
        "sets_with_timeline": 0,
        "sets_total": sets_joues,
        "phase_coverage_pct": 0.0,
    }


def _empty_phase_metrics() -> dict:
    return {
        "break_points": 0,
        "break_opportunities": 0,
        "break_point_ratio_pct": 0.0,
        "sideout_points": 0,
        "sideout_successes": 0,
        "sideout_attempts": 0,
        "sideout_efficacite_pct": 0.0,
        "first_sideout_successes": 0,
        "first_sideout_attempts": 0,
        "first_sideout_efficacite_pct": 0.0,
        "service_turns": 0,
        "receiving_turns": 0,
        "sets_with_timeline": 0,
        "sets_total": 0,
        "phase_coverage_pct": 0.0,
    }


def _compute_team_phase_metrics(match_core) -> dict[str, dict]:
    metrics = {"A": _empty_phase_metrics(), "B": _empty_phase_metrics()}
    sets = list(getattr(match_core, "sets", []) or [])
    for side in ("A", "B"):
        metrics[side]["sets_total"] = len(sets)

    for set_ in sets:
        timeline = build_set_timeline(set_)
        if not timeline:
            continue

        metrics["A"]["sets_with_timeline"] += 1
        metrics["B"]["sets_with_timeline"] += 1

        for turn in timeline:
            serving = turn.team
            receiving = "B" if serving == "A" else "A"

            break_points = _to_int(turn.points_scored)
            break_opportunities = break_points + (0 if turn.is_set_winner else 1)

            serving_bucket = metrics[serving]
            serving_bucket["break_points"] += break_points
            serving_bucket["break_opportunities"] += break_opportunities
            serving_bucket["service_turns"] += 1

            receiving_bucket = metrics[receiving]
            receiving_bucket["sideout_attempts"] += break_opportunities
            receiving_bucket["receiving_turns"] += 1
            receiving_bucket["first_sideout_attempts"] += 1

            if not turn.is_set_winner:
                receiving_bucket["sideout_successes"] += 1
                receiving_bucket["sideout_points"] += 1
                if break_points == 0:
                    receiving_bucket["first_sideout_successes"] += 1

    for side in ("A", "B"):
        bucket = metrics[side]
        bucket["break_point_ratio_pct"] = round(
            _pct(bucket["break_points"], bucket["break_opportunities"]), 1,
        )
        bucket["sideout_efficacite_pct"] = round(
            _pct(bucket["sideout_successes"], bucket["sideout_attempts"]), 1,
        )
        bucket["first_sideout_efficacite_pct"] = round(
            _pct(bucket["first_sideout_successes"], bucket["first_sideout_attempts"]), 1,
        )
        bucket["phase_coverage_pct"] = round(
            _pct(bucket["sets_with_timeline"], bucket["sets_total"]), 1,
        )

    return metrics


def _merge_phase_metrics(summary: dict, phase_metrics: dict) -> dict:
    merged = dict(summary)
    phase_metrics = phase_metrics or _empty_phase_metrics()

    has_phase_data = (
        _to_int(phase_metrics.get("sets_with_timeline")) > 0
        and (
            _to_int(phase_metrics.get("break_opportunities")) > 0
            or _to_int(phase_metrics.get("sideout_attempts")) > 0
        )
    )

    if has_phase_data:
        merged.update(phase_metrics)
        merged["points_gagnes_sideout"] = _to_int(phase_metrics.get("sideout_points"))
        merged["break_points"] = _to_int(phase_metrics.get("break_points"))
        merged["break_opportunities"] = _to_int(phase_metrics.get("break_opportunities"))
        merged["break_point_ratio_pct"] = _to_float(phase_metrics.get("break_point_ratio_pct"))
        merged["sideout_efficacite_pct"] = _to_float(phase_metrics.get("sideout_efficacite_pct"))
        merged["first_sideout_efficacite_pct"] = _to_float(
            phase_metrics.get("first_sideout_efficacite_pct"),
        )
        points_total = merged["points_gagnes_sideout"] + merged["break_points"]
        merged["sideout_contribution_pct"] = round(
            _pct(merged["points_gagnes_sideout"], points_total), 1,
        )
        return merged

    merged["sets_total"] = _to_int(phase_metrics.get("sets_total"))
    merged["sets_with_timeline"] = _to_int(phase_metrics.get("sets_with_timeline"))
    merged["phase_coverage_pct"] = _to_float(phase_metrics.get("phase_coverage_pct"))
    return merged


def _build_position_stats(match: MatchDB, side: str, items: list[dict]) -> list[dict]:
    by_num = {}
    for item in items:
        stats = item.get("stats", {})
        numero = _normalize_numero(stats.get("numero"))
        if numero:
            by_num[numero] = stats

    positions = {
        pos: {
            "position": f"P{pos}",
            "apparitions": 0,
            "points_joues": 0,
            "points_gagnes": 0,
            "points_perdus": 0,
            "service_turns": 0,
            "joueurs": defaultdict(int),
        }
        for pos in range(1, 7)
    }

    for set_ in (match.sets or []):
        formation = next((f for f in (set_.formations or []) if f.equipe == side), None)
        if formation:
            for pos in range(1, 7):
                numero_raw = getattr(formation, f"position_{pos}", None)
                numero = _normalize_numero(numero_raw)
                if not numero:
                    continue
                bucket = positions[pos]
                bucket["apparitions"] += 1
                bucket["joueurs"][numero] += 1
                player = by_num.get(numero)
                if player:
                    bucket["points_joues"] += _to_int(player.get("points_joues"))
                    bucket["points_gagnes"] += _to_int(player.get("points_gagnes"))
                    bucket["points_perdus"] += _to_int(player.get("points_perdus"))

        services = set_.services_a if side == "A" else set_.services_b
        if isinstance(services, dict):
            for pos_key, scores in services.items():
                try:
                    pos = int(pos_key)
                except (TypeError, ValueError):
                    continue
                if pos in positions and isinstance(scores, list):
                    positions[pos]["service_turns"] += len(scores)

    result = []
    for pos in range(1, 7):
        bucket = positions[pos]
        points_joues = bucket["points_joues"]
        points_gagnes = bucket["points_gagnes"]
        points_perdus = bucket["points_perdus"]
        result.append(
            {
                "position": bucket["position"],
                "apparitions": bucket["apparitions"],
                "points_joues": points_joues,
                "points_gagnes": points_gagnes,
                "points_perdus": points_perdus,
                "efficacite_pct": round(_pct(points_gagnes, points_joues), 1),
                "service_turns": bucket["service_turns"],
                "joueur_dominant": max(bucket["joueurs"], key=bucket["joueurs"].get) if bucket["joueurs"] else None,
            }
        )
    return result


def _build_team_history_rows(current_summary: dict, previous_summaries: list[dict]) -> list[dict]:
    rows = [{
        "label": "Match actuel",
        "points_joues": current_summary["points_joues"],
        "efficacite_pct": current_summary["efficacite_pct"],
        "services": current_summary["services"],
        "max_serie": current_summary["max_serie"],
        "break_point_ratio_pct": current_summary.get("break_point_ratio_pct", 0.0),
        "sideout_efficacite_pct": current_summary.get("sideout_efficacite_pct", 0.0),
    }]
    rows.extend(previous_summaries)
    return rows[:8]


def _build_face_to_face_rows(match: MatchDB, summary_a: dict, summary_b: dict) -> list[dict]:
    timeouts_a = sum(1 for set_ in (match.sets or []) for t in (set_.timeouts or []) if t.equipe == "A")
    timeouts_b = sum(1 for set_ in (match.sets or []) for t in (set_.timeouts or []) if t.equipe == "B")
    sanctions_a = sum(1 for s in (match.sanctions or []) if s.equipe == "A")
    sanctions_b = sum(1 for s in (match.sanctions or []) if s.equipe == "B")
    score_points_a = sum(_to_int(set_.score_a) for set_ in (match.sets or []))
    score_points_b = sum(_to_int(set_.score_b) for set_ in (match.sets or []))

    return [
        {"label": "Sets remportés", "a": _to_int(match.sets_equipe_a), "b": _to_int(match.sets_equipe_b), "unit": ""},
        {"label": "Points marqués (sets)", "a": score_points_a, "b": score_points_b, "unit": ""},
        {"label": "Points de break", "a": summary_a.get("break_points", 0), "b": summary_b.get("break_points", 0), "unit": ""},
        {"label": "Points de side-out", "a": summary_a.get("sideout_points", 0), "b": summary_b.get("sideout_points", 0), "unit": ""},
        {"label": "Points joués estimés", "a": summary_a["points_joues"], "b": summary_b["points_joues"], "unit": ""},
        {"label": "Efficacité terrain", "a": summary_a["efficacite_pct"], "b": summary_b["efficacite_pct"], "unit": "%"},
        {"label": "Efficacité side-out", "a": summary_a.get("sideout_efficacite_pct", 0.0), "b": summary_b.get("sideout_efficacite_pct", 0.0), "unit": "%"},
        {"label": "Efficacité first side-out", "a": summary_a.get("first_sideout_efficacite_pct", 0.0), "b": summary_b.get("first_sideout_efficacite_pct", 0.0), "unit": "%"},
        {"label": "Break point ratio", "a": summary_a.get("break_point_ratio_pct", 0.0), "b": summary_b.get("break_point_ratio_pct", 0.0), "unit": "%"},
        {"label": "Efficacité au service", "a": summary_a["service_win_pct"], "b": summary_b["service_win_pct"], "unit": "%"},
        {"label": "Services totaux", "a": summary_a["services"], "b": summary_b["services"], "unit": ""},
        {"label": "Meilleure série service", "a": summary_a["max_serie"], "b": summary_b["max_serie"], "unit": ""},
        {"label": "Couverture données service", "a": summary_a.get("phase_coverage_pct", 0.0), "b": summary_b.get("phase_coverage_pct", 0.0), "unit": "%"},
        {"label": "Temps de jeu cumulé", "a": summary_a["temps_total"], "b": summary_b["temps_total"], "unit": " min"},
        {"label": "Changements", "a": summary_a["changements"], "b": summary_b["changements"], "unit": ""},
        {"label": "Temps morts provoqués", "a": summary_a["temps_morts_provoques"], "b": summary_b["temps_morts_provoques"], "unit": ""},
        {"label": "Temps morts demandés", "a": timeouts_a, "b": timeouts_b, "unit": ""},
        {"label": "Sanctions", "a": sanctions_a, "b": sanctions_b, "unit": ""},
        {"label": "Effectif utilisé", "a": summary_a["players"], "b": summary_b["players"], "unit": " joueurs"},
    ]


@router.get("/matchs", response_class=HTMLResponse)
async def matchs_list(
    request: Request,
    page: int = Query(1, ge=1),
    saison_id: Optional[str] = Query(None),
    saison_ids: Optional[list[int]] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    after_date: Optional[str] = Query(None),
    before_date: Optional[str] = Query(None),
    competition_id: Optional[int] = None,
    departements: Optional[str] = None,
    repo: MatchRepository = Depends(get_match_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
):
    saison_id_int = parse_optional_int(saison_id)
    time_filter = build_time_filter(
        season_ids=saison_ids,
        season_id=saison_id_int,
        date_from=date_from,
        date_to=date_to,
        after_date=after_date,
        before_date=before_date,
    )

    dept_list = (
        [d.strip() for d in departements.split(",") if d.strip()]
        if departements
        else None
    )

    limit = 50
    offset = (page - 1) * limit
    matchs = repo.search(
        saison_ids=time_filter.season_ids,
        date_from=time_filter.date_from,
        date_to=time_filter.date_to,
        competition_id=competition_id,
        departements=dept_list,
        limit=limit,
        offset=offset,
    )
    total = repo.count_search(
        saison_ids=time_filter.season_ids,
        date_from=time_filter.date_from,
        date_to=time_filter.date_to,
        competition_id=competition_id,
        departements=dept_list,
    )
    saisons = saison_repo.get_all(limit=20)

    def page_url(target_page: int) -> str:
        params = []
        for sid in time_filter.season_ids:
            params.append(("saison_ids", str(sid)))
        if competition_id is not None:
            params.append(("competition_id", str(competition_id)))
        if departements:
            params.append(("departements", departements))
        if time_filter.date_from:
            params.append(("date_from", time_filter.date_from.isoformat()))
        if time_filter.date_to:
            params.append(("date_to", time_filter.date_to.isoformat()))
        params.append(("page", str(target_page)))
        return f"/matchs?{urlencode(params)}"

    return templates.TemplateResponse(
        "matchs/list.html",
        {
            "request": request,
            "matchs": matchs,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
            "saisons": saisons,
            "current_saison_ids": time_filter.season_ids,
            "selected_departements": dept_list or [],
            "time_filter": time_filter.to_context(),
            "page_prev_url": page_url(page - 1) if page > 1 else None,
            "page_next_url": page_url(page + 1) if offset + limit < total else None,
        },
    )


@router.get("/matchs/{match_id}", response_class=HTMLResponse)
async def match_detail(
    request: Request,
    match_id: int,
    repo: MatchRepository = Depends(get_match_repo),
):
    match = repo.get_with_details(match_id)
    if not match:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Match non trouvé"},
            status_code=404,
        )

    # Séparer les participations par équipe
    participants_a = [
        p for p in (match.participations or []) if p.equipe_id == match.equipe_a_id
    ]
    participants_b = [
        p for p in (match.participations or []) if p.equipe_id == match.equipe_b_id
    ]

    # Séparer les officiels par équipe
    officiels_a = [o for o in (match.officiels or []) if o.equipe == "A"]
    officiels_b = [o for o in (match.officiels or []) if o.equipe == "B"]

    # Données de simulation
    sim_data = build_simulation_data(
        match, participants_a, participants_b, officiels_a, officiels_b
    )

    match_core = match_db_to_core(match, participants_a, participants_b)
    momentum_data = build_momentum_data(match, match_core)
    phase_metrics = _compute_team_phase_metrics(match_core)

    has_point_timeline = bool(momentum_data.get("sets"))

    # Statistiques détaillées par joueur
    player_stats_a = []
    player_stats_b = []
    stats_dashboard = {
        "face_to_face": [],
        "teams": {"A": {}, "B": {}},
        "players": [],
    }
    if match.has_details:
        from pyvolley.database.player_stats_service import JoueurMatchStatsService

        stats_service = JoueurMatchStatsService(repo.session)
        stats_service.compute_and_store_for_match(match)
        player_stats_a, player_stats_b = stats_service.get_match_stats_grouped(match.id)

        participant_count_a = len([p for p in (match.participations or []) if p.equipe_id == match.equipe_a_id])
        participant_count_b = len([p for p in (match.participations or []) if p.equipe_id == match.equipe_b_id])

        summary_a = _summarize_team_players(player_stats_a)
        summary_b = _summarize_team_players(player_stats_b)

        if not player_stats_a:
            summary_a = _summarize_team_from_sets(match, "A", participant_count=participant_count_a)
        if not player_stats_b:
            summary_b = _summarize_team_from_sets(match, "B", participant_count=participant_count_b)

        summary_a = _merge_phase_metrics(summary_a, phase_metrics.get("A"))
        summary_b = _merge_phase_metrics(summary_b, phase_metrics.get("B"))

        prev_matches_a = list(repo.session.scalars(
            select(MatchDB)
            .where(
                MatchDB.id != match.id,
                MatchDB.has_details.is_(True),
                or_(MatchDB.equipe_a_id == match.equipe_a_id, MatchDB.equipe_b_id == match.equipe_a_id),
            )
            .order_by(MatchDB.date_match.desc(), MatchDB.id.desc())
            .limit(8)
        )) if match.equipe_a_id else []
        prev_matches_b = list(repo.session.scalars(
            select(MatchDB)
            .where(
                MatchDB.id != match.id,
                MatchDB.has_details.is_(True),
                or_(MatchDB.equipe_a_id == match.equipe_b_id, MatchDB.equipe_b_id == match.equipe_b_id),
            )
            .order_by(MatchDB.date_match.desc(), MatchDB.id.desc())
            .limit(8)
        )) if match.equipe_b_id else []

        for prev in prev_matches_a + prev_matches_b:
            stats_service.compute_and_store_for_match(prev)

        prev_ids = [m.id for m in (prev_matches_a + prev_matches_b)]
        prev_rows = list(repo.session.scalars(
            select(JoueurMatchStatsDB)
            .where(JoueurMatchStatsDB.match_id.in_(prev_ids))
        )) if prev_ids else []

        prev_team_rows: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for row in prev_rows:
            if row.equipe_id is None:
                continue
            prev_team_rows[(row.match_id, row.equipe_id)].append({"stats": row.stats_data})

        previous_a = []
        for prev in prev_matches_a:
            s = _summarize_team_players(prev_team_rows.get((prev.id, match.equipe_a_id), []))
            prev_side = "A" if prev.equipe_a_id == match.equipe_a_id else "B"
            prev_phase = _compute_team_phase_metrics(match_db_to_core(prev)).get(prev_side)
            s = _merge_phase_metrics(s, prev_phase)
            label = prev.date_match.strftime("%d/%m") if prev.date_match else prev.code_match
            previous_a.append({
                "label": label,
                "points_joues": s["points_joues"],
                "efficacite_pct": s["efficacite_pct"],
                "services": s["services"],
                "max_serie": s["max_serie"],
                "break_point_ratio_pct": s.get("break_point_ratio_pct", 0.0),
                "sideout_efficacite_pct": s.get("sideout_efficacite_pct", 0.0),
            })

        previous_b = []
        for prev in prev_matches_b:
            s = _summarize_team_players(prev_team_rows.get((prev.id, match.equipe_b_id), []))
            prev_side = "A" if prev.equipe_a_id == match.equipe_b_id else "B"
            prev_phase = _compute_team_phase_metrics(match_db_to_core(prev)).get(prev_side)
            s = _merge_phase_metrics(s, prev_phase)
            label = prev.date_match.strftime("%d/%m") if prev.date_match else prev.code_match
            previous_b.append({
                "label": label,
                "points_joues": s["points_joues"],
                "efficacite_pct": s["efficacite_pct"],
                "services": s["services"],
                "max_serie": s["max_serie"],
                "break_point_ratio_pct": s.get("break_point_ratio_pct", 0.0),
                "sideout_efficacite_pct": s.get("sideout_efficacite_pct", 0.0),
            })

        stats_dashboard = {
            "face_to_face": _build_face_to_face_rows(match, summary_a, summary_b),
            "teams": {
                "A": {
                    "name": match.equipe_a.nom if match.equipe_a else "Équipe A",
                    "summary": summary_a,
                    "positions": _build_position_stats(match, "A", player_stats_a),
                    "history": _build_team_history_rows(summary_a, previous_a),
                },
                "B": {
                    "name": match.equipe_b.nom if match.equipe_b else "Équipe B",
                    "summary": summary_b,
                    "positions": _build_position_stats(match, "B", player_stats_b),
                    "history": _build_team_history_rows(summary_b, previous_b),
                },
            },
            "players": [],
        }

        for item in (player_stats_a + player_stats_b):
            stats = item.get("stats", {})
            joueur_id = item.get("joueur_id")
            history_rows = list(repo.session.execute(
                select(JoueurMatchStatsDB, MatchDB)
                .join(MatchDB, MatchDB.id == JoueurMatchStatsDB.match_id)
                .where(
                    JoueurMatchStatsDB.joueur_id == joueur_id,
                    JoueurMatchStatsDB.match_id != match.id,
                )
                .order_by(MatchDB.date_match.desc(), MatchDB.id.desc())
                .limit(10)
            ))
            player_history = []
            for stat_row, history_match in history_rows:
                history_services = _to_int(
                    stat_row.stats_data.get("services") or stat_row.stats_data.get("nb_services"),
                )
                history_break_points = _to_int(stat_row.stats_data.get("points_gagnes_service"))
                history_points_gagnes = _to_int(stat_row.stats_data.get("points_gagnes"))
                history_sideout_raw = stat_row.stats_data.get("points_gagnes_sideout")
                if history_sideout_raw is None:
                    history_sideout_points = max(0, history_points_gagnes - history_break_points)
                else:
                    history_sideout_points = max(0, _to_int(history_sideout_raw))
                label = history_match.date_match.strftime("%d/%m") if history_match.date_match else history_match.code_match
                player_history.append({
                    "label": label,
                    "points_joues": _to_int(stat_row.stats_data.get("points_joues")),
                    "efficacite_pct": round(_pct(history_points_gagnes, _to_int(stat_row.stats_data.get("points_joues"))), 1),
                    "services": history_services,
                    "break_point_ratio_pct": round(_pct(history_break_points, history_services), 1),
                    "points_gagnes_sideout": max(0, history_sideout_points),
                    "max_serie": _to_int(stat_row.stats_data.get("max_serie") or stat_row.stats_data.get("meilleure_serie")),
                    "temps_jeu": round(_to_float(stat_row.stats_data.get("temps_jeu_estime")), 1),
                })

            player_services = _to_int(stats.get("services") or stats.get("nb_services"))
            player_break_points = _to_int(stats.get("points_gagnes_service"))
            player_sideout_raw = stats.get("points_gagnes_sideout")
            if player_sideout_raw is None:
                player_sideout_points = max(0, _to_int(stats.get("points_gagnes")) - player_break_points)
            else:
                player_sideout_points = max(0, _to_int(player_sideout_raw))

            stats_dashboard["players"].append({
                "joueur_id": joueur_id,
                "side": stats.get("side"),
                "numero": stats.get("numero"),
                "nom": stats.get("nom"),
                "prenom": stats.get("prenom"),
                "est_capitaine": bool(stats.get("est_capitaine")),
                "est_libero": bool(stats.get("est_libero")),
                "points_joues": _to_int(stats.get("points_joues")),
                "points_gagnes": _to_int(stats.get("points_gagnes")),
                "points_perdus": _to_int(stats.get("points_perdus")),
                "points_gagnes_sideout": max(0, player_sideout_points),
                "efficacite_pct": round(_pct(_to_int(stats.get("points_gagnes")), _to_int(stats.get("points_joues"))), 1),
                "services": player_services,
                "break_point_ratio_pct": round(_pct(player_break_points, player_services), 1),
                "sideout_contribution_pct": round(_pct(max(0, player_sideout_points), _to_int(stats.get("points_gagnes"))), 1),
                "max_serie": _to_int(stats.get("max_serie") or stats.get("meilleure_serie")),
                "temps_jeu": round(_to_float(stats.get("temps_jeu_estime")), 1),
                "sets_joues": _to_int(stats.get("sets_joues")),
                "presence_par_set": stats.get("presence_par_set") or [],
                "detail_services_par_set": stats.get("detail_services_par_set") or [],
                "history": player_history,
            })

    return templates.TemplateResponse(
        "matchs/detail.html",
        {
            "request": request,
            "match": match,
            "participants_a": participants_a,
            "participants_b": participants_b,
            "officiels_a": officiels_a,
            "officiels_b": officiels_b,
            "sim_data_json": json.dumps(sim_data, ensure_ascii=False),
            "momentum_data_json": json.dumps(momentum_data, ensure_ascii=False),
            "has_point_timeline": has_point_timeline,
            "player_stats_a": player_stats_a,
            "player_stats_b": player_stats_b,
            "match_stats_dashboard_json": json.dumps(stats_dashboard, ensure_ascii=False),
        },
    )
