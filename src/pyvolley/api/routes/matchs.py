"""
Routes API — Matchs.
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query

from pyvolley.api.dependencies import get_match_repo
from pyvolley.api.schemas import MatchResponse, MatchDetail
from pyvolley.api.converters import match_to_response, match_to_detail
from pyvolley.database.repositories import MatchRepository

router = APIRouter()


@router.get("/matchs", response_model=List[MatchResponse])
async def list_matchs(
    competition_id: Optional[int] = None,
    saison_id: Optional[int] = None,
    equipe_nom: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: MatchRepository = Depends(get_match_repo),
):
    matchs = repo.search(
        competition_id=competition_id,
        saison_id=saison_id,
        equipe_nom=equipe_nom,
        limit=limit,
    )
    return [match_to_response(m) for m in matchs]


@router.get("/matchs/{match_id}", response_model=MatchDetail)
async def get_match(
    match_id: int,
    repo: MatchRepository = Depends(get_match_repo),
):
    match = repo.get_with_details(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match non trouvé")
    return match_to_detail(match)
