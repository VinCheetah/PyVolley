"""
Routes web — Clubs (liste et détail).
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import get_club_repo, get_equipe_repo
from pyvolley.database.repositories import ClubRepository, EquipeRepository

router = APIRouter()


@router.get("/clubs", response_class=HTMLResponse)
async def clubs_list(
    request: Request,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: ClubRepository = Depends(get_club_repo),
):
    limit = 50
    offset = (page - 1) * limit
    clubs = (
        repo.search_by_name(q, limit=limit)
        if q
        else repo.get_all(limit=limit, offset=offset)
    )
    total = repo.count()
    return templates.TemplateResponse(
        "clubs/list.html",
        {
            "request": request,
            "clubs": clubs,
            "query": q,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
        },
    )


@router.get("/clubs/{club_id}", response_class=HTMLResponse)
async def club_detail(
    request: Request,
    club_id: int,
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    club = club_repo.get_with_details(club_id)
    if not club:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Club non trouvé"},
            status_code=404,
        )
    equipes = equipe_repo.get_by_club(club_id)
    return templates.TemplateResponse(
        "clubs/detail.html",
        {"request": request, "club": club, "equipes": equipes},
    )
