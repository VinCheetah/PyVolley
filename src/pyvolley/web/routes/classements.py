"""
Route web pour les classements universels et multidimensionnels.
"""

from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, distinct

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import get_session
from pyvolley.database.models import SaisonDB, ClubDB, CompetitionDB
from pyvolley.database.ranking_service import (
    RankingService, RankingFilters, METRICS_CONFIG,
)

router = APIRouter()


@router.get("/classements", response_class=HTMLResponse)
def classements_page(
    request: Request,
    entity_type: str = Query("joueurs", description="Type d'entité : joueurs, equipes, clubs"),
    metric: Optional[str] = Query(None),
    saison_id: Optional[str] = Query(None),  # 'all' ou int
    departement: Optional[str] = Query(None),
    ligue: Optional[str] = Query(None),
    club_id: Optional[int] = Query(None),
    genre: Optional[str] = Query(None),
    categorie: Optional[str] = Query(None),
    niveau: Optional[str] = Query(None),
    role_principal: Optional[str] = Query(None),
    min_matchs: int = Query(1),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=10, le=100),
    order_direction: str = Query("desc"),
    session: Session = Depends(get_session),
):
    ranking_service = RankingService(session)

    # Résolution de la saison
    saisons = list(
        session.scalars(select(SaisonDB).order_by(SaisonDB.date_debut.desc().nulls_last(), SaisonDB.id.desc()))
    )
    resolved_saison_id: Optional[int] = None
    if saison_id and saison_id != "all":
        try:
            resolved_saison_id = int(saison_id)
        except ValueError:
            resolved_saison_id = None
    elif saison_id is None and saisons:
        # Par défaut, saison la plus récente pour équipes, ou carrière pour joueurs si demandé
        resolved_saison_id = saisons[0].id

    # Métrique par défaut
    available_metrics = METRICS_CONFIG.get(entity_type, METRICS_CONFIG["joueurs"])
    if not metric:
        metric = next((m["id"] for m in available_metrics if m.get("default")), available_metrics[0]["id"])

    filters = RankingFilters(
        entity_type=entity_type,
        metric=metric,
        saison_id=resolved_saison_id,
        departement=departement if departement else None,
        ligue=ligue if ligue else None,
        club_id=club_id,
        genre=genre if genre else None,
        categorie=categorie if categorie else None,
        niveau=niveau if niveau else None,
        role_principal=role_principal if role_principal else None,
        min_matchs=min_matchs,
        page=page,
        per_page=per_page,
        order_direction=order_direction,
    )

    result = ranking_service.get_ranking(filters)

    # Options pour les filtres
    ligues = list(
        session.scalars(
            select(distinct(ClubDB.ligue)).where(ClubDB.ligue.is_not(None), ClubDB.ligue != "").order_by(ClubDB.ligue.asc())
        )
    )
    departements = list(
        session.scalars(
            select(distinct(ClubDB.departement)).where(
                ClubDB.departement.is_not(None), ClubDB.departement != ""
            ).order_by(ClubDB.departement.asc())
        )
    )
    categories = list(
        session.scalars(
            select(distinct(CompetitionDB.categorie)).where(
                CompetitionDB.categorie.is_not(None), CompetitionDB.categorie != ""
            ).order_by(CompetitionDB.categorie.asc())
        )
    )
    niveaux = list(
        session.scalars(
            select(distinct(CompetitionDB.niveau)).where(
                CompetitionDB.niveau.is_not(None), CompetitionDB.niveau != ""
            ).order_by(CompetitionDB.niveau.asc())
        )
    )
    postes = ["Passeur", "Central", "Réceptionneur-Attaquant", "Pointu", "Libéro"]

    return templates.TemplateResponse(
        "classements.html",
        {
            "request": request,
            "result": result,
            "saisons": saisons,
            "current_saison_id": resolved_saison_id,
            "is_all_time": (saison_id == "all" or resolved_saison_id is None),
            "ligues": ligues,
            "departements": departements,
            "categories": categories,
            "niveaux": niveaux,
            "postes": postes,
            "filters": filters,
            "metrics_config": available_metrics,
        },
    )
