"""
Routes web — Statistiques et Palmarès.
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, func, distinct

from pyvolley.web.templateconfig import templates
from pyvolley.web.helpers.time_filter import build_time_filter
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
from pyvolley.database.models import (
    MatchDB,
    ParticipationMatchDB,
    EquipeDB,
    ArbitreMatchDB,
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
def stats_page(
    request: Request,
    saison_id: Optional[int] = Query(None),
    saison_ids: Optional[list[int]] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    after_date: Optional[str] = Query(None),
    before_date: Optional[str] = Query(None),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
    competition_repo: CompetitionRepository = Depends(get_competition_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
    session: Session = Depends(get_session),
):
    time_filter = build_time_filter(
        season_ids=saison_ids,
        season_id=saison_id,
        date_from=date_from,
        date_to=date_to,
        after_date=after_date,
        before_date=before_date,
    )

    if time_filter.is_active:
        base_match_stmt = select(MatchDB.id)
        base_match_stmt = time_filter.apply_to_match_stmt(base_match_stmt, MatchDB)
        filtered_match_ids = list(session.scalars(base_match_stmt).all())

        if filtered_match_ids:
            stats = {
                "matchs": len(filtered_match_ids),
                "joueurs": session.scalar(
                    select(func.count(distinct(ParticipationMatchDB.joueur_id)))
                    .where(ParticipationMatchDB.match_id.in_(filtered_match_ids))
                ) or 0,
                "clubs": session.scalar(
                    select(func.count(distinct(EquipeDB.club_id)))
                    .join(ParticipationMatchDB, ParticipationMatchDB.equipe_id == EquipeDB.id)
                    .where(ParticipationMatchDB.match_id.in_(filtered_match_ids))
                    .where(EquipeDB.club_id.isnot(None))
                ) or 0,
                "equipes": session.scalar(
                    select(func.count(distinct(ParticipationMatchDB.equipe_id)))
                    .where(ParticipationMatchDB.match_id.in_(filtered_match_ids))
                ) or 0,
                "arbitres": session.scalar(
                    select(func.count(distinct(ArbitreMatchDB.arbitre_id)))
                    .where(ArbitreMatchDB.match_id.in_(filtered_match_ids))
                ) or 0,
                "competitions": session.scalar(
                    select(func.count(distinct(MatchDB.competition_id)))
                    .where(MatchDB.id.in_(filtered_match_ids))
                    .where(MatchDB.competition_id.isnot(None))
                ) or 0,
            }
        else:
            stats = {
                "matchs": 0,
                "joueurs": 0,
                "clubs": 0,
                "equipes": 0,
                "arbitres": 0,
                "competitions": 0,
            }
    else:
        stats = {
            "matchs": match_repo.count(),
            "joueurs": joueur_repo.count(),
            "clubs": club_repo.count(),
            "equipes": equipe_repo.count(),
            "arbitres": arbitre_repo.count(),
            "competitions": competition_repo.count(),
        }

    matchs_par_saison = match_repo.count_by_saison(
        saison_ids=time_filter.season_ids,
        date_from=time_filter.date_from,
        date_to=time_filter.date_to,
    )
    matchs_par_mois = match_repo.get_stats_by_month(
        saison_ids=time_filter.season_ids,
        date_from=time_filter.date_from,
        date_to=time_filter.date_to,
    )
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
            "time_filter": time_filter.to_context(),
        },
    )


@router.get("/palmares", response_class=HTMLResponse)
def palmares_page(
    request: Request,
    saison_id: Optional[int] = Query(None),
    saison_ids: Optional[list[int]] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    after_date: Optional[str] = Query(None),
    before_date: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    categorie: Optional[str] = Query(None),
    niveau_min: Optional[str] = Query(None),
    niveau_max: Optional[str] = Query(None),
    departement: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from pyvolley.database.stats_service import StatsAmusantesService, StatsFilters

    time_filter = build_time_filter(
        season_ids=saison_ids,
        season_id=saison_id,
        date_from=date_from,
        date_to=date_to,
        after_date=after_date,
        before_date=before_date,
    )

    service = StatsAmusantesService(session)
    filters = StatsFilters(
        saison_id=saison_id,
        saison_ids=time_filter.season_ids,
        date_from=time_filter.date_from,
        date_to=time_filter.date_to,
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
                "saison_ids": time_filter.season_ids,
                "date_from": time_filter.date_from.isoformat() if time_filter.date_from else "",
                "date_to": time_filter.date_to.isoformat() if time_filter.date_to else "",
                "genre": genre or "",
                "categorie": categorie or "",
                "niveau_min": niveau_min or "",
                "niveau_max": niveau_max or "",
                "departement": departement or "",
            },
        },
    )
