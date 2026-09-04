"""
Routes web — Joueurs (liste et fiche détaillée).

Délègue l'assemblage métier et analytique au JoueurViewService.
Les routes sont exécutées de manière synchrone (`def`) pour tirer parti
du threadpool Starlette de FastAPI sans bloquer l'Event Loop.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from pyvolley.api.dependencies import (
    get_equipe_repo,
    get_joueur_repo,
    get_session,
)
from pyvolley.database.repositories import EquipeRepository, JoueurRepository
from pyvolley.web.services.joueur_view_service import JoueurViewService
from pyvolley.web.templateconfig import templates

router = APIRouter()


@router.get("/joueurs", response_class=HTMLResponse)
def joueurs_list(
    request: Request,
    q: Optional[str] = None,
    genre: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: JoueurRepository = Depends(get_joueur_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    """Liste paginée des joueurs avec recherche et filtre de genre."""
    limit = 50
    offset = (page - 1) * limit
    if q:
        joueurs = repo.search_by_name(q, genre=genre, limit=limit, offset=offset)
        total = repo.count_search(q, genre=genre)
    else:
        joueurs = repo.get_all(limit=limit, offset=offset)
        total = repo.count()

    genres = equipe_repo.get_distinct_genres()
    return templates.TemplateResponse(
        request,
        "joueurs/list.html",
        {
            "joueurs": joueurs,
            "query": q,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
            "genre": genre or "",
            "genres": genres,
        },
    )


@router.get("/joueurs/{joueur_id}", response_class=HTMLResponse)
def joueur_detail(
    request: Request,
    joueur_id: int,
    tab: Optional[str] = Query("resume"),
    saison_id: Optional[int] = Query(None),
    saison_ids: Optional[list[int]] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    equipe_ids: Optional[list[int]] = Query(None),
    club_ids: Optional[list[int]] = Query(None),
    competition_ids: Optional[list[int]] = Query(None),
    niveaux: Optional[list[str]] = Query(None),
    resultat: Optional[str] = Query(None),
    domicile_exterieur: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """Fiche joueur détaillée avec timeline de niveau, statistiques avancées et maillots."""
    context = JoueurViewService.build_detail_context(
        joueur_id=joueur_id,
        session=session,
        tab=tab,
        saison_id=saison_id,
        saison_ids=saison_ids,
        date_from=date_from,
        date_to=date_to,
        equipe_ids=equipe_ids,
        club_ids=club_ids,
        competition_ids=competition_ids,
        niveaux=niveaux,
        resultat=resultat,
        domicile_exterieur=domicile_exterieur,
    )
    if not context:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")

    # Support des requêtes partielles HTMX (par ex. changement de filtres dans l'onglet stats)
    if request.headers.get("HX-Request") and tab == "matchs":
        return templates.TemplateResponse(
            request,
            "joueurs/includes/_tab_matchs.html",
            context,
        )

    return templates.TemplateResponse(
        request,
        "joueurs/detail.html",
        context,
    )
