"""
Routes web — Joueurs (liste et fiche détaillée).

Délègue l'assemblage métier et analytique au JoueurViewService.
Les routes sont exécutées de manière synchrone (`def`) pour tirer parti
du threadpool Starlette de FastAPI sans bloquer l'Event Loop.
"""

from datetime import date as dt_date
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


# Backwards compatibility re-exports
def _extract_youth_ages_from_text(value: Optional[str]) -> list[int]:
    return JoueurViewService.extract_youth_ages_from_text(value)


def _estimate_player_max_age(rows: list[dict], reference_date: Optional[dt_date] = None) -> Optional[dict]:
    ref_date = reference_date or dt_date.today()
    age_candidates: list[dict] = []
    for row in rows:
        season_end_yr = JoueurViewService.season_end_year_from_row(row)
        if not season_end_yr:
            continue
        match = row.get("match")
        competition = row.get("competition")
        equipe_joueur = row.get("equipe_joueur")
        saison = row.get("saison")
        season_code = saison.code if saison else None

        texts_to_inspect: list[Optional[str]] = []
        if competition:
            texts_to_inspect.extend([getattr(competition, "nom", None), getattr(competition, "categorie", None), getattr(competition, "division", None)])
        if equipe_joueur:
            texts_to_inspect.extend([getattr(equipe_joueur, "nom", None), getattr(equipe_joueur, "categorie", None), getattr(equipe_joueur, "division", None)])

        detected_ages: set[int] = set()
        for text in texts_to_inspect:
            detected_ages.update(JoueurViewService.extract_youth_ages_from_text(text))

        for age_limit in detected_ages:
            b_min, b_max = JoueurViewService.compute_birth_date_bounds(age_limit, season_end_yr)
            age_candidates.append({
                "age_limit": age_limit,
                "season_code": season_code,
                "season_end_year": season_end_yr,
                "match_id": match.id if match else None,
                "birth_date_min": b_min,
                "birth_date_max": b_max,
            })

    return JoueurViewService.estimate_player_age(age_candidates, ref_date)



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
    template_name = "joueurs/_list_results.html" if request.headers.get("HX-Request") else "joueurs/list.html"
    return templates.TemplateResponse(
        request,
        template_name,
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
