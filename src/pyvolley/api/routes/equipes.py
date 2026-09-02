"""
Routes API — Équipes.
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query

from pyvolley.api.dependencies import get_equipe_repo, get_match_repo
from pyvolley.api.schemas import EquipeResponse, EquipeDetail, MatchResponse
from pyvolley.api.converters import match_to_response
from pyvolley.shared.helpers import is_winner
from pyvolley.database.repositories import EquipeRepository, MatchRepository

router = APIRouter()


@router.get("/equipes", response_model=List[EquipeResponse])
async def list_equipes(
    q: Optional[str] = Query(None, min_length=2),
    club_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: EquipeRepository = Depends(get_equipe_repo),
):
    if q:
        equipes = repo.search_by_name(q, limit=limit)
    elif club_id:
        equipes = repo.get_by_club(club_id)
    else:
        equipes = repo.get_all(limit=limit, offset=offset)
    return [EquipeResponse.model_validate(e) for e in equipes]


@router.get("/equipes/{equipe_id}", response_model=EquipeDetail)
async def get_equipe(
    equipe_id: int,
    repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    equipe = repo.get(equipe_id)
    if not equipe:
        raise HTTPException(status_code=404, detail="Équipe non trouvée")
    matchs = match_repo.get_by_equipe(equipe_id, limit=200)
    victoires = sum(1 for m in matchs if is_winner(m, equipe))
    return EquipeDetail(
        id=equipe.id,
        nom=equipe.nom,
        club_id=equipe.club_id,
        genre=equipe.genre,
        categorie=equipe.categorie,
        club_nom=equipe.club.nom if equipe.club else None,
        saison_code=equipe.saison.code if equipe.saison else None,
        matchs_count=len(matchs),
        victoires=victoires,
        defaites=len(matchs) - victoires,
    )


@router.get("/equipes/{equipe_id}/matchs", response_model=List[MatchResponse])
async def get_equipe_matchs(
    equipe_id: int,
    limit: int = Query(50, ge=1, le=200),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    equipe = equipe_repo.get(equipe_id)
    if not equipe:
        raise HTTPException(status_code=404, detail="Équipe non trouvée")
    matchs = match_repo.get_by_equipe(equipe_id, limit=limit)
    return [match_to_response(m) for m in matchs]


@router.get("/equipes/{equipe_id}/saisons-stats")
async def get_equipe_saisons_stats(
    equipe_id: int,
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    """Statistiques agglomérées par saison d'une équipe."""
    from pyvolley.database.repositories import EquipeSaisonStatsRepository

    repo = EquipeSaisonStatsRepository(equipe_repo.session)
    rows = repo.get_for_equipe(equipe_id)
    return [
        {
            "id": r.id,
            "saison_id": r.saison_id,
            "saison_code": r.saison.code if r.saison else None,
            "competition_id": r.competition_id,
            "competition_nom": r.competition.nom if r.competition else None,
            "poule_id": r.poule_id,
            "poule_code": r.poule.code if r.poule else None,
            "matchs_joues": r.matchs_joues,
            "victoires": r.victoires,
            "defaites": r.defaites,
            "victoires_domicile": r.victoires_domicile,
            "victoires_exterieur": r.victoires_exterieur,
            "victoires_3_0": r.victoires_3_0,
            "victoires_3_1": r.victoires_3_1,
            "victoires_3_2": r.victoires_3_2,
            "defaites_2_3": r.defaites_2_3,
            "defaites_1_3": r.defaites_1_3,
            "defaites_0_3": r.defaites_0_3,
            "forfaits": r.forfaits,
            "sets_pour": r.sets_pour,
            "sets_contre": r.sets_contre,
            "ratio_sets": r.ratio_sets,
            "points_pour": r.points_pour,
            "points_contre": r.points_contre,
            "ratio_points": r.ratio_points,
            "serie_victoires_max": r.serie_victoires_max,
            "serie_en_cours": r.serie_en_cours,
        }
        for r in rows
    ]


@router.get("/equipes/standings")
async def get_equipes_standings(
    saison_id: int = Query(...),
    competition_id: Optional[int] = Query(None),
    poule_id: Optional[int] = Query(None),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    """Classement d'une poule ou compétition calculé depuis stats_equipe_saison."""
    from pyvolley.database.repositories import EquipeSaisonStatsRepository

    repo = EquipeSaisonStatsRepository(equipe_repo.session)
    rows = repo.get_standings(saison_id=saison_id, competition_id=competition_id, poule_id=poule_id)
    return [
        {
            "equipe_id": r.equipe_id,
            "equipe_nom": r.equipe.nom if r.equipe else None,
            "matchs_joues": r.matchs_joues,
            "victoires": r.victoires,
            "defaites": r.defaites,
            "sets_pour": r.sets_pour,
            "sets_contre": r.sets_contre,
            "ratio_sets": r.ratio_sets,
            "points_pour": r.points_pour,
            "points_contre": r.points_contre,
            "ratio_points": r.ratio_points,
            "serie_en_cours": r.serie_en_cours,
        }
        for r in rows
    ]

