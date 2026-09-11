"""
Route web pour l'analyse globale et territoriale du volleyball français.
"""

from typing import Optional
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import get_session
from pyvolley.database.models import SaisonDB
from pyvolley.database.geographic_service import GeographicStatsService
from pyvolley.database.licence_analysis_service import LicenceAnalysisService

router = APIRouter()


@router.get("/territoire", response_class=HTMLResponse)
def territoire_page(
    request: Request,
    saison_id: Optional[int] = Query(None),
    ligue: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    geo_service = GeographicStatsService(session)
    licence_service = LicenceAnalysisService(session)

    saisons = list(
        session.scalars(select(SaisonDB).order_by(SaisonDB.date_debut.desc().nulls_last(), SaisonDB.id.desc()))
    )
    if saison_id is None and saisons:
        saison_id = saisons[0].id

    # Données géographiques
    national_overview = geo_service.get_national_overview(saison_id=saison_id)
    regions = geo_service.get_regions_list(saison_id=saison_id)
    departements = geo_service.get_departements_list(ligue=ligue, saison_id=saison_id)

    # Données licences & démographie
    licence_report = None
    retention_report = None
    if saison_id:
        licence_report = licence_service.get_licence_report(saison_id)

        # Chercher la saison précédente pour la rétention
        current_idx = next((i for i, s in enumerate(saisons) if s.id == saison_id), None)
        if current_idx is not None and current_idx + 1 < len(saisons):
            prev_saison = saisons[current_idx + 1]
            retention_report = licence_service.get_retention_flow(prev_saison.id, saison_id)

    return templates.TemplateResponse(
        "territoire.html",
        {
            "request": request,
            "saisons": saisons,
            "current_saison_id": saison_id,
            "national": national_overview,
            "regions": regions,
            "departements": departements,
            "selected_ligue": ligue,
            "licence_report": licence_report,
            "retention_report": retention_report,
        },
    )
