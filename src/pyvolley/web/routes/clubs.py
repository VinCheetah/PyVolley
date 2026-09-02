"""
Routes web — Clubs (liste et détail).
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.api.dependencies import get_club_repo, get_equipe_repo
from pyvolley.database.repositories import ClubRepository, EquipeRepository
from pyvolley.web.helpers.niveau import resolve_niveau_badge
from pyvolley.web.helpers.club_branding import build_club_branding
from pyvolley.web.helpers.common import season_sort_key
from pyvolley.core.config import settings
from pyvolley.scrapers.ffvb.adressier_scraper import (
    build_adressier_url,
    build_club_classement_url,
    build_club_planning_url,
)

router = APIRouter()


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


def _to_ffvb_season(saison_code: str | None) -> str | None:
    if not saison_code:
        return None
    return saison_code.replace("-", "/")


def _build_ffvb_links(club, equipes: list) -> dict[str, str | None]:
    if not club.code_ffvb:
        return {"planning": None, "classement": None, "adressier": None}

    entite_code = None
    season_codes: list[str] = []

    for equipe in equipes:
        if equipe.saison and equipe.saison.code:
            season_codes.append(equipe.saison.code)
        if (
            not entite_code
            and equipe.competition
            and equipe.competition.entite
            and equipe.competition.entite.code
        ):
            entite_code = equipe.competition.entite.code

    latest_season = max(season_codes, key=season_sort_key) if season_codes else None
    ffvb_saison = _to_ffvb_season(latest_season)

    planning_url = None
    classement_url = None
    adressier_url = None

    if entite_code:
        planning_url = build_club_planning_url(settings.ffvb_base_url, entite_code, club.code_ffvb)
        adressier_url = build_adressier_url(settings.ffvb_base_url)
        if ffvb_saison:
            classement_url = build_club_classement_url(
                settings.ffvb_base_url,
                entite_code,
                ffvb_saison,
                club.code_ffvb,
            )

    return {
        "planning": planning_url,
        "classement": classement_url,
        "adressier": adressier_url,
    }


def _build_level_evolution_chart(team_rows: list[dict]) -> dict:
    seasons = sorted({row["saison"] for row in team_rows if row["saison"]}, key=season_sort_key)
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
    if q:
        clubs = repo.search_by_name(q, limit=limit, offset=offset)
        total = repo.count_search(q)
    else:
        clubs = repo.get_all(limit=limit, offset=offset)
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

    ffvb_links = _build_ffvb_links(club, equipes)

    branding = build_club_branding(
        club.couleurs,
        club.logo_url,
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
                "kind": f"{genre} Â· {categorie}",
            }
        )

    team_rows.sort(
        key=lambda row: (season_sort_key(row["saison"]), row["nom"]),
        reverse=True,
    )
    team_filters = {
        "saisons": sorted({row["saison"] for row in team_rows if row["saison"]}, key=season_sort_key, reverse=True),
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
            "ffvb_links": ffvb_links,
            "team_rows": team_rows,
            "team_filters": team_filters,
            "level_chart": level_chart,
        },
    )
