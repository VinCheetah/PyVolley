"""
Routes API — Recherche globale.
"""

from fastapi import APIRouter, Depends, Query

from pyvolley.api.dependencies import (
    get_joueur_repo,
    get_club_repo,
    get_equipe_repo,
    get_arbitre_repo,
)
from pyvolley.api.schemas import (
    JoueurResponse,
    ClubResponse,
    EquipeResponse,
    ArbitreResponse,
    SearchResult,
)
from pyvolley.database.repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    ArbitreRepository,
)

router = APIRouter()


@router.get("/search", response_model=SearchResult)
async def search(
    q: str = Query(..., min_length=2, description="Terme de recherche"),
    limit: int = Query(10, ge=1, le=50),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    """Recherche globale dans joueurs, clubs, équipes et arbitres."""
    joueurs = joueur_repo.search_by_name(q, limit=limit)
    clubs = club_repo.search_by_name(q, limit=limit)
    equipes = equipe_repo.search_by_name(q, limit=limit)
    arbitres = arbitre_repo.search_by_name(q, limit=limit)

    return SearchResult(
        joueurs=[JoueurResponse.model_validate(j) for j in joueurs],
        clubs=[ClubResponse.model_validate(c) for c in clubs],
        equipes=[EquipeResponse.model_validate(e) for e in equipes],
        arbitres=[ArbitreResponse.model_validate(a) for a in arbitres],
        total=len(joueurs) + len(clubs) + len(equipes) + len(arbitres),
    )
