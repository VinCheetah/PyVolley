"""
Routes web — Entraîneurs (liste et détail).
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import get_entraineur_repo
from pyvolley.database.repositories import EntraineurRepository

router = APIRouter()


@router.get("/entraineurs", response_class=HTMLResponse)
def entraineurs_list(
    request: Request,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: EntraineurRepository = Depends(get_entraineur_repo),
):
    limit = 50
    offset = (page - 1) * limit
    if q:
        entraineurs = repo.search_by_name(q, limit=limit, offset=offset)
        total = repo.count_search(q)
    else:
        entraineurs = repo.get_all(limit=limit, offset=offset)
        total = repo.count()
    return templates.TemplateResponse(
        "entraineurs/list.html",
        {
            "request": request,
            "entraineurs": entraineurs,
            "query": q,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
        },
    )


@router.get("/entraineurs/{entraineur_id:path}", response_class=HTMLResponse)
def entraineur_detail(
    request: Request,
    entraineur_id: str,
    repo: EntraineurRepository = Depends(get_entraineur_repo),
):
    entraineur = repo.get_by_id(entraineur_id)
    if not entraineur:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Entraîneur non trouvé"},
            status_code=404,
        )
    stats = repo.get_stats(entraineur_id)
    matchs = repo.get_matchs(entraineur_id, limit=50)
    return templates.TemplateResponse(
        "entraineurs/detail.html",
        {
            "request": request,
            "entraineur": entraineur,
            "stats": stats,
            "matchs": matchs,
        },
    )
