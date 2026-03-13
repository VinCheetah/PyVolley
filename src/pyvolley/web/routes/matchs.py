"""
Routes web — Matchs (liste et détail).
"""

import json
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
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
    competition_id: Optional[int] = None,
    departements: Optional[str] = None,
    repo: MatchRepository = Depends(get_match_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
):
    saison_id_int = parse_optional_int(saison_id)

    dept_list = (
        [d.strip() for d in departements.split(",") if d.strip()]
        if departements
        else None
    )

    limit = 50
    offset = (page - 1) * limit
    matchs = repo.search(
        saison_id=saison_id_int,
        competition_id=competition_id,
        departements=dept_list,
        limit=limit,
    )
    total = repo.count()
    saisons = saison_repo.get_all(limit=20)
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
            "selected_departements": dept_list or [],
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
        from pyvolley.database.converters import match_db_to_core
        from pyvolley.analysis.joueur_stats import analyze_joueur_match

        match_core = match_db_to_core(match, participants_a, participants_b)
        for p in participants_a:
            if p.joueur:
                s = analyze_joueur_match(match_core, p.joueur.licence)
                if s:
                    player_stats_a.append({"stats": s, "joueur_id": p.joueur_id})
        for p in participants_b:
            if p.joueur:
                s = analyze_joueur_match(match_core, p.joueur.licence)
                if s:
                    player_stats_b.append({"stats": s, "joueur_id": p.joueur_id})

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
