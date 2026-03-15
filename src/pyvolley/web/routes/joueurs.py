"""
Routes web — Joueurs (liste et détail).
"""

import unicodedata
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import get_joueur_repo, get_equipe_repo, get_match_repo, get_session
from pyvolley.database.repositories import (
    JoueurRepository,
    EquipeRepository,
    MatchRepository,
)
from sqlalchemy.orm import Session
from pyvolley.analysis.joueur_stats import aggregate_joueur_stats
from pyvolley.analysis.models import JoueurMatchDetailedStats
from pyvolley.database.models import ParticipationMatchDB
from pyvolley.database.player_stats_service import JoueurMatchStatsService

router = APIRouter()


LEVEL_ORDER = {
    "LOISIR": 0,
    "DEPARTEMENTAL": 1,
    "DEPARTEMENTALE": 1,
    "PRE_REGIONALE": 2,
    "PREREGIONALE": 2,
    "REGIONAL": 3,
    "REGIONALE": 3,
    "PRE_NATIONAL": 4,
    "PRENATIONAL": 4,
    "PRENATIONALE": 4,
    "NATIONAL": 5,
    "NATIONALE": 5,
    "N3": 5,
    "N2": 6,
    "N1": 7,
    "ELITE": 8,
    "PRO_B": 9,
    "PRO": 9,
    "PRO_A": 10,
}


def _normalize_level(level: Optional[str]) -> Optional[str]:
    if not level:
        return None
    normalized = unicodedata.normalize("NFKD", level)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.upper().replace("-", "_").replace(" ", "_")


def _level_rank(level: Optional[str]) -> Optional[int]:
    key = _normalize_level(level)
    if not key:
        return None
    return LEVEL_ORDER.get(key)


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
    participations = list(
        session.scalars(
            select(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
        )
    )
    participation_by_match_id = {p.match_id: p for p in participations}

    numero_counts: dict[str, int] = {}
    for participation in participations:
        numero = (participation.numero_maillot or "").strip()
        if not numero:
            continue
        numero_counts[numero] = numero_counts.get(numero, 0) + 1

    numero_total = sum(numero_counts.values())
    sorted_numeros = sorted(
        numero_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )
    numero_stats = {
        "principal": sorted_numeros[0][0] if sorted_numeros else None,
        "distinct_count": len(sorted_numeros),
        "matches_with_number": numero_total,
        "distribution": [
            {
                "numero": numero,
                "count": count,
                "pct": round((count / numero_total) * 100, 1) if numero_total > 0 else 0,
            }
            for numero, count in sorted_numeros
        ],
    }

    stats_service = JoueurMatchStatsService(session)
    stats_rows = stats_service.repo.get_for_joueur(joueur_id, limit=500)

    aggregated_stats = None
    per_match_stats = []
    match_evolution_stats = []
    if stats_rows:
        detailed_models = [
            JoueurMatchDetailedStats.model_validate(row.stats_data)
            for row in stats_rows
        ]
        aggregated = aggregate_joueur_stats(detailed_models)
        if aggregated is not None:
            aggregated_stats = aggregated.model_dump(mode="json")

        matchs_by_id = {m.id: m for m in matchs}
        for row in stats_rows:
            match = matchs_by_id.get(row.match_id)
            side = row.stats_data.get("side")
            adversaire = "?"
            niveau_competition = match.competition.niveau if match and match.competition else None
            niveau_equipe = None
            niveau_adverse = None
            if match and match.equipe_a and match.equipe_b:
                if side == "A":
                    adversaire = match.equipe_b.nom
                    niveau_equipe = match.equipe_a.niveau
                    niveau_adverse = match.equipe_b.niveau
                elif side == "B":
                    adversaire = match.equipe_a.nom
                    niveau_equipe = match.equipe_b.niveau
                    niveau_adverse = match.equipe_a.niveau

            niveau_principal = niveau_competition or niveau_equipe or niveau_adverse
            numero_participation = None
            participation = participation_by_match_id.get(row.match_id)
            if participation and participation.numero_maillot:
                numero_participation = participation.numero_maillot.strip() or None
            numero_stats_data = (row.stats_data.get("numero") or "").strip() or None
            numero_display = numero_participation or numero_stats_data

            ratio_points_gagnes = row.stats_data.get("ratio_points_gagnes") or 0
            ratio_points_pct = round(float(ratio_points_gagnes) * 100, 1)

            per_match_stats.append(
                {
                    "match_id": row.match_id,
                    "date": match.date_match.isoformat() if match and match.date_match else None,
                    "adversaire": adversaire,
                    "numero": numero_display,
                    "niveau_competition": niveau_competition,
                    "niveau_equipe": niveau_equipe,
                    "niveau_adverse": niveau_adverse,
                    "niveau_principal": niveau_principal,
                    "niveau_rank": _level_rank(niveau_principal),
                    "ratio_points_pct": ratio_points_pct,
                    "stats": row.stats_data,
                }
            )

        per_match_stats.sort(
            key=lambda item: (item["date"] is None, item["date"] or "", item["match_id"]),
            reverse=True,
        )

        per_match_stats_chrono = list(reversed(per_match_stats))
        for index, item in enumerate(per_match_stats_chrono, start=1):
            pms = item["stats"]
            match_evolution_stats.append(
                {
                    "index": index,
                    "date": item["date"],
                    "adversaire": item["adversaire"],
                    "label": item["date"] or f"Match {index}",
                    "numero": item["numero"],
                    "niveau_principal": item["niveau_principal"],
                    "niveau_rank": item["niveau_rank"],
                    "victoire": bool(pms.get("victoire")),
                    "points_joues": int(pms.get("points_joues") or 0),
                    "points_gagnes": int(pms.get("points_gagnes") or 0),
                    "points_perdus": int(pms.get("points_perdus") or 0),
                    "points_gagnes_service": int(pms.get("points_gagnes_service") or 0),
                    "services": int(pms.get("services") or 0),
                    "max_serie": int(pms.get("max_serie") or 0),
                    "temps_jeu_estime": pms.get("temps_jeu_estime"),
                    "ratio_points_pct": item["ratio_points_pct"],
                }
            )

    return templates.TemplateResponse(
        "joueurs/detail.html",
        {
            "request": request,
            "joueur": joueur,
            "matchs": matchs,
            "stats": stats,
            "detailed_stats": detailed_stats,
            "numero_stats": numero_stats,
            "aggregated_stats": aggregated_stats,
            "per_match_stats": per_match_stats,
            "match_evolution_stats": match_evolution_stats,
        },
    )
