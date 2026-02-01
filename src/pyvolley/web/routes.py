"""
Routes web pour l'interface utilisateur.
"""

from typing import Optional
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.app import templates
from pyvolley.api.dependencies import (
    get_joueur_repo,
    get_club_repo,
    get_equipe_repo,
    get_match_repo,
)
from pyvolley.database.repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    MatchRepository,
)


web_router = APIRouter()


@web_router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Page d'accueil."""
    stats = {
        "joueurs": joueur_repo.count(),
        "matchs": match_repo.count(),
    }
    
    # Derniers matchs
    derniers_matchs = match_repo.search(limit=5)
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "derniers_matchs": derniers_matchs,
        }
    )


@web_router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: Optional[str] = Query(None, min_length=2),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    """Page de recherche."""
    results = {
        "joueurs": [],
        "clubs": [],
        "equipes": [],
        "query": q or "",
    }
    
    if q:
        results["joueurs"] = joueur_repo.search_by_name(q, limit=20)
        results["clubs"] = club_repo.search_by_name(q, limit=20)
        results["equipes"] = equipe_repo.search_by_name(q, limit=20)
    
    return templates.TemplateResponse(
        "search.html",
        {"request": request, **results}
    )


@web_router.get("/joueurs", response_class=HTMLResponse)
async def joueurs_list(
    request: Request,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: JoueurRepository = Depends(get_joueur_repo),
):
    """Liste des joueurs."""
    limit = 50
    offset = (page - 1) * limit
    
    if q:
        joueurs = repo.search_by_name(q, limit=limit)
    else:
        joueurs = repo.get_all(limit=limit, offset=offset)
    
    total = repo.count()
    
    return templates.TemplateResponse(
        "joueurs/list.html",
        {
            "request": request,
            "joueurs": joueurs,
            "query": q,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
        }
    )


@web_router.get("/joueurs/{joueur_id}", response_class=HTMLResponse)
async def joueur_detail(
    request: Request,
    joueur_id: int,
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Détail d'un joueur."""
    joueur = joueur_repo.get(joueur_id)
    if not joueur:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Joueur non trouvé"},
            status_code=404
        )
    
    matchs = match_repo.get_by_joueur(joueur_id, limit=20)
    stats = joueur_repo.get_stats(joueur_id)
    
    return templates.TemplateResponse(
        "joueurs/detail.html",
        {
            "request": request,
            "joueur": joueur,
            "matchs": matchs,
            "stats": stats,
        }
    )


@web_router.get("/equipes", response_class=HTMLResponse)
async def equipes_list(
    request: Request,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: EquipeRepository = Depends(get_equipe_repo),
):
    """Liste des équipes."""
    limit = 50
    offset = (page - 1) * limit
    
    if q:
        equipes = repo.search_by_name(q, limit=limit)
    else:
        equipes = repo.get_all(limit=limit, offset=offset)
    
    total = repo.count()
    
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
        }
    )


@web_router.get("/equipes/{equipe_id}", response_class=HTMLResponse)
async def equipe_detail(
    request: Request,
    equipe_id: int,
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Détail d'une équipe."""
    equipe = equipe_repo.get(equipe_id)
    if not equipe:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Équipe non trouvée"},
            status_code=404
        )
    
    matchs = match_repo.get_by_equipe(equipe_id, limit=20)
    victoires = sum(1 for m in matchs if m.vainqueur_nom == equipe.nom)
    
    return templates.TemplateResponse(
        "equipes/detail.html",
        {
            "request": request,
            "equipe": equipe,
            "matchs": matchs,
            "victoires": victoires,
            "defaites": len(matchs) - victoires,
        }
    )


@web_router.get("/matchs", response_class=HTMLResponse)
async def matchs_list(
    request: Request,
    page: int = Query(1, ge=1),
    repo: MatchRepository = Depends(get_match_repo),
):
    """Liste des matchs."""
    limit = 50
    offset = (page - 1) * limit
    
    matchs = repo.search(limit=limit)
    total = repo.count()
    
    return templates.TemplateResponse(
        "matchs/list.html",
        {
            "request": request,
            "matchs": matchs,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
        }
    )


@web_router.get("/matchs/{match_id}", response_class=HTMLResponse)
async def match_detail(
    request: Request,
    match_id: int,
    repo: MatchRepository = Depends(get_match_repo),
):
    """Détail d'un match."""
    match = repo.get(match_id)
    if not match:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Match non trouvé"},
            status_code=404
        )
    
    return templates.TemplateResponse(
        "matchs/detail.html",
        {
            "request": request,
            "match": match,
        }
    )


@web_router.get("/clubs", response_class=HTMLResponse)
async def clubs_list(
    request: Request,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: ClubRepository = Depends(get_club_repo),
):
    """Liste des clubs."""
    limit = 50
    offset = (page - 1) * limit
    
    if q:
        clubs = repo.search_by_name(q, limit=limit)
    else:
        clubs = repo.get_all(limit=limit, offset=offset)
    
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
        }
    )


@web_router.get("/clubs/{club_id}", response_class=HTMLResponse)
async def club_detail(
    request: Request,
    club_id: int,
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    """Détail d'un club."""
    club = club_repo.get(club_id)
    if not club:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Club non trouvé"},
            status_code=404
        )
    
    equipes = equipe_repo.get_by_club(club_id)
    
    return templates.TemplateResponse(
        "clubs/detail.html",
        {
            "request": request,
            "club": club,
            "equipes": equipes,
        }
    )
