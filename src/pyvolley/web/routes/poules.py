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
from pyvolley.web.helpers.cross_table import build_cross_table
from pyvolley.database.repositories import (
    PouleRepository,
    CompetitionRepository,
    MatchRepository,
)
from pyvolley.core.config import settings
from pyvolley.scrapers.ffvb.utils import build_competition_calendar_url, build_classement_url

router = APIRouter()


def _to_ffvb_saison(saison_code: str | None) -> str | None:
    if not saison_code:
        return None
    return saison_code.replace("-", "/")


@router.get("/poules/{identifier}", response_class=HTMLResponse)
def poule_detail(
    request: Request,
    identifier: str,
    poule_repo: PouleRepository = Depends(get_poule_repo),
    competition_repo: CompetitionRepository = Depends(get_competition_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Page de détail d'une poule, vue comme compétition à part entière."""
    poule = poule_repo.get_with_details(identifier)
    if not poule:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Poule non trouvée"},
            status_code=404,
        )

    poule_id = poule.id
    competition = poule.competition

    # Liens FFVB reconstruits à la volée (non persistés en base)
    if competition and competition.entite and competition.saison:
        saison = _to_ffvb_saison(competition.saison.code)
        if saison:
            poule.url_calendrier = build_competition_calendar_url(
                settings.ffvb_base_url,
                competition.entite.code,
                saison,
                poule.code,
            )
            poule.url_classement = build_classement_url(
                settings.ffvb_base_url,
                competition.entite.code,
                saison,
                poule.code,
            )
        else:
            poule.url_calendrier = None
            poule.url_classement = None
    else:
        poule.url_calendrier = None
        poule.url_classement = None

    # Detect youth competition
    from pyvolley.scrapers.ffvb.jeunes import is_youth_competition

    is_youth = is_youth_competition(competition.nom) if competition else False

    # Classement spécifique à cette poule
    classement = competition_repo.get_classement_for_poule(poule_id)
    evolution_json = []
    if not is_youth and classement and classement.evolution:
        evolution_json = [e.model_dump(mode="json") for e in classement.evolution]

    # Matchs de la poule uniquement (recherche directe par poule_id pour exhaustivité)
    matchs = match_repo.search(poule_id=poule_id, limit=2000)

    # Équipes enregistrées pour cette compétition / poule
    comp_equipes = competition_repo.get_equipes_for_competition(competition.id) if competition else []
    poule_equipes = [eq for eq in comp_equipes if getattr(eq, "poule_id", None) == poule_id] or None

    # Matrice des confrontations aller-retour
    cross_table = build_cross_table(
        classement.classement_actuel if classement else [],
        matchs,
        equipes_disponibles=poule_equipes,
    )

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

    # Calcul des journées uniques pour filtrage interactif
    journees_set = {m.journee for m in matchs if m.journee}
    journees_disponibles = sorted(
        list(journees_set),
        key=lambda j: int(j) if j.isdigit() else 999,
    )

    return templates.TemplateResponse(
        "poules/detail.html",
        {
            "request": request,
            "poule": poule,
            "competition": competition,
            "classement": classement,
            "evolution_json": evolution_json,
            "cross_table": cross_table,
            "matchs": matchs,
            "nb_equipes": len(equipe_ids),
            "sibling_poules": sibling_poules,
            "is_youth": is_youth,
            "journees_disponibles": journees_disponibles,
        },
    )
