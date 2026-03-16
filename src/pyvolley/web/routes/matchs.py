"""
Routes web — Matchs (liste et détail).
"""

import json
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.web.helpers.time_filter import build_time_filter
from pyvolley.web.helpers.match_utils import build_simulation_data
from pyvolley.shared.helpers import parse_optional_int
from pyvolley.api.dependencies import get_match_repo, get_saison_repo
from pyvolley.database.repositories import MatchRepository, SaisonRepository

router = APIRouter()


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
    )
    total = repo.count()
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
            "current_saison_id": saison_id_int,
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

    # Statistiques détaillées par joueur
    player_stats_a = []
    player_stats_b = []
    if match.has_details:
        from pyvolley.database.player_stats_service import JoueurMatchStatsService

        stats_service = JoueurMatchStatsService(repo.session)
        stats_service.compute_and_store_for_match(match)
        player_stats_a, player_stats_b = stats_service.get_match_stats_grouped(match.id)

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
            "player_stats_a": player_stats_a,
            "player_stats_b": player_stats_b,
        },
    )
