"""
Routes web — Recherche globale.
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import (
    get_joueur_repo,
    get_club_repo,
    get_equipe_repo,
    get_arbitre_repo,
    get_saison_repo,
)
from pyvolley.database.repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    ArbitreRepository,
    SaisonRepository,
)

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: Optional[str] = Query(None, min_length=2),
    genre: Optional[str] = Query(None),
    niveau: Optional[str] = Query(None),
    saison_id: Optional[int] = Query(None),
    ligue: Optional[str] = Query(None),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
):
    results = {
        "joueurs": [],
        "clubs": [],
        "equipes": [],
        "arbitres": [],
        "query": q or "",
        "genre": genre or "",
        "niveau": niveau or "",
        "saison_id": saison_id,
        "ligue": ligue or "",
    }

    if q:
        results["joueurs"] = joueur_repo.search_by_name(
            q, genre=genre, saison_id=saison_id, limit=30
        )
        results["clubs"] = club_repo.search_by_name(q, limit=30)
        results["equipes"] = equipe_repo.search_by_name(
            q, genre=genre, niveau=niveau, saison_id=saison_id, limit=30
        )
        results["arbitres"] = arbitre_repo.search_by_name(q, ligue=ligue, limit=30)

    saisons = saison_repo.get_all(limit=20)
    genres = equipe_repo.get_distinct_genres()
    niveaux = equipe_repo.get_distinct_niveaux()
    ligues = arbitre_repo.get_distinct_ligues()

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            **results,
            "saisons": saisons,
            "genres": genres,
            "niveaux": niveaux,
            "ligues": ligues,
        },
    )
