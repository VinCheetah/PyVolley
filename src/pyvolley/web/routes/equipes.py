"""
Routes web — Équipes (liste et détail).
"""

import json
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.web.helpers.match_utils import build_match_score_evolution
from pyvolley.shared.helpers import is_winner, parse_optional_int
from pyvolley.api.dependencies import (
    get_equipe_repo,
    get_match_repo,
    get_saison_repo,
)
from pyvolley.database.repositories import (
    EquipeRepository,
    MatchRepository,
    SaisonRepository,
)
from pyvolley.scrapers.ffvb.utils import build_equipe_ffvb_url
from pyvolley.core.config import get_settings

router = APIRouter()


@router.get("/equipes", response_class=HTMLResponse)
async def equipes_list(
    request: Request,
    q: Optional[str] = None,
    genre: Optional[str] = None,
    niveau: Optional[str] = None,
    categorie: Optional[str] = None,
    saison_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    repo: EquipeRepository = Depends(get_equipe_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
):
    saison_id_int = parse_optional_int(saison_id)

    limit = 50
    offset = (page - 1) * limit
    if q or genre or niveau or categorie or saison_id_int:
        equipes = repo.search_by_name(
            q or "%",
            genre=genre,
            niveau=niveau,
            categorie=categorie,
            saison_id=saison_id_int,
            limit=limit,
            offset=offset,
        )
        total = repo.count_search(
            q or "%",
            genre=genre,
            niveau=niveau,
            categorie=categorie,
            saison_id=saison_id_int,
        )
    else:
        equipes = repo.get_all(limit=limit, offset=offset)
        total = repo.count()
    saisons = saison_repo.get_all(limit=20)
    genres = repo.get_distinct_genres()
    niveaux = repo.get_distinct_niveaux()
    categories = repo.get_distinct_categories()
    return templates.TemplateResponse(
        "equipes/list.html",
        {
            "request": request,
            "equipes": equipes,
            "query": q,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
            "saisons": saisons,
            "current_saison_id": saison_id_int,
            "genre": genre or "",
            "genres": genres,
            "niveau": niveau or "",
            "niveaux": niveaux,
            "categorie": categorie or "",
            "categories": categories,
        },
    )


@router.get("/equipes/{equipe_id}", response_class=HTMLResponse)
async def equipe_detail(
    request: Request,
    equipe_id: int,
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    equipe = equipe_repo.get_with_details(equipe_id)
    if not equipe:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Équipe non trouvée"},
            status_code=404,
        )
    matchs = match_repo.get_by_equipe(equipe_id, limit=200)
    victoires = sum(1 for m in matchs if is_winner(m, equipe))
    roster = equipe_repo.get_roster(equipe_id)

    # Sets stats
    sets_gagnes = 0
    sets_perdus = 0
    for m in matchs:
        if m.equipe_a_id == equipe.id:
            sets_gagnes += m.sets_equipe_a
            sets_perdus += m.sets_equipe_b
        else:
            sets_gagnes += m.sets_equipe_b
            sets_perdus += m.sets_equipe_a

    score_evolution = build_match_score_evolution(matchs, equipe)

    # URL FFVB pour l'équipe
    url_ffvb = None
    if (
        equipe.club
        and equipe.club.code_ffvb
        and equipe.competition
        and equipe.competition.entite
        and equipe.saison
    ):
        settings = get_settings()
        saison_ffvb = equipe.saison.code.replace("-", "/")
        url_ffvb = build_equipe_ffvb_url(
            base_url=settings.ffvb_base_url,
            entity_code=equipe.competition.entite.code,
            saison=saison_ffvb,
            club_code_ffvb=equipe.club.code_ffvb,
        )

    return templates.TemplateResponse(
        "equipes/detail.html",
        {
            "request": request,
            "equipe": equipe,
            "matchs": matchs,
            "victoires": victoires,
            "defaites": len([m for m in matchs if m.match_joue]) - victoires,
            "roster": roster,
            "sets_gagnes": sets_gagnes,
            "sets_perdus": sets_perdus,
            "score_evolution_json": json.dumps(
                score_evolution, ensure_ascii=False, default=str
            ),
            "url_ffvb": url_ffvb,
        },
    )
