"""
Routes web — Clubs (liste et détail).
"""

from typing import Optional
import re

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import get_club_repo, get_equipe_repo
from pyvolley.database.repositories import ClubRepository, EquipeRepository
from pyvolley.web.helpers.niveau import resolve_niveau_badge
from pyvolley.web.helpers.club_branding import build_club_branding

router = APIRouter()


def _season_sort_key(value: str) -> tuple[int, int]:
    if not value:
        return (0, 0)
    match = re.match(r"^(\d{4})-(\d{4})$", value)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    single = re.match(r"^(\d{4})$", value)
    if single:
        year = int(single.group(1))
        return (year, year)
    return (0, 0)


def _level_score_from_label(level_label: str | None) -> float | None:
    if not level_label:
        return None
    normalized = level_label.strip().upper()
    mapping = {
        "CDF": 11.0,
        "PRO A": 10.0,
        "PRO B": 9.0,
        "PRO": 8.5,
        "ELITE": 8.0,
        "ELITE AVENIR": 7.5,
        "N1": 7.0,
        "N2": 6.0,
        "N3": 5.0,
        "NATIONAL": 4.8,
        "PRENAT": 4.0,
        "PRÉNAT": 4.0,
        "PREREG": 3.0,
        "PRÉREG": 3.0,
        "REGIONAL": 2.0,
        "RÉGIONAL": 2.0,
        "DEP": 1.0,
        "DÉP": 1.0,
        "LOISIR": 0.5,
    }
    return mapping.get(normalized)


def _build_level_evolution_chart(team_rows: list[dict]) -> dict:
    seasons = sorted({row["saison"] for row in team_rows if row["saison"]}, key=_season_sort_key)
    kinds = sorted({row["kind"] for row in team_rows if row["kind"]})

    datasets: list[dict] = []
    for kind in kinds:
        by_season: dict[str, tuple[float, str]] = {}
        for row in team_rows:
            if row["kind"] != kind or not row["saison"] or row["niveau_score"] is None:
                continue
            season = row["saison"]
            current = by_season.get(season)
            if current is None or row["niveau_score"] > current[0]:
                by_season[season] = (row["niveau_score"], row["niveau_label"])

        if not by_season:
            continue

        data: list[float | None] = []
        labels: list[str | None] = []
        for season in seasons:
            value = by_season.get(season)
            data.append(value[0] if value else None)
            labels.append(value[1] if value else None)

        datasets.append({"label": kind, "data": data, "level_labels": labels})

    return {"seasons": seasons, "datasets": datasets}


@router.get("/clubs", response_class=HTMLResponse)
async def clubs_list(
    request: Request,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: ClubRepository = Depends(get_club_repo),
):
    limit = 50
    offset = (page - 1) * limit
    clubs = (
        repo.search_by_name(q, limit=limit)
        if q
        else repo.get_all(limit=limit, offset=offset)
    )
    total = repo.count()
    return templates.TemplateResponse(
        "clubs/list.html",
        {
            "request": request,
            "clubs": clubs,
            "query": q,
            "page": page,
            "total": total,
            "has_next": offset + limit < total,
            "has_prev": page > 1,
        },
    )


@router.get("/clubs/{club_id}", response_class=HTMLResponse)
async def club_detail(
    request: Request,
    club_id: int,
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    club = club_repo.get_with_details(club_id)
    if not club:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Club non trouvé"},
            status_code=404,
        )
    equipes = equipe_repo.get_by_club(club_id)

    branding = build_club_branding(
        club.couleurs,
        club.url_planning,
        club.url_classement,
        club.code_ffvb,
    )

    team_rows: list[dict] = []
    for eq in equipes:
        saison_code = eq.saison.code if eq.saison and eq.saison.code else ""
        genre = (eq.genre or (eq.competition.genre if eq.competition else None) or "NC").strip()
        categorie = (
            eq.categorie or (eq.competition.categorie if eq.competition else None) or "Inconnue"
        ).strip()
        niveau_badge = resolve_niveau_badge(
            eq.niveau or (eq.competition.niveau if eq.competition else None),
            eq.competition.nom if eq.competition else eq.nom,
            categorie,
            eq.division or (eq.competition.division if eq.competition else None),
        )
        niveau_label = niveau_badge["label"] if niveau_badge else "Non classé"
        team_rows.append(
            {
                "id": eq.id,
                "nom": eq.nom,
                "saison": saison_code,
                "genre": genre,
                "categorie": categorie,
                "niveau_label": niveau_label,
                "niveau_css": niveau_badge["css_class"] if niveau_badge else "badge",
                "niveau_score": _level_score_from_label(niveau_label),
                "division": eq.division or (eq.competition.division if eq.competition else None),
                "competition": eq.competition.nom if eq.competition else "",
                "kind": f"{genre} · {categorie}",
            }
        )

    team_rows.sort(
        key=lambda row: (_season_sort_key(row["saison"]), row["nom"]),
        reverse=True,
    )
    team_filters = {
        "saisons": sorted({row["saison"] for row in team_rows if row["saison"]}, key=_season_sort_key, reverse=True),
        "genres": sorted({row["genre"] for row in team_rows if row["genre"]}),
        "categories": sorted({row["categorie"] for row in team_rows if row["categorie"]}),
        "niveaux": sorted({row["niveau_label"] for row in team_rows if row["niveau_label"]}),
    }
    level_chart = _build_level_evolution_chart(team_rows)

    return templates.TemplateResponse(
        "clubs/detail.html",
        {
            "request": request,
            "club": club,
            "equipes": equipes,
            "club_branding": branding,
            "team_rows": team_rows,
            "team_filters": team_filters,
            "level_chart": level_chart,
        },
    )
