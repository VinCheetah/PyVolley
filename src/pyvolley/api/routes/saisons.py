"""
Routes API — Saisons.
"""

from typing import List

from fastapi import APIRouter, Depends

from pyvolley.api.dependencies import get_saison_repo
from pyvolley.api.schemas import SaisonResponse
from pyvolley.database.repositories import SaisonRepository

router = APIRouter()


@router.get("/saisons", response_model=List[SaisonResponse])
async def list_saisons(
    repo: SaisonRepository = Depends(get_saison_repo),
):
    saisons = repo.get_all(limit=50)
    return [SaisonResponse.model_validate(s) for s in saisons]
