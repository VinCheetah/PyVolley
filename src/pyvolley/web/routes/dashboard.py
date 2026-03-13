"""
Routes web — Tableau de bord (page d'accueil).
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import (
    get_joueur_repo,
    get_club_repo,
    get_equipe_repo,
    get_match_repo,
    get_saison_repo,
    get_competition_repo,
    get_arbitre_repo,
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


@router.get("/", response_class=HTMLResponse)
async def index(
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
    derniers_matchs = match_repo.search(limit=10)
    saisons = saison_repo.get_all(limit=20)

    matchs_par_saison = match_repo.count_by_saison()
    matchs_par_mois = match_repo.get_stats_by_month()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "derniers_matchs": derniers_matchs,
            "saisons": saisons,
            "matchs_par_saison": [
                {"saison": code, "count": count}
                for code, count in matchs_par_saison
            ],
            "matchs_par_mois": [
                {"year": int(y), "month": int(m), "count": c}
                for y, m, c in matchs_par_mois
            ],
        },
    )
