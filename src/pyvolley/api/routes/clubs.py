"""
Routes API — Clubs.
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query

from pyvolley.api.dependencies import get_club_repo
from pyvolley.api.schemas import ClubResponse, ClubDetail
from pyvolley.database.repositories import ClubRepository

router = APIRouter()


@router.get("/clubs", response_model=List[ClubResponse])
async def list_clubs(
    q: Optional[str] = Query(None, min_length=2),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: ClubRepository = Depends(get_club_repo),
):
    if q:
        clubs = repo.search_by_name(q, limit=limit)
    else:
        clubs = repo.get_all(limit=limit, offset=offset)
    return [ClubResponse.model_validate(c) for c in clubs]


@router.get("/clubs/{club_id}", response_model=ClubDetail)
async def get_club(
    club_id: int,
    repo: ClubRepository = Depends(get_club_repo),
):
    club = repo.get(club_id)
    if not club:
        raise HTTPException(status_code=404, detail="Club non trouvé")
    return ClubDetail(
        id=club.id,
        nom=club.nom,
        nom_court=club.nom_court,
        ville=club.ville,
        departement=club.departement,
        code_ffvb=club.code_ffvb,
        equipes_count=len(club.equipes) if club.equipes else 0,
    )
