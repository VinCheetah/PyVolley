"""
Routes web — Arbitres (liste et détail).
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import get_arbitre_repo
from pyvolley.database.repositories import ArbitreRepository

router = APIRouter()


@router.get("/arbitres", response_class=HTMLResponse)
async def arbitres_list(
    request: Request,
    q: Optional[str] = None,
    ligue: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    limit = 50
    offset = (page - 1) * limit
    if q:
        arbitres = repo.search_by_name(q, ligue=ligue, limit=limit, offset=offset)
        total = repo.count_search(q, ligue=ligue)
    else:
        arbitres = repo.get_all(limit=limit, offset=offset)
        total = repo.count()
    ligues = repo.get_distinct_ligues()
    return templates.TemplateResponse(
        "arbitres/list.html",
        {
            "request": request,
            "arbitres": arbitres,
            "query": q,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
            "ligue": ligue or "",
            "ligues": ligues,
        },
    )


@router.get("/arbitres/{arbitre_id}", response_class=HTMLResponse)
async def arbitre_detail(
    request: Request,
    arbitre_id: int,
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    arbitre = arbitre_repo.get(arbitre_id)
    if not arbitre:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Arbitre non trouvé"},
            status_code=404,
        )
    stats = arbitre_repo.get_stats(arbitre_id)
    matchs = arbitre_repo.get_matchs(arbitre_id, limit=50)
    return templates.TemplateResponse(
        "arbitres/detail.html",
        {"request": request, "arbitre": arbitre, "stats": stats, "matchs": matchs},
    )
