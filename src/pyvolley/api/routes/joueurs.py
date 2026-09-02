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
    JoueurSaisonStatsRepository,
    JoueurCarriereStatsRepository,
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

    current_match_count = match_repo.session.scalar(
        select(func.count())
        .select_from(ParticipationMatchDB)
        .where(ParticipationMatchDB.joueur_id == joueur_id)
    ) or 0

    stats_service = JoueurMatchStatsService(match_repo.session)
    all_stats = stats_service.get_joueur_all_stats(
        joueur_id,
        limit=max(500, current_match_count + 50),
    )
    aggregated = aggregate_joueur_stats(all_stats)

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


@router.get("/joueurs/{joueur_id}/saisons-stats")
async def get_joueur_saisons_stats(
    joueur_id: int,
    saison_id: Optional[int] = Query(None),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Statistiques agglomérées par saison d'un joueur."""
    from pyvolley.database.repositories import JoueurSaisonStatsRepository

    repo = JoueurSaisonStatsRepository(match_repo.session)
    rows = repo.get_for_joueur(joueur_id, saison_id=saison_id)
    return [
        {
            "id": r.id,
            "saison_id": r.saison_id,
            "saison_code": r.saison.code if r.saison else None,
            "competition_id": r.competition_id,
            "competition_nom": r.competition.nom if r.competition else None,
            "equipe_id": r.equipe_id,
            "equipe_nom": r.equipe.nom if r.equipe else None,
            "matchs_joues": r.matchs_joues,
            "matchs_titulaire": r.matchs_titulaire,
            "victoires": r.victoires,
            "defaites": r.defaites,
            "sets_joues": r.sets_joues,
            "sets_titulaire": r.sets_titulaire,
            "points_gagnes": r.points_gagnes,
            "points_perdus": r.points_perdus,
            "points_joues": r.points_joues,
            "points_service": r.points_service,
            "points_sideout": r.points_sideout,
            "services": r.services,
            "series": r.series,
            "max_serie": r.max_serie,
            "moyenne_services_par_serie": r.moyenne_services_par_serie,
            "ratio_points_gagnes": r.ratio_points_gagnes,
            "role_principal": r.role_principal,
            "roles_frequence": r.roles_frequence,
        }
        for r in rows
    ]


@router.get("/joueurs/{joueur_id}/carriere-stats")
async def get_joueur_carriere_stats(
    joueur_id: int,
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Synthèse globale sur l'ensemble de la carrière d'un joueur."""
    from pyvolley.database.repositories import JoueurCarriereStatsRepository

    repo = JoueurCarriereStatsRepository(match_repo.session)
    r = repo.get_for_joueur(joueur_id)
    if not r:
        raise HTTPException(status_code=404, detail="Statistiques carrière non trouvées")

    return {
        "joueur_id": r.joueur_id,
        "total_matchs": r.total_matchs,
        "total_victoires": r.total_victoires,
        "total_defaites": r.total_defaites,
        "total_sets": r.total_sets,
        "total_points_gagnes": r.total_points_gagnes,
        "total_points_joues": r.total_points_joues,
        "total_services": r.total_services,
        "total_series": r.total_series,
        "max_serie_carriere": r.max_serie_carriere,
        "max_points_match": r.max_points_match,
        "clubs_frequentes_count": r.clubs_frequentes_count,
        "saisons_count": r.saisons_count,
        "premier_match_date": r.premier_match_date.isoformat() if r.premier_match_date else None,
        "dernier_match_date": r.dernier_match_date.isoformat() if r.dernier_match_date else None,
    }

