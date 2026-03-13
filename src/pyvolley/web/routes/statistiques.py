"""
Routes web — Statistiques et Palmarès.
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import (
    get_joueur_repo,
    get_club_repo,
    get_equipe_repo,
    get_match_repo,
    get_saison_repo,
    get_competition_repo,
    get_arbitre_repo,
    get_session,
)
from pyvolley.database.repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    MatchRepository,
    SaisonRepository,
    CompetitionRepository,
    ArbitreRepository,
)

router = APIRouter()


@router.get("/statistiques", response_class=HTMLResponse)
async def stats_page(
    request: Request,
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
    competition_repo: CompetitionRepository = Depends(get_competition_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    stats = {
        "matchs": match_repo.count(),
        "joueurs": joueur_repo.count(),
        "clubs": club_repo.count(),
        "equipes": equipe_repo.count(),
        "arbitres": arbitre_repo.count(),
        "competitions": competition_repo.count(),
    }
    matchs_par_saison = match_repo.count_by_saison()
    matchs_par_mois = match_repo.get_stats_by_month()
    saisons = saison_repo.get_all(limit=20)

    return templates.TemplateResponse(
        "statistiques.html",
        {
            "request": request,
            "stats": stats,
            "matchs_par_saison": [
                {"saison": code, "count": count}
                for code, count in matchs_par_saison
            ],
            "matchs_par_mois": [
                {"year": int(y), "month": int(m), "count": c}
                for y, m, c in matchs_par_mois
            ],
            "saisons": saisons,
        },
    )


@router.get("/palmares", response_class=HTMLResponse)
async def palmares_page(
    request: Request,
    saison_id: Optional[int] = Query(None),
    genre: Optional[str] = Query(None),
    categorie: Optional[str] = Query(None),
    niveau_min: Optional[str] = Query(None),
    niveau_max: Optional[str] = Query(None),
    departement: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from pyvolley.database.stats_service import StatsAmusantesService, StatsFilters

    service = StatsAmusantesService(session)
    filters = StatsFilters(
        saison_id=saison_id,
        genre=genre,
        categorie=categorie,
        niveau_min=niveau_min,
        niveau_max=niveau_max,
        departement=departement,
    )

    all_stats, from_cache = service.get_cached_or_compute(filters)
    filter_options = service.get_filter_options()

    return templates.TemplateResponse(
        "palmares.html",
        {
            "request": request,
            **all_stats,
            "filter_options": filter_options,
            "from_cache": from_cache,
            "current_filters": {
                "saison_id": saison_id,
                "genre": genre or "",
                "categorie": categorie or "",
                "niveau_min": niveau_min or "",
                "niveau_max": niveau_max or "",
                "departement": departement or "",
            },
        },
    )
