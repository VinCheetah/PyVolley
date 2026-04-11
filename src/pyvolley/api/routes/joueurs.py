"""
Routes API — Joueurs.
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func

from pyvolley.api.dependencies import get_joueur_repo, get_match_repo
from pyvolley.api.schemas import JoueurResponse, JoueurDetail, MatchResponse
from pyvolley.api.converters import match_to_response
from pyvolley.database.repositories import (
    JoueurRepository,
    MatchRepository,
    JoueurStatsCacheRepository,
)
from pyvolley.database.models import ParticipationMatchDB
from pyvolley.analysis.joueur_stats import aggregate_joueur_stats
from pyvolley.database.player_stats_service import JoueurMatchStatsService

router = APIRouter()


@router.get("/joueurs", response_model=List[JoueurResponse])
async def list_joueurs(
    q: Optional[str] = Query(None, min_length=2),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: JoueurRepository = Depends(get_joueur_repo),
):
    if q:
        joueurs = repo.search_by_name(q, limit=limit)
    else:
        joueurs = repo.get_all(limit=limit, offset=offset)
    return [JoueurResponse.model_validate(j) for j in joueurs]


@router.get("/joueurs/{joueur_id}", response_model=JoueurDetail)
async def get_joueur(
    joueur_id: int,
    repo: JoueurRepository = Depends(get_joueur_repo),
):
    joueur = repo.get(joueur_id)
    if not joueur:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")
    stats = repo.get_stats(joueur_id)
    return JoueurDetail(
        id=joueur.id,
        licence=joueur.licence,
        nom=joueur.nom,
        prenom=joueur.prenom,
        matchs_joues=stats.get("matchs_joues", 0),
        equipes=stats.get("equipes", []),
        saisons=stats.get("saisons", []),
        capitaine_count=stats.get("capitaine_count", 0),
        libero_count=stats.get("libero_count", 0),
    )


@router.get("/joueurs/{joueur_id}/matchs", response_model=List[MatchResponse])
async def get_joueur_matchs(
    joueur_id: int,
    limit: int = Query(50, ge=1, le=200),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    joueur = joueur_repo.get(joueur_id)
    if not joueur:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")
    matchs = match_repo.get_by_joueur(joueur_id, limit=limit)
    return [match_to_response(m) for m in matchs]


@router.get("/joueurs/{joueur_id}/matchs/{match_id}/stats")
async def get_joueur_match_stats(
    joueur_id: int,
    match_id: int,
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
):
    stats = joueur_repo.get_match_stats(joueur_id, match_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Participation non trouvée")
    return {
        "joueur_id": joueur_id,
        "match_id": match_id,
        "side": stats["side"],
        "numero_maillot": stats["numero_maillot"],
        "est_capitaine": stats["est_capitaine"],
        "est_libero": stats["est_libero"],
        "sets_titulaire": stats["sets_titulaire"],
        "sets_entrant": stats["sets_entrant"],
    }


@router.get("/joueurs/{joueur_id}/matchs/{match_id}/detailed-stats")
async def get_joueur_match_detailed_stats(
    joueur_id: int,
    match_id: int,
    remplace_par_libero: bool = Query(False),
    est_mode_libero: bool = Query(False),
    joueurs_remplaces: Optional[str] = Query(
        None, description="Numéros séparés par des virgules"
    ),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Statistiques détaillées d'un joueur sur un match."""
    from pyvolley.database.converters import match_db_to_core
    from pyvolley.analysis.joueur_stats import analyze_joueur_match

    joueur = joueur_repo.get(joueur_id)
    if not joueur:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")

    match_db = match_repo.get_with_details(match_id)
    if not match_db:
        raise HTTPException(status_code=404, detail="Match non trouvé")

    stats_service = JoueurMatchStatsService(match_repo.session)

    # Mode standard : servir depuis les stats persistées (pas de recalcul runtime)
    has_custom_mode = remplace_par_libero or est_mode_libero or bool(joueurs_remplaces)
    if not has_custom_mode:
        stats_service.compute_and_store_for_match(match_db)
        persisted = stats_service.get_joueur_match_stats(joueur_id, match_id)
        if persisted:
            return persisted.model_dump(mode="json")

    participants_a = [
        p
        for p in (match_db.participations or [])
        if p.equipe_id == match_db.equipe_a_id
    ]
    participants_b = [
        p
        for p in (match_db.participations or [])
        if p.equipe_id == match_db.equipe_b_id
    ]

    match_core = match_db_to_core(match_db, participants_a, participants_b)

    remplaces = (
        [n.strip() for n in joueurs_remplaces.split(",") if n.strip()]
        if joueurs_remplaces
        else None
    )

    stats = analyze_joueur_match(
        match_core,
        joueur.licence,
        remplace_par_libero=remplace_par_libero,
        est_mode_libero=est_mode_libero,
        joueurs_remplaces_numeros=remplaces,
    )
    if not stats:
        raise HTTPException(
            status_code=404, detail="Joueur non trouvé dans ce match"
        )

    return stats.model_dump()


@router.get("/joueurs/{joueur_id}/aggregated-stats")
async def get_joueur_aggregated_stats(
    joueur_id: int,
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Statistiques agrégées d'un joueur sur tous ses matchs."""
    joueur = joueur_repo.get(joueur_id)
    if not joueur:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")

    cache_repo = JoueurStatsCacheRepository(match_repo.session)
    current_match_count = match_repo.session.scalar(
        select(func.count())
        .select_from(ParticipationMatchDB)
        .where(ParticipationMatchDB.joueur_id == joueur_id)
    ) or 0

    cache_entry = cache_repo.get_by_joueur(joueur_id)
    if (
        cache_entry
        and cache_entry.match_count == current_match_count
        and cache_entry.aggregated_stats
    ):
        return cache_entry.aggregated_stats

    stats_service = JoueurMatchStatsService(match_repo.session)
    all_stats = stats_service.get_joueur_all_stats(
        joueur_id,
        limit=max(500, current_match_count + 50),
    )
    aggregated = aggregate_joueur_stats(all_stats)

    cache_repo.upsert(
        joueur_id=joueur_id,
        aggregated_stats=aggregated.model_dump(mode="json") if aggregated else None,
        per_match_stats=None,
        match_count=current_match_count,
    )

    if not aggregated:
        return {"message": "Aucune statistique disponible"}

    return aggregated.model_dump()


@router.get("/matchs/{match_id}/all-player-stats")
async def get_match_all_player_stats(
    match_id: int,
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Statistiques détaillées de tous les joueurs d'un match."""
    match_db = match_repo.get_with_details(match_id)
    if not match_db:
        raise HTTPException(status_code=404, detail="Match non trouvé")

    stats_service = JoueurMatchStatsService(match_repo.session)
    stats_service.compute_and_store_for_match(match_db)
    stats_a_wrapped, stats_b_wrapped = stats_service.get_match_stats_grouped(match_id)
    stats_a = [item["stats"] for item in stats_a_wrapped]
    stats_b = [item["stats"] for item in stats_b_wrapped]

    return {
        "match_id": match_id,
        "equipe_a": match_db.equipe_a.nom if match_db.equipe_a else "Équipe A",
        "equipe_b": match_db.equipe_b.nom if match_db.equipe_b else "Équipe B",
        "stats_a": stats_a,
        "stats_b": stats_b,
    }
