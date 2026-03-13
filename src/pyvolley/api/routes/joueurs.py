"""
Routes API — Joueurs.
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query

from pyvolley.api.dependencies import get_joueur_repo, get_match_repo
from pyvolley.api.schemas import JoueurResponse, JoueurDetail, MatchResponse
from pyvolley.api.converters import match_to_response
from pyvolley.database.repositories import JoueurRepository, MatchRepository

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
    from pyvolley.database.converters import match_db_to_core
    from pyvolley.analysis.joueur_stats import (
        analyze_joueur_match,
        aggregate_joueur_stats,
    )

    joueur = joueur_repo.get(joueur_id)
    if not joueur:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")

    matchs_db = match_repo.get_by_joueur(joueur_id, limit=500)
    all_stats = []

    for m_db in matchs_db:
        if not m_db.has_details:
            continue
        m_full = match_repo.get_with_details(m_db.id)
        if not m_full:
            continue

        participants_a = [
            p
            for p in (m_full.participations or [])
            if p.equipe_id == m_full.equipe_a_id
        ]
        participants_b = [
            p
            for p in (m_full.participations or [])
            if p.equipe_id == m_full.equipe_b_id
        ]
        match_core = match_db_to_core(m_full, participants_a, participants_b)

        s = analyze_joueur_match(match_core, joueur.licence)
        if s:
            all_stats.append(s)

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
    from pyvolley.database.converters import match_db_to_core
    from pyvolley.analysis.joueur_stats import analyze_joueur_match

    match_db = match_repo.get_with_details(match_id)
    if not match_db:
        raise HTTPException(status_code=404, detail="Match non trouvé")

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

    stats_a = []
    stats_b = []
    for p in participants_a:
        if p.joueur:
            s = analyze_joueur_match(match_core, p.joueur.licence)
            if s:
                stats_a.append(s.model_dump())
    for p in participants_b:
        if p.joueur:
            s = analyze_joueur_match(match_core, p.joueur.licence)
            if s:
                stats_b.append(s.model_dump())

    return {
        "match_id": match_id,
        "equipe_a": match_db.equipe_a.nom if match_db.equipe_a else "Équipe A",
        "equipe_b": match_db.equipe_b.nom if match_db.equipe_b else "Équipe B",
        "stats_a": stats_a,
        "stats_b": stats_b,
    }
