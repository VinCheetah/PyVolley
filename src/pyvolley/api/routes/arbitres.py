"""
Routes API — Arbitres.
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query

from pyvolley.api.dependencies import get_arbitre_repo
from pyvolley.api.schemas import ArbitreResponse, ArbitreDetail, MatchResponse
from pyvolley.api.converters import match_to_response
from pyvolley.database.repositories import ArbitreRepository

router = APIRouter()


@router.get("/arbitres", response_model=List[ArbitreResponse])
async def list_arbitres(
    q: Optional[str] = Query(None, min_length=2),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    if q:
        arbitres = repo.search_by_name(q, limit=limit)
    else:
        arbitres = repo.get_all(limit=limit, offset=offset)
    return [ArbitreResponse.model_validate(a) for a in arbitres]


@router.get("/arbitres/{arbitre_id}", response_model=ArbitreDetail)
async def get_arbitre(
    arbitre_id: int,
    repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    arbitre = repo.get(arbitre_id)
    if not arbitre:
        raise HTTPException(status_code=404, detail="Arbitre non trouvé")
    stats = repo.get_stats(arbitre_id)
    return ArbitreDetail(
        id=arbitre.id,
        nom=arbitre.nom,
        prenom=arbitre.prenom,
        licence=arbitre.licence,
        ligue=arbitre.ligue,
        matchs_count=stats.get("matchs_count", 0),
        roles=stats.get("roles", {}),
    )


@router.get("/arbitres/{arbitre_id}/matchs", response_model=List[MatchResponse])
async def get_arbitre_matchs(
    arbitre_id: int,
    limit: int = Query(50, ge=1, le=200),
    repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    arbitre = repo.get(arbitre_id)
    if not arbitre:
        raise HTTPException(status_code=404, detail="Arbitre non trouvé")
    matchs = repo.get_matchs(arbitre_id, limit=limit)
    return [match_to_response(m) for m in matchs]
