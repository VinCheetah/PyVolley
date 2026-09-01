"""
Routes web — Équipes (liste et détail).
"""

from collections import defaultdict
import json
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from pyvolley.web.templateconfig import templates
from pyvolley.web.helpers.match_utils import build_match_score_evolution
from pyvolley.web.helpers.common import role_label, safe_float
from pyvolley.shared.helpers import is_winner, parse_optional_int
from pyvolley.api.dependencies import (
    get_equipe_repo,
    get_match_repo,
    get_saison_repo,
)
from pyvolley.database.repositories import (
    EquipeRepository,
    MatchRepository,
    SaisonRepository,
)
from pyvolley.database.models import JoueurMatchStatsDB
from pyvolley.scrapers.ffvb.utils import build_equipe_ffvb_url
from pyvolley.core.config import get_settings

router = APIRouter()


ROLE_SETTER = "PASSEUR"
ROLE_OPPOSITE = "POINTU"
ROLE_MIDDLE = "CENTRAL"
ROLE_OUTSIDE = "RECEPTIONNEUR_ATTAQUANT"
ROLE_LIBERO = "LIBERO"
ROLE_MULTI = "POLYVALENT"
ROLE_UNKNOWN = "INDETERMINE"

_ROLE_GROUP_ORDER = (
    ROLE_SETTER,
    ROLE_OPPOSITE,
    ROLE_MIDDLE,
    ROLE_OUTSIDE,
    ROLE_LIBERO,
    ROLE_MULTI,
    ROLE_UNKNOWN,
)


def _compute_player_role_profile(
    role_samples: list[dict],
    matchs_joues: int,
    libero_count: int,
) -> dict:
    role_counts: dict[str, int] = defaultdict(int)
    role_score_sum: dict[str, float] = defaultdict(float)
    role_score_hits: dict[str, int] = defaultdict(int)
    confidence_values: list[float] = []

    for sample in role_samples:
        role_principal = str(sample.get("role_principal") or "").strip().upper()
        if role_principal:
            role_counts[role_principal] += 1

        conf = safe_float(sample.get("role_confiance"))
        if conf > 0:
            confidence_values.append(conf)

        role_scores = sample.get("role_scores") or {}
        if isinstance(role_scores, dict):
            for role_name, score in role_scores.items():
                role_code = str(role_name or "").strip().upper()
                if not role_code:
                    continue
                value = safe_float(score)
                if value <= 0:
                    continue
                role_score_sum[role_code] += value
                role_score_hits[role_code] += 1

    sample_count = len(role_samples)
    role_codes = set(role_counts.keys()) | set(role_score_sum.keys())
    role_rows: list[dict] = []

    for role_code in role_codes:
        hit_count = role_score_hits.get(role_code, 0)
        avg_score = (role_score_sum.get(role_code, 0.0) / hit_count) if hit_count > 0 else 0.0
        match_count = int(role_counts.get(role_code, 0))
        match_share = (match_count / sample_count) if sample_count > 0 else 0.0
        role_rows.append(
            {
                "code": role_code,
                "label": role_label(role_code),
                "score": avg_score,
                "match_count": match_count,
                "match_share": match_share,
            }
        )

    role_rows.sort(
        key=lambda item: (
            -item["score"],
            -item["match_count"],
            item["code"],
        )
    )

    if not role_rows:
        if libero_count > 0:
            return {
                "group_code": ROLE_LIBERO,
                "group_label": role_label(ROLE_LIBERO),
                "primary_code": ROLE_LIBERO,
                "primary_label": role_label(ROLE_LIBERO),
                "plausible_labels": [role_label(ROLE_LIBERO)],
                "is_multi_role": False,
                "has_data": False,
                "confidence_pct": 35.0,
                "coverage_pct": 0.0,
                "sample_count": 0,
            }

        return {
            "group_code": ROLE_UNKNOWN,
            "group_label": role_label(ROLE_UNKNOWN),
            "primary_code": None,
            "primary_label": role_label(ROLE_UNKNOWN),
            "plausible_labels": [],
            "is_multi_role": False,
            "has_data": False,
            "confidence_pct": 0.0,
            "coverage_pct": 0.0,
            "sample_count": 0,
        }

    top_role = role_rows[0]
    top_score = float(top_role["score"])
    top_share = float(top_role["match_share"])
    min_plausible_score = max(0.18, top_score * 0.62)

    plausible_rows = [
        row for row in role_rows if row["score"] >= min_plausible_score or row["match_share"] >= 0.30
    ]
    if not plausible_rows:
        plausible_rows = [top_role]
    plausible_rows = plausible_rows[:3]

    is_multi_role = False
    if len(plausible_rows) >= 2:
        second_role = plausible_rows[1]
        second_score = float(second_role["score"])
        second_share = float(second_role["match_share"])

        if sample_count >= 4:
            is_multi_role = (top_score - second_score) <= 0.18 and second_share >= 0.22
        elif sample_count >= 2:
            is_multi_role = (top_score - second_score) <= 0.12 and second_share >= 0.30
        else:
            is_multi_role = (top_score - second_score) <= 0.08 and top_share <= 0.75

    group_code = ROLE_MULTI if is_multi_role else str(top_role["code"])

    avg_confidence = (
        sum(confidence_values) / len(confidence_values)
        if confidence_values
        else max(0.15, top_score * 0.75)
    )
    coverage_pct = (
        round((sample_count / matchs_joues) * 100, 1)
        if matchs_joues > 0
        else 0.0
    )

    return {
        "group_code": group_code,
        "group_label": role_label(group_code),
        "primary_code": str(top_role["code"]),
        "primary_label": str(top_role["label"]),
        "plausible_labels": [str(row["label"]) for row in plausible_rows],
        "is_multi_role": is_multi_role,
        "has_data": True,
        "confidence_pct": round(avg_confidence * 100, 1),
        "coverage_pct": coverage_pct,
        "sample_count": sample_count,
    }


def _build_roster_role_groups(
    roster: list[dict],
    role_samples_by_player: dict[int, list[dict]],
) -> tuple[list[dict], list[dict]]:
    enriched_roster: list[dict] = []
    grouped: dict[str, list[dict]] = defaultdict(list)

    for entry in roster:
        joueur = entry.get("joueur")
        if joueur is None:
            continue

        role_profile = _compute_player_role_profile(
            role_samples_by_player.get(joueur.id, []),
            int(entry.get("matchs_joues") or 0),
            int(entry.get("libero_count") or 0),
        )
        enriched = {**entry, "role_profile": role_profile}
        enriched_roster.append(enriched)
        grouped[role_profile["group_code"]].append(enriched)

    for players in grouped.values():
        players.sort(
            key=lambda item: (
                -int(item.get("matchs_joues") or 0),
                -float(item.get("role_profile", {}).get("confidence_pct") or 0.0),
                (item.get("joueur").nom or "") if item.get("joueur") else "",
                (item.get("joueur").prenom or "") if item.get("joueur") else "",
            )
        )

    groups: list[dict] = []
    for group_code in _ROLE_GROUP_ORDER:
        players = grouped.pop(group_code, [])
        if not players:
            continue
        groups.append(
            {
                "code": group_code,
                "label": role_label(group_code),
                "players": players,
                "count": len(players),
                "total_matches": sum(int(p.get("matchs_joues") or 0) for p in players),
                "coverage_avg_pct": round(
                    sum(float(p["role_profile"].get("coverage_pct") or 0.0) for p in players) / len(players),
                    1,
                ),
            }
        )

    for group_code in sorted(grouped.keys()):
        players = grouped[group_code]
        if not players:
            continue
        groups.append(
            {
                "code": group_code,
                "label": role_label(group_code),
                "players": players,
                "count": len(players),
                "total_matches": sum(int(p.get("matchs_joues") or 0) for p in players),
                "coverage_avg_pct": round(
                    sum(float(p["role_profile"].get("coverage_pct") or 0.0) for p in players) / len(players),
                    1,
                ),
            }
        )

    return enriched_roster, groups


@router.get("/equipes", response_class=HTMLResponse)
async def equipes_list(
    request: Request,
    q: Optional[str] = None,
    genre: Optional[str] = None,
    niveau: Optional[str] = None,
    categorie: Optional[str] = None,
    saison_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    repo: EquipeRepository = Depends(get_equipe_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
):
    saison_id_int = parse_optional_int(saison_id)

    limit = 50
    offset = (page - 1) * limit
    if q or genre or niveau or categorie or saison_id_int:
        equipes = repo.search_by_name(
            q or "%",
            genre=genre,
            niveau=niveau,
            categorie=categorie,
            saison_id=saison_id_int,
            limit=limit,
            offset=offset,
        )
        total = repo.count_search(
            q or "%",
            genre=genre,
            niveau=niveau,
            categorie=categorie,
            saison_id=saison_id_int,
        )
    else:
        equipes = repo.get_all(limit=limit, offset=offset)
        total = repo.count()
    saisons = saison_repo.get_all(limit=20)
    genres = repo.get_distinct_genres()
    niveaux = repo.get_distinct_niveaux()
    categories = repo.get_distinct_categories()
    return templates.TemplateResponse(
        "equipes/list.html",
        {
            "request": request,
            "equipes": equipes,
            "query": q,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
            "saisons": saisons,
            "current_saison_id": saison_id_int,
            "genre": genre or "",
            "genres": genres,
            "niveau": niveau or "",
            "niveaux": niveaux,
            "categorie": categorie or "",
            "categories": categories,
        },
    )


@router.get("/equipes/{equipe_id}", response_class=HTMLResponse)
async def equipe_detail(
    request: Request,
    equipe_id: int,
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    equipe = equipe_repo.get_with_details(equipe_id)
    if not equipe:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Équipe non trouvée"},
            status_code=404,
        )
    matchs = match_repo.get_by_equipe(equipe_id, limit=200)
    victoires = sum(1 for m in matchs if is_winner(m, equipe))
    roster = equipe_repo.get_roster(equipe_id)

    roster_player_ids = [entry["joueur"].id for entry in roster if entry.get("joueur")]
    role_samples_by_player: dict[int, list[dict]] = defaultdict(list)
    if roster_player_ids:
        role_rows = list(
            equipe_repo.session.scalars(
                select(JoueurMatchStatsDB)
                .where(
                    JoueurMatchStatsDB.equipe_id == equipe_id,
                    JoueurMatchStatsDB.joueur_id.in_(roster_player_ids),
                )
                .order_by(
                    JoueurMatchStatsDB.joueur_id,
                    JoueurMatchStatsDB.match_updated_at.desc(),
                    JoueurMatchStatsDB.computed_at.desc(),
                )
            )
        )
        for role_row in role_rows:
            if isinstance(role_row.stats_data, dict):
                role_samples_by_player[role_row.joueur_id].append(role_row.stats_data)

    roster, roster_role_groups = _build_roster_role_groups(roster, role_samples_by_player)
    players_with_role_data = sum(
        1 for entry in roster if bool(entry.get("role_profile", {}).get("has_data"))
    )
    role_detection_coverage = {
        "players_with_role_data": players_with_role_data,
        "players_total": len(roster),
        "pct": round((players_with_role_data / len(roster)) * 100, 1) if roster else 0.0,
    }

    # Sets stats
    sets_gagnes = 0
    sets_perdus = 0
    for m in matchs:
        if m.equipe_a_id == equipe.id:
            sets_gagnes += m.sets_equipe_a
            sets_perdus += m.sets_equipe_b
        else:
            sets_gagnes += m.sets_equipe_b
            sets_perdus += m.sets_equipe_a

    score_evolution = build_match_score_evolution(matchs, equipe)

    # URL FFVB pour l'équipe
    url_ffvb = None
    if (
        equipe.club
        and equipe.club.code_ffvb
        and equipe.competition
        and equipe.competition.entite
        and equipe.saison
    ):
        settings = get_settings()
        saison_ffvb = equipe.saison.code.replace("-", "/")
        url_ffvb = build_equipe_ffvb_url(
            base_url=settings.ffvb_base_url,
            entity_code=equipe.competition.entite.code,
            saison=saison_ffvb,
            club_code_ffvb=equipe.club.code_ffvb,
        )

    return templates.TemplateResponse(
        "equipes/detail.html",
        {
            "request": request,
            "equipe": equipe,
            "matchs": matchs,
            "victoires": victoires,
            "defaites": len([m for m in matchs if m.match_joue]) - victoires,
            "roster": roster,
            "roster_role_groups": roster_role_groups,
            "role_detection_coverage": role_detection_coverage,
            "sets_gagnes": sets_gagnes,
            "sets_perdus": sets_perdus,
            "score_evolution_json": json.dumps(
                score_evolution, ensure_ascii=False, default=str
            ),
            "url_ffvb": url_ffvb,
        },
    )
