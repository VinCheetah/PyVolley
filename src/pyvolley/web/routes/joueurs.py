"""
Routes web — Joueurs (liste et détail).
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import get_joueur_repo, get_equipe_repo, get_match_repo, get_session
from pyvolley.database.repositories import (
    JoueurRepository,
    EquipeRepository,
    MatchRepository,
    JoueurStatsCacheRepository,
)
from sqlalchemy.orm import Session
from sqlalchemy import select, func

router = APIRouter()


@router.get("/joueurs", response_class=HTMLResponse)
async def joueurs_list(
    request: Request,
    q: Optional[str] = None,
    genre: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: JoueurRepository = Depends(get_joueur_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    limit = 50
    offset = (page - 1) * limit
    if q:
        joueurs = repo.search_by_name(q, genre=genre, limit=limit)
    else:
        joueurs = repo.get_all(limit=limit, offset=offset)
    total = repo.count()
    genres = equipe_repo.get_distinct_genres()
    return templates.TemplateResponse(
        "joueurs/list.html",
        {
            "request": request,
            "joueurs": joueurs,
            "query": q,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
            "genre": genre or "",
            "genres": genres,
        },
    )


def _compute_joueur_perf_stats(
    match_repo: MatchRepository,
    joueur_id: int,
    joueur_licence: str,
    matchs,
):
    """Calcule les statistiques de performance agrégées et par match pour un joueur."""
    from pyvolley.database.converters import match_db_to_core
    from pyvolley.analysis.joueur_stats import (
        analyze_joueur_match,
        aggregate_joueur_stats,
    )

    all_detailed = []
    per_match_stats = []
    for m in matchs:
        if not m.has_details:
            continue
        m_full = match_repo.get_with_details(m.id)
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
        s = analyze_joueur_match(match_core, joueur_licence)
        if s:
            all_detailed.append(s)
            per_match_stats.append(
                {
                    "match_id": m.id,
                    "date": m.date_match.isoformat() if m.date_match else None,
                    "adversaire": (
                        m.equipe_b.nom
                        if m.equipe_a_id
                        and any(
                            p.equipe_id == m.equipe_a_id
                            for p in (m_full.participations or [])
                            if p.joueur_id == joueur_id
                        )
                        else m.equipe_a.nom
                    )
                    if m.equipe_a and m.equipe_b
                    else "?",
                    "stats": s,
                }
            )

    aggregated_stats = aggregate_joueur_stats(all_detailed)
    return aggregated_stats, per_match_stats


@router.get("/joueurs/{joueur_id}", response_class=HTMLResponse)
async def joueur_detail(
    request: Request,
    joueur_id: int,
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
    session: Session = Depends(get_session),
):
    joueur = joueur_repo.get(joueur_id)
    if not joueur:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Joueur non trouvé"},
            status_code=404,
        )
    matchs = match_repo.get_by_joueur(joueur_id, limit=200)
    stats = joueur_repo.get_stats(joueur_id)
    detailed_stats = joueur_repo.get_detailed_stats(joueur_id)

    # Utiliser le cache des statistiques de performance
    from pyvolley.database.models import ParticipationMatchDB

    current_match_count = session.scalar(
        select(func.count())
        .select_from(ParticipationMatchDB)
        .where(ParticipationMatchDB.joueur_id == joueur_id)
    ) or 0

    cache_repo = JoueurStatsCacheRepository(session)
    aggregated_stats = None
    per_match_stats = []

    if not cache_repo.is_stale(joueur_id, current_match_count):
        cached = cache_repo.get_by_joueur(joueur_id)
        if cached:
            aggregated_stats = cached.aggregated_stats
            per_match_stats = cached.per_match_stats or []
    else:
        # Calcul et mise en cache
        aggregated_stats, per_match_stats = _compute_joueur_perf_stats(
            match_repo, joueur_id, joueur.licence, matchs,
        )
        cache_repo.upsert(joueur_id, aggregated_stats, per_match_stats, current_match_count)
        session.commit()

    return templates.TemplateResponse(
        "joueurs/detail.html",
        {
            "request": request,
            "joueur": joueur,
            "matchs": matchs,
            "stats": stats,
            "detailed_stats": detailed_stats,
            "aggregated_stats": aggregated_stats,
            "per_match_stats": per_match_stats,
        },
    )
