"""
Route web pour la vue dédiée Carte Interactive (/carte).

Fournit la page d'exploration cartographique complète avec l'ensemble des
options de filtrage géographique, sportif et temporel.
"""

from typing import Optional
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, distinct

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import get_session
from pyvolley.database.models import SaisonDB, ClubDB, CompetitionDB

router = APIRouter()


@router.get("/carte", response_class=HTMLResponse)
def carte_page(
    request: Request,
    entity_type: Optional[str] = Query("club", description="Filtre d'entité : club, salle"),
    saison_id: Optional[int] = Query(None, description="ID de saison"),
    ligue: Optional[str] = Query(None, description="Nom de la ligue régionale"),
    departement: Optional[str] = Query(None, description="Code département"),
    competition_id: Optional[int] = Query(None, description="ID de compétition"),
    club_id: Optional[int] = Query(None, description="ID de club"),
    zone: Optional[str] = Query("metropole", description="Zone géographique"),
    q: Optional[str] = Query(None, description="Terme de recherche"),
    session: Session = Depends(get_session),
):
    """Affiche la vue cartographique immersive de PyVolley."""
    if entity_type == "match" or not entity_type:
        entity_type = "club"

    # 1. Saisons disponibles
    saisons = list(
        session.scalars(
            select(SaisonDB).order_by(SaisonDB.date_debut.desc().nulls_last(), SaisonDB.id.desc())
        )
    )
    if saison_id is None and saisons:
        saison_id = saisons[0].id

    # 2. Ligues régionales distinctes (triées alphabétiquement)
    raw_ligues = session.scalars(
        select(distinct(ClubDB.ligue))
        .where(ClubDB.ligue.is_not(None), ClubDB.ligue != "")
        .order_by(ClubDB.ligue)
    ).all()
    ligues = [l.strip() for l in raw_ligues if l and l.strip()]

    # 3. Départements distincts (triés naturellement)
    raw_depts = session.scalars(
        select(distinct(ClubDB.departement))
        .where(ClubDB.departement.is_not(None), ClubDB.departement != "")
    ).all()

    def _dept_sort_key(d: str):
        cleaned = d.strip().upper()
        if cleaned.isdigit():
            return (0, int(cleaned), cleaned)
        return (1, 0, cleaned)

    departements = sorted([d.strip().upper() for d in raw_depts if d and d.strip()], key=_dept_sort_key)

    # 4. Compétitions pour la saison sélectionnée (ou récentes)
    comp_stmt = select(CompetitionDB).order_by(CompetitionDB.nom)
    if saison_id:
        comp_stmt = comp_stmt.where(CompetitionDB.saison_id == saison_id)
    competitions = list(session.scalars(comp_stmt.limit(200)))

    # 5. Clubs référencés pour la sélection rapide
    club_stmt = select(ClubDB.id, ClubDB.nom, ClubDB.ville, ClubDB.departement).order_by(ClubDB.nom)
    if ligue:
        club_stmt = club_stmt.where(ClubDB.ligue == ligue)
    if departement:
        club_stmt = club_stmt.where(ClubDB.departement == departement)
    clubs_summary = [
        {
            "id": row.id,
            "nom": row.nom,
            "ville": row.ville or "",
            "departement": row.departement or "",
        }
        for row in session.execute(club_stmt.limit(300))
    ]

    return templates.TemplateResponse(
        "carte.html",
        {
            "request": request,
            "saisons": saisons,
            "current_saison_id": saison_id,
            "ligues": ligues,
            "departements": departements,
            "competitions": competitions,
            "clubs": clubs_summary,
            "selected_entity_type": entity_type or "club",
            "selected_zone": zone or "metropole",
            "selected_ligue": ligue or "",
            "selected_departement": departement or "",
            "selected_competition_id": competition_id,
            "selected_club_id": club_id,
            "search_query": q or "",
        },
    )
