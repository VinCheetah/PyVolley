"""
Routes API — Compétitions.
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query

from pyvolley.api.dependencies import get_competition_repo
from pyvolley.api.schemas import CompetitionResponse
from pyvolley.database.repositories import CompetitionRepository

router = APIRouter()


@router.get("/competitions", response_model=List[CompetitionResponse])
async def list_competitions(
    q: Optional[str] = Query(None, min_length=2),
    saison_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    repo: CompetitionRepository = Depends(get_competition_repo),
):
    if q:
        competitions = repo.search_by_name(q, limit=limit)
    elif saison_id:
        competitions = repo.get_by_saison(saison_id)
    else:
        competitions = repo.get_all(limit=limit)
    return [CompetitionResponse.model_validate(c) for c in competitions]


@router.get("/competitions/{competition_id}/classement")
async def get_competition_classement(
    competition_id: int,
    repo: CompetitionRepository = Depends(get_competition_repo),
):
    """Calcule et retourne le classement complet d'une compétition avec évolution."""
    classement = repo.get_classement(competition_id)
    if not classement:
        raise HTTPException(status_code=404, detail="Compétition non trouvée")
    return classement.model_dump()
