"""
Routes web — Poules (détail d'une poule).
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import (
    get_poule_repo,
    get_competition_repo,
    get_match_repo,
)
from pyvolley.database.repositories import (
    PouleRepository,
    CompetitionRepository,
    MatchRepository,
)

router = APIRouter()


@router.get("/poules/{poule_id}", response_class=HTMLResponse)
async def poule_detail(
    request: Request,
    poule_id: int,
    poule_repo: PouleRepository = Depends(get_poule_repo),
    competition_repo: CompetitionRepository = Depends(get_competition_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Page de détail d'une poule, vue comme compétition à part entière."""
    poule = poule_repo.get_with_details(poule_id)
    if not poule:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Poule non trouvée"},
            status_code=404,
        )

    competition = poule.competition

    # Detect youth competition
    from pyvolley.scrapers.ffvb.jeunes import is_youth_competition

    is_youth = is_youth_competition(competition.nom) if competition else False

    # Classement spécifique à cette poule
    classement = competition_repo.get_classement_for_poule(poule_id)
    evolution_json = []
    if not is_youth and classement and classement.evolution:
        evolution_json = [e.model_dump(mode="json") for e in classement.evolution]

    # Matchs de la poule uniquement
    matchs = match_repo.search(competition_id=competition.id, limit=500)
    matchs = [m for m in matchs if m.poule_id == poule_id]

    # Équipes de la poule (déduites des matchs)
    equipe_ids = set()
    for m in matchs:
        if m.equipe_a_id:
            equipe_ids.add(m.equipe_a_id)
        if m.equipe_b_id:
            equipe_ids.add(m.equipe_b_id)

    # Poules sœurs
    sibling_poules = sorted(
        [p for p in competition.poules if p.id != poule_id],
        key=lambda p: p.code,
    )

    return templates.TemplateResponse(
        "poules/detail.html",
        {
            "request": request,
            "poule": poule,
            "competition": competition,
            "classement": classement,
            "evolution_json": evolution_json,
            "matchs": matchs,
            "nb_equipes": len(equipe_ids),
            "sibling_poules": sibling_poules,
            "is_youth": is_youth,
        },
    )
