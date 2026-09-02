"""
Routes API — Statistiques globales.
"""

from fastapi import APIRouter, Depends

from pyvolley.api.dependencies import (
    get_joueur_repo,
    get_club_repo,
    get_equipe_repo,
    get_match_repo,
    get_saison_repo,
    get_competition_repo,
    get_arbitre_repo,
)
from pyvolley.api.schemas import StatsOverview
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


@router.get("/stats", response_model=StatsOverview)
async def get_stats(
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
    competition_repo: CompetitionRepository = Depends(get_competition_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    saisons = saison_repo.get_all(limit=50)
    matchs_par_saison_raw = match_repo.count_by_saison()
    matchs_par_mois_raw = match_repo.get_stats_by_month()

    return StatsOverview(
        total_matchs=match_repo.count(),
        total_joueurs=joueur_repo.count(),
        total_clubs=club_repo.count(),
        total_equipes=equipe_repo.count(),
        total_arbitres=arbitre_repo.count(),
        total_competitions=competition_repo.count(),
        saisons=[s.code for s in saisons],
        matchs_par_saison={code: count for code, count in matchs_par_saison_raw},
        matchs_par_mois=[
            {"year": int(y), "month": int(m), "count": c}
            for y, m, c in matchs_par_mois_raw
        ],
    )


@router.get("/stats/palmares")
async def get_palmares(
    saison_id: Optional[int] = None,
    genre: Optional[str] = None,
    categorie: Optional[str] = None,
    niveau_min: Optional[str] = None,
    niveau_max: Optional[str] = None,
    departement: Optional[str] = None,
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Palmarès et records complets."""
    from pyvolley.database.stats_service import StatsAmusantesService, StatsFilters

    service = StatsAmusantesService(match_repo.session)
    filters = StatsFilters(
        saison_id=saison_id,
        genre=genre,
        categorie=categorie,
        niveau_min=niveau_min,
        niveau_max=niveau_max,
        departement=departement,
    )
    data, from_cache = service.get_cached_or_compute(filters)
    return {
        "from_cache": from_cache,
        "results": data,
    }


@router.get("/stats/leaderboards/scorers")
async def get_top_scorers(
    saison_id: Optional[int] = None,
    competition_id: Optional[int] = None,
    limit: int = 20,
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Classement des meilleurs marqueurs depuis les rollups."""
    from pyvolley.database.repositories import JoueurSaisonStatsRepository

    repo = JoueurSaisonStatsRepository(match_repo.session)
    return repo.get_top_scorers(saison_id=saison_id, competition_id=competition_id, limit=limit)


@router.get("/stats/leaderboards/servers")
async def get_top_servers(
    saison_id: Optional[int] = None,
    competition_id: Optional[int] = None,
    limit: int = 20,
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Classement des meilleurs serveurs depuis les rollups."""
    from pyvolley.database.repositories import JoueurSaisonStatsRepository

    repo = JoueurSaisonStatsRepository(match_repo.session)
    return repo.get_top_servers(saison_id=saison_id, competition_id=competition_id, limit=limit)


@router.get("/stats/leaderboards/career")
async def get_top_career(
    limit: int = 20,
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Classement carrière des joueurs avec le plus de points marqués."""
    from pyvolley.database.repositories import JoueurCarriereStatsRepository

    repo = JoueurCarriereStatsRepository(match_repo.session)
    return repo.get_top_career_scorers(limit=limit)

