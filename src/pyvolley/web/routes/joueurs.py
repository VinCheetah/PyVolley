"""
Routes web â€” Joueurs (liste et dÃ©tail).
"""

import unicodedata
import re
from datetime import date as dt_date
from collections import defaultdict
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
from pyvolley.web.helpers.niveau import (
    resolve_niveau_badge,
    niveau_sort_key,
    niveau_reference_labels,
)
from pyvolley.web.helpers.club_branding import parse_club_colors
from pyvolley.web.helpers.common import season_sort_key, season_end_year, role_label

router = APIRouter()

YOUTH_CATEGORY_RE = re.compile(r"\b(?:M|U)\s*(1[0-9]|20|21)\b", re.IGNORECASE)


def _normalize_level(level: Optional[str]) -> Optional[str]:
    if not level:
        return None
    normalized = unicodedata.normalize("NFKD", level)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.upper().replace("-", "_").replace(" ", "_")


def _level_rank(level: Optional[str]) -> Optional[int]:
    if not level:
        return None
    rank, _ = niveau_sort_key(level)
    return rank if rank >= 0 else None


def _resolve_match_level_label(match, equipe_joueur, adversaire) -> Optional[str]:
    competition = match.competition

    candidates = []
    if competition:
        candidates.append(
            (
                competition.niveau,
                competition.nom,
                competition.categorie,
                competition.division,
            )
        )

    if equipe_joueur:
        candidates.append(
            (
                equipe_joueur.niveau,
                equipe_joueur.nom,
                equipe_joueur.categorie,
                equipe_joueur.division,
            )
        )

    if adversaire:
        candidates.append(
            (
                adversaire.niveau,
                adversaire.nom,
                adversaire.categorie,
                adversaire.division,
            )
        )

    for niveau, nom, categorie, division in candidates:
        badge = resolve_niveau_badge(niveau, nom, categorie, division)
        if badge and badge.get("label"):
            return badge["label"]
        if niveau:
            return niveau
    return None


def _parse_date(value: Optional[str]) -> Optional[dt_date]:
    if not value:
        return None
    try:
        return dt_date.fromisoformat(value)
    except ValueError:
        return None


def _season_end_year_from_row(row: dict) -> Optional[int]:
    saison = row.get("saison")
    season_code = getattr(saison, "code", None) if saison else None
    end_year = season_end_year(season_code)
    if end_year is not None:
        return end_year

    match = row.get("match")
    match_date = getattr(match, "date_match", None)
    if match_date is None:
        return None

    # Saison sportive: les matchs d'aoÃ»t Ã  dÃ©cembre se terminent l'annÃ©e suivante.
    return match_date.year + 1 if match_date.month >= 8 else match_date.year





def _extract_youth_ages_from_text(value: Optional[str]) -> list[int]:
    if not value:
        return []

    found: list[int] = []
    for match in YOUTH_CATEGORY_RE.finditer(value):
        try:
            age_limit = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if age_limit < 11 or age_limit > 21:
            continue
        if age_limit not in found:
            found.append(age_limit)

    return found


def _compute_full_years_since(birth_date: dt_date, reference_date: dt_date) -> int:
    years = reference_date.year - birth_date.year
    if (reference_date.month, reference_date.day) < (birth_date.month, birth_date.day):
        years -= 1
    return max(0, years)


def _estimate_player_max_age(profile_rows: list[dict], reference_date: Optional[dt_date] = None) -> Optional[dict]:
    if not profile_rows:
        return None

    ref_date = reference_date or dt_date.today()
    candidates: list[dict] = []

    for row in profile_rows:
        season_end_year = _season_end_year_from_row(row)
        if season_end_year is None:
            continue

        match = row.get("match")
        competition = row.get("competition")
        equipe_joueur = row.get("equipe_joueur")
        saison = row.get("saison")

        text_sources = [
            getattr(competition, "categorie", None) if competition else None,
            getattr(competition, "nom", None) if competition else None,
            getattr(competition, "niveau", None) if competition else None,
            getattr(equipe_joueur, "categorie", None) if equipe_joueur else None,
            getattr(equipe_joueur, "nom", None) if equipe_joueur else None,
            getattr(equipe_joueur, "niveau", None) if equipe_joueur else None,
            row.get("niveau"),
        ]

        ages_found: set[int] = set()
        for text in text_sources:
            for age_limit in _extract_youth_ages_from_text(text):
                ages_found.add(age_limit)

        if not ages_found:
            continue

        season_code = getattr(saison, "code", None) if saison else None
        for age_limit in sorted(ages_found):
            birth_date_min = dt_date(season_end_year - age_limit, 1, 1)
            candidates.append(
                {
                    "match_id": getattr(match, "id", None),
                    "season_code": season_code,
                    "season_end_year": season_end_year,
                    "age_limit": age_limit,
                    "birth_date_min": birth_date_min,
                }
            )

    if not candidates:
        return None

    strongest = max(candidates, key=lambda item: item["birth_date_min"])
    strongest_birth_date = strongest["birth_date_min"]
    strongest_candidates = [
        item
        for item in candidates
        if item["birth_date_min"] == strongest_birth_date
    ]

    all_categories = sorted({f"M{item['age_limit']}" for item in candidates}, key=lambda label: int(label[1:]))
    best_categories = sorted(
        {f"M{item['age_limit']}" for item in strongest_candidates},
        key=lambda label: int(label[1:]),
    )
    best_seasons = sorted(
        {
            str(item["season_code"])
            for item in strongest_candidates
            if item.get("season_code")
        },
        key=season_sort_key,
        reverse=True,
    )

    return {
        "max_age_years": _compute_full_years_since(strongest_birth_date, ref_date),
        "birth_date_min": strongest_birth_date.isoformat(),
        "birth_date_min_display": strongest_birth_date.strftime("%d/%m/%Y"),
        "reference_date": ref_date.isoformat(),
        "all_category_labels": all_categories,
        "best_category_labels": best_categories,
        "best_season_labels": best_seasons,
        "source_match_count": len(
            {
                item["match_id"]
                for item in candidates
                if item.get("match_id") is not None
            }
        ),
    }


TEAM_NAME_STOPWORDS = {
    "LE", "LA", "LES", "DE", "DES", "DU", "D", "L", "ET",
    "VOLLEY", "BALL", "VOLLEYBALL", "VB", "CFC", "ASS", "ASSO", "ASSOCIATION",
}


def _normalize_team_name(value: Optional[str]) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.upper()
    cleaned = []
    for ch in normalized:
        cleaned.append(ch if ch.isalnum() else " ")
    return " ".join("".join(cleaned).split())


def _team_tokens(value: Optional[str]) -> set[str]:
    normalized = _normalize_team_name(value)
    if not normalized:
        return set()
    return {
        token
        for token in normalized.split()
        if len(token) > 1 and not token.isdigit() and token not in TEAM_NAME_STOPWORDS
    }


def _infer_side_from_participation(match, participation) -> Optional[str]:
    if not participation:
        return None

    if match.equipe_a_id == participation.equipe_id:
        return "A"
    if match.equipe_b_id == participation.equipe_id:
        return "B"

    participation_equipe = participation.equipe
    if not participation_equipe:
        return None

    part_club_id = participation_equipe.club_id
    if part_club_id and match.equipe_a and match.equipe_a.club_id == part_club_id:
        return "A"
    if part_club_id and match.equipe_b and match.equipe_b.club_id == part_club_id:
        return "B"

    part_name = participation_equipe.nom
    a_name = match.equipe_a.nom if match.equipe_a else None
    b_name = match.equipe_b.nom if match.equipe_b else None

    part_norm = _normalize_team_name(part_name).replace(" ", "")
    a_norm = _normalize_team_name(a_name).replace(" ", "")
    b_norm = _normalize_team_name(b_name).replace(" ", "")

    if part_norm and a_norm and (part_norm in a_norm or a_norm in part_norm):
        return "A"
    if part_norm and b_norm and (part_norm in b_norm or b_norm in part_norm):
        return "B"

    part_tokens = _team_tokens(part_name)
    a_tokens = _team_tokens(a_name)
    b_tokens = _team_tokens(b_name)

    if not part_tokens:
        return None

    score_a = len(part_tokens & a_tokens) / len(part_tokens) if a_tokens else 0.0
    score_b = len(part_tokens & b_tokens) / len(part_tokens) if b_tokens else 0.0

    if score_a > score_b and score_a >= 0.5:
        return "A"
    if score_b > score_a and score_b >= 0.5:
        return "B"

    return None





def _role_hint_source(hint: str) -> str:
    text = (hint or "").strip().lower()
    if not text:
        return "Indices divers"
    if "passe-pointe" in text:
        return "Inversion passe-pointe"
    if "libero" in text:
        return "Remplacements libero"
    if (
        "rotation" in text
        or "formation" in text
        or "opposition au passeur" in text
        or "pointu" in text
        or "serveur de depart" in text
    ):
        return "Ordre rotation / formation"
    if "remplacement" in text or "coherence" in text or "sortie" in text:
        return "Patterns de changements"
    return "Indices divers"


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
        joueurs = repo.search_by_name(q, genre=genre, limit=limit, offset=offset)
        total = repo.count_search(q, genre=genre)
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
    tab: Optional[str] = Query("resume"),
    saison_id: Optional[int] = Query(None),
    saison_ids: Optional[list[int]] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    equipe_ids: Optional[list[int]] = Query(None),
    club_ids: Optional[list[int]] = Query(None),
    competition_ids: Optional[list[int]] = Query(None),
    niveaux: Optional[list[str]] = Query(None),
    resultat: Optional[str] = Query(None),
    domicile_exterieur: Optional[str] = Query(None),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
    session: Session = Depends(get_session),
):
    joueur = joueur_repo.get(joueur_id)
    if not joueur:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Joueur non trouvÃ©"},
            status_code=404,
        )

    matchs_all = match_repo.get_by_joueur(joueur_id, limit=1200)
    participations = list(
        session.scalars(
            select(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
        )
    )
    participation_by_match_id = {p.match_id: p for p in participations}

    default_rows = []
    for match in matchs_all:
        participation = participation_by_match_id.get(match.id)
        if not participation:
            continue

        side = _infer_side_from_participation(match, participation)
        equipe_joueur = None
        adversaire = None
        if side == "A":
            side = "A"
            equipe_joueur = match.equipe_a
            adversaire = match.equipe_b
        elif side == "B":
            side = "B"
            equipe_joueur = match.equipe_b
            adversaire = match.equipe_a
        else:
            equipe_joueur = participation.equipe

        niveau_principal = _resolve_match_level_label(match, equipe_joueur, adversaire)

        victoire = None
        if match.match_joue and side in {"A", "B"}:
            victoire = (
                (side == "A" and (match.sets_equipe_a or 0) > (match.sets_equipe_b or 0))
                or (side == "B" and (match.sets_equipe_b or 0) > (match.sets_equipe_a or 0))
            )

        default_rows.append(
            {
                "match": match,
                "participation": participation,
                "side": side,
                "equipe_joueur": equipe_joueur,
                "adversaire": adversaire,
                "club": equipe_joueur.club if equipe_joueur else None,
                "saison": match.saison,
                "competition": match.competition,
                "niveau": niveau_principal,
                "victoire": victoire,
            }
        )

    rows_played = [row for row in default_rows if row["match"].match_joue]
    base_rows = rows_played if rows_played else default_rows

    selected_saison_ids = set(saison_ids or ([] if saison_id is None else [saison_id]))
    selected_equipe_ids = set(equipe_ids or [])
    selected_club_ids = set(club_ids or [])
    selected_competition_ids = set(competition_ids or [])
    selected_niveaux = set(niveaux or [])
    date_from_obj = _parse_date(date_from)
    date_to_obj = _parse_date(date_to)

    filtered_rows = []
    for row in base_rows:
        match = row["match"]
        equipe_joueur = row["equipe_joueur"]
        club = row["club"]
        competition = row["competition"]
        niveau = row["niveau"]
        if selected_saison_ids and match.saison_id not in selected_saison_ids:
            continue
        if date_from_obj and (not match.date_match or match.date_match < date_from_obj):
            continue
        if date_to_obj and (not match.date_match or match.date_match > date_to_obj):
            continue
        if selected_equipe_ids and (not equipe_joueur or equipe_joueur.id not in selected_equipe_ids):
            continue
        if selected_club_ids and (not club or club.id not in selected_club_ids):
            continue
        if selected_competition_ids and (not competition or competition.id not in selected_competition_ids):
            continue
        if selected_niveaux and (not niveau or niveau not in selected_niveaux):
            continue
        if resultat == "victoire" and not row["victoire"]:
            continue
        if resultat == "defaite" and row["victoire"] is not False:
            continue
        if domicile_exterieur == "domicile" and row["side"] != "A":
            continue
        if domicile_exterieur == "exterieur" and row["side"] != "B":
            continue
        filtered_rows.append(row)

    matchs = [row["match"] for row in filtered_rows][:400]
    filtered_rows = filtered_rows[:400]
    filtered_match_ids = {m.id for m in matchs}

    seasons_map: dict[int, str] = {}
    equipes_map: dict[int, str] = {}
    clubs_map: dict[int, str] = {}
    competitions_map: dict[int, str] = {}
    niveaux_set: set[str] = set()
    for row in base_rows:
        match = row["match"]
        equipe_joueur = row["equipe_joueur"]
        club = row["club"]
        competition = row["competition"]
        niveau = row["niveau"]
        if match.saison_id and row["saison"]:
            seasons_map[match.saison_id] = row["saison"].code
        if equipe_joueur:
            equipes_map[equipe_joueur.id] = equipe_joueur.nom
        if club:
            clubs_map[club.id] = club.nom
        if competition:
            competitions_map[competition.id] = competition.nom
        if niveau:
            niveaux_set.add(niveau)

    filter_options = {
        "saisons": [
            {"id": sid, "label": label}
            for sid, label in sorted(seasons_map.items(), key=lambda item: item[1], reverse=True)
        ],
        "equipes": [
            {"id": eid, "label": label}
            for eid, label in sorted(equipes_map.items(), key=lambda item: item[1])
        ],
        "clubs": [
            {"id": cid, "label": label}
            for cid, label in sorted(clubs_map.items(), key=lambda item: item[1])
        ],
        "competitions": [
            {"id": cid, "label": label}
            for cid, label in sorted(competitions_map.items(), key=lambda item: item[1])
        ],
        "niveaux": sorted(niveaux_set, key=niveau_sort_key, reverse=True),
    }

    hide_filters = {
        "clubs": len(filter_options["clubs"]) <= 1,
        "equipes": len(filter_options["equipes"]) <= 1,
        "competitions": len(filter_options["competitions"]) <= 1,
        "niveaux": len(filter_options["niveaux"]) <= 1,
        "saisons": len(filter_options["saisons"]) <= 1,
    }

    stats_rows_filtered = [row for row in filtered_rows if row["match"].match_joue]
    victoires = sum(1 for row in stats_rows_filtered if row["victoire"] is True)
    defaites = sum(1 for row in stats_rows_filtered if row["victoire"] is False)
    sets_gagnes = 0
    sets_perdus = 0
    for row in stats_rows_filtered:
        match = row["match"]
        if row["side"] == "A":
            sets_gagnes += match.sets_equipe_a or 0
            sets_perdus += match.sets_equipe_b or 0
        elif row["side"] == "B":
            sets_gagnes += match.sets_equipe_b or 0
            sets_perdus += match.sets_equipe_a or 0

    stats = {
        "matchs_joues": len(stats_rows_filtered),
        "victoires": victoires,
        "defaites": defaites,
        "sets_gagnes": sets_gagnes,
        "sets_perdus": sets_perdus,
        "equipes_count": len({row["equipe_joueur"].id for row in filtered_rows if row["equipe_joueur"]}),
        "clubs_count": len({row["club"].id for row in filtered_rows if row["club"]}),
    }
    total_vd = victoires + defaites
    stats["taux_victoire"] = round((victoires / total_vd) * 100, 1) if total_vd > 0 else None

    profile_rows = rows_played if rows_played else base_rows
    estimated_age = _estimate_player_max_age(profile_rows)

    season_candidates: dict[int, tuple[tuple[int, int, str], dt_date, str]] = {}
    for row in profile_rows:
        saison = row["saison"]
        match = row["match"]
        if not saison or not match.saison_id:
            continue
        code = saison.code
        candidate = (
            season_sort_key(code),
            match.date_match or dt_date.min,
            code,
        )
        existing = season_candidates.get(match.saison_id)
        if not existing or candidate > existing:
            season_candidates[match.saison_id] = candidate

    current_saison_id = None
    current_saison_label = None
    if season_candidates:
        current_saison_id, current_saison_data = max(season_candidates.items(), key=lambda item: item[1])
        current_saison_label = current_saison_data[2]

    def _best_level_info(rows: list[dict]) -> Optional[dict]:
        level_buckets: dict[str, dict[str, int | Optional[int]]] = {}
        for row in rows:
            level = row["niveau"]
            if not level:
                continue
            bucket = level_buckets.setdefault(
                level,
                {
                    "count": 0,
                    "wins": 0,
                    "losses": 0,
                    "rank": _level_rank(level),
                },
            )
            bucket["count"] = int(bucket["count"]) + 1
            if row["victoire"] is True:
                bucket["wins"] = int(bucket["wins"]) + 1
            elif row["victoire"] is False:
                bucket["losses"] = int(bucket["losses"]) + 1

        if not level_buckets:
            return None

        best_level, best_data = max(
            level_buckets.items(),
            key=lambda item: (
                item[1]["rank"] if item[1]["rank"] is not None else -1,
                item[1]["count"],
                item[0],
            ),
        )
        return {
            "label": best_level,
            "rank": best_data["rank"],
            "match_count": best_data["count"],
            "wins": best_data["wins"],
            "losses": best_data["losses"],
        }

    current_season_rows = [
        row for row in profile_rows
        if current_saison_id is not None and row["match"].saison_id == current_saison_id
    ]
    previous_seasons_rows = [
        row for row in profile_rows
        if current_saison_id is None or row["match"].saison_id != current_saison_id
    ]

    best_level_current = _best_level_info(current_season_rows)
    best_level_previous = _best_level_info(previous_seasons_rows)
    if (
        best_level_current
        and best_level_previous
        and best_level_current["label"] == best_level_previous["label"]
    ):
        best_level_previous = None

    def _safe_date(value: Optional[dt_date]) -> dt_date:
        return value or dt_date.min

    latest_profile_row = None
    if profile_rows:
        latest_profile_row = max(
            profile_rows,
            key=lambda row: (
                _safe_date(row["match"].date_match),
                row["match"].id,
            ),
        )

    club_history: dict[int, dict] = {}
    for row in profile_rows:
        club = row["club"]
        if not club:
            continue
        match = row["match"]
        bucket = club_history.setdefault(
            club.id,
            {
                "id": club.id,
                "nom": club.nom,
                "match_count": 0,
                "first_date": None,
                "last_date": None,
                "saisons": set(),
            },
        )
        bucket["match_count"] += 1
        if match.date_match and (bucket["first_date"] is None or match.date_match < bucket["first_date"]):
            bucket["first_date"] = match.date_match
        if match.date_match and (bucket["last_date"] is None or match.date_match > bucket["last_date"]):
            bucket["last_date"] = match.date_match
        if row["saison"] and row["saison"].code:
            bucket["saisons"].add(row["saison"].code)

    current_club_id = None
    if latest_profile_row and latest_profile_row["club"]:
        current_club_id = latest_profile_row["club"].id

    current_club = club_history.get(current_club_id) if current_club_id else None
    former_clubs = sorted(
        [club for cid, club in club_history.items() if cid != current_club_id],
        key=lambda item: (
            item["last_date"] or dt_date.min,
            item["match_count"],
            item["nom"],
        ),
        reverse=True,
    )

    for club_data in [current_club] + former_clubs:
        if not club_data:
            continue
        club_data["saisons"] = sorted(club_data["saisons"], key=season_sort_key, reverse=True)

    level_distribution_counts: dict[str, dict[str, int | Optional[int]]] = {}
    for row in stats_rows_filtered:
        level = row["niveau"] or "Niveau inconnu"
        bucket = level_distribution_counts.setdefault(
            level,
            {
                "count": 0,
                "wins": 0,
                "losses": 0,
                "rank": _level_rank(level),
            },
        )
        bucket["count"] = int(bucket["count"]) + 1
        if row["victoire"] is True:
            bucket["wins"] = int(bucket["wins"]) + 1
        elif row["victoire"] is False:
            bucket["losses"] = int(bucket["losses"]) + 1

    level_distribution_total = sum(int(bucket["count"]) for bucket in level_distribution_counts.values())
    level_distribution = []
    for label, bucket in sorted(
        level_distribution_counts.items(),
        key=lambda item: (
            item[1]["rank"] if item[1]["rank"] is not None else -1,
            item[1]["count"],
            item[0],
        ),
        reverse=True,
    ):
        count = int(bucket["count"])
        level_distribution.append(
            {
                "label": label,
                "count": count,
                "wins": int(bucket["wins"]),
                "losses": int(bucket["losses"]),
                "rank": bucket["rank"],
                "pct": round((count / level_distribution_total) * 100, 1) if level_distribution_total else 0.0,
            }
        )

    player_profile = {
        "current_saison_id": current_saison_id,
        "current_saison_label": current_saison_label,
        "best_level_current": best_level_current,
        "best_level_previous": best_level_previous,
        "current_club": current_club,
        "former_clubs": former_clubs,
        "level_distribution": level_distribution,
        "level_distribution_total": level_distribution_total,
    }

    level_timeline = []
    for index, row in enumerate(
        sorted(
            stats_rows_filtered,
            key=lambda item: (
                _safe_date(item["match"].date_match),
                item["match"].id,
            ),
        ),
        start=1,
    ):
        match = row["match"]
        level_label = row["niveau"] or "Niveau inconnu"
        level_timeline.append(
            {
                "index": index,
                "match_id": match.id,
                "date": match.date_match.isoformat() if match.date_match else None,
                "niveau": level_label,
                "level_rank": _level_rank(level_label),
                "victoire": row["victoire"],
                "adversaire": row["adversaire"].nom if row["adversaire"] else None,
                "domicile_exterieur": (
                    "domicile"
                    if row["side"] == "A"
                    else ("exterieur" if row["side"] == "B" else "inconnu")
                ),
            }
        )

    level_rank_labels = niveau_reference_labels()
    level_reference_order_text = " < ".join(
        str(item["label"])
        for item in level_rank_labels
    )

    known_level_points = [point for point in level_timeline if point["level_rank"] is not None]
    level_timeline_summary = {
        "total_count": len(level_timeline),
        "known_count": len(known_level_points),
        "coverage_pct": round((len(known_level_points) / len(level_timeline)) * 100, 1)
        if level_timeline
        else 0.0,
        "current_label": None,
        "peak_label": None,
    }
    if known_level_points:
        peak_point = max(
            known_level_points,
            key=lambda point: (point["level_rank"], point["index"]),
        )
        current_point = known_level_points[-1]
        level_timeline_summary.update(
            {
                "current_label": current_point["niveau"],
                "peak_label": peak_point["niveau"],
            }
        )

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

    jersey_counts: dict[tuple[str, Optional[int], str], int] = {}
    jersey_meta: dict[tuple[str, Optional[int], str], dict] = {}

    def _club_from_participation(participation):
        equipe = participation.equipe
        if equipe and equipe.club:
            return equipe.club
        if latest_profile_row and latest_profile_row["club"]:
            return latest_profile_row["club"]
        return None

    for participation in participations:
        numero = (participation.numero_maillot or "").strip()
        if not numero:
            continue
        club = _club_from_participation(participation)
        club_id = club.id if club else None
        club_nom = club.nom if club else "Club inconnu"
        key = (numero, club_id, club_nom)
        jersey_counts[key] = jersey_counts.get(key, 0) + 1
        if key not in jersey_meta:
            palette = parse_club_colors(club.couleurs if club else None)
            jersey_meta[key] = {
                "numero": numero,
                "club_id": club_id,
                "club_nom": club_nom,
                "primary": palette["primary"],
                "secondary": palette["secondary"],
                "text_on_primary": palette["text_on_primary"],
            }

    jersey_total = sum(jersey_counts.values())
    jersey_cards = []
    joueur_nom_complet = f"{(joueur.prenom or '').strip()} {(joueur.nom or '').strip()}".strip()
    for key, count in sorted(
        jersey_counts.items(),
        key=lambda item: (
            item[0][1] == current_club_id,
            item[1],
            item[0][0],
        ),
        reverse=True,
    ):
        meta = jersey_meta[key]
        pct = round((count / jersey_total) * 100, 1) if jersey_total else 0.0
        jersey_scale = 0.98 + min(0.26, (pct / 100) * 0.38)
        jersey_cards.append(
            {
                **meta,
                "nom": joueur_nom_complet,
                "count": count,
                "pct": pct,
                "scale": round(jersey_scale, 2),
                "is_current_club": meta["club_id"] == current_club_id,
            }
        )

    if not jersey_cards:
        fallback_club = latest_profile_row["club"] if latest_profile_row and latest_profile_row["club"] else None
        fallback_palette = parse_club_colors(fallback_club.couleurs if fallback_club else None)
        jersey_cards.append(
            {
                "numero": "?",
                "club_id": fallback_club.id if fallback_club else None,
                "club_nom": fallback_club.nom if fallback_club else "Club non identifiÃ©",
                "primary": fallback_palette["primary"],
                "secondary": fallback_palette["secondary"],
                "text_on_primary": fallback_palette["text_on_primary"],
                "nom": joueur_nom_complet or "Joueur",
                "count": 0,
                "pct": 0.0,
                "scale": 1.0,
                "is_current_club": bool(fallback_club),
                "is_placeholder": True,
            }
        )

    top_numero = numero_stats["distribution"][0] if numero_stats["distribution"] else None
    principal_pct = float(top_numero["pct"]) if top_numero else 0.0
    if principal_pct >= 70:
        consistency_label = "Tres stable"
    elif principal_pct >= 55:
        consistency_label = "Stable"
    elif principal_pct >= 35:
        consistency_label = "Alternance moderee"
    else:
        consistency_label = "Tres variable"

    current_club_jersey_count = sum(
        int(card.get("count", 0))
        for card in jersey_cards
        if card.get("is_current_club")
    )
    current_club_jersey_pct = (
        round((current_club_jersey_count / jersey_total) * 100, 1)
        if jersey_total
        else 0.0
    )
    jersey_profile = {
        "principal_numero": numero_stats["principal"],
        "principal_pct": principal_pct,
        "consistency_label": consistency_label,
        "distinct_numeros": numero_stats["distinct_count"],
        "matches_with_number": numero_stats["matches_with_number"],
        "variants_count": len(jersey_cards),
        "current_club_pct": current_club_jersey_pct,
        "has_placeholder": any(card.get("is_placeholder") for card in jersey_cards),
    }

    stats_service = JoueurMatchStatsService(session)
    stats_rows = stats_service.repo.get_for_joueur(joueur_id, limit=1200)

    aggregated_stats = None
    per_match_stats = []
    match_evolution_stats = []
    role_overview = {
        "available": False,
        "principal_code": None,
        "principal_label": "Non determine",
        "plausibility_pct": 0.0,
        "consistency_pct": 0.0,
        "average_confidence_pct": 0.0,
        "coverage_pct": 0.0,
        "match_count": 0,
        "roles": [],
        "sources": [],
        "evidence": [],
    }
    if stats_rows:
        filtered_stats_rows = [row for row in stats_rows if row.match_id in filtered_match_ids]
        detailed_models = [
            JoueurMatchDetailedStats.model_validate(row.stats_data)
            for row in filtered_stats_rows
        ]
        aggregated = aggregate_joueur_stats(detailed_models)
        if aggregated is not None:
            aggregated_stats = aggregated.model_dump(mode="json")

        role_distribution_matchs = (
            (aggregated_stats or {}).get("role_distribution_matchs")
            if aggregated_stats
            else {}
        ) or {}
        role_scores_moyens = (
            (aggregated_stats or {}).get("role_scores_moyens")
            if aggregated_stats
            else {}
        ) or {}
        role_principal_global = (
            (aggregated_stats or {}).get("role_principal_global")
            if aggregated_stats
            else None
        )

        role_counts_local: dict[str, int] = defaultdict(int)
        role_confidences: list[float] = []
        source_counts: dict[str, int] = defaultdict(int)
        evidence_items: list[str] = []
        role_known_count = 0

        matchs_by_id = {m.id: m for m in matchs}
        for row in filtered_stats_rows:
            match = matchs_by_id.get(row.match_id)
            side = row.stats_data.get("side")
            adversaire = "?"
            niveau_competition = None
            if match and match.competition:
                niveau_competition_badge = resolve_niveau_badge(
                    match.competition.niveau,
                    match.competition.nom,
                    match.competition.categorie,
                    match.competition.division,
                )
                niveau_competition = (
                    niveau_competition_badge["label"]
                    if niveau_competition_badge
                    else match.competition.niveau
                )
            niveau_equipe = None
            niveau_adverse = None
            if match and match.equipe_a and match.equipe_b:
                if side == "A":
                    adversaire = match.equipe_b.nom
                    niveau_equipe_badge = resolve_niveau_badge(
                        match.equipe_a.niveau,
                        match.equipe_a.nom,
                        match.equipe_a.categorie,
                        match.equipe_a.division,
                    )
                    niveau_adverse_badge = resolve_niveau_badge(
                        match.equipe_b.niveau,
                        match.equipe_b.nom,
                        match.equipe_b.categorie,
                        match.equipe_b.division,
                    )
                    niveau_equipe = niveau_equipe_badge["label"] if niveau_equipe_badge else match.equipe_a.niveau
                    niveau_adverse = niveau_adverse_badge["label"] if niveau_adverse_badge else match.equipe_b.niveau
                elif side == "B":
                    adversaire = match.equipe_a.nom
                    niveau_equipe_badge = resolve_niveau_badge(
                        match.equipe_b.niveau,
                        match.equipe_b.nom,
                        match.equipe_b.categorie,
                        match.equipe_b.division,
                    )
                    niveau_adverse_badge = resolve_niveau_badge(
                        match.equipe_a.niveau,
                        match.equipe_a.nom,
                        match.equipe_a.categorie,
                        match.equipe_a.division,
                    )
                    niveau_equipe = niveau_equipe_badge["label"] if niveau_equipe_badge else match.equipe_b.niveau
                    niveau_adverse = niveau_adverse_badge["label"] if niveau_adverse_badge else match.equipe_a.niveau

            niveau_principal = niveau_competition or niveau_equipe or niveau_adverse
            numero_participation = None
            participation = participation_by_match_id.get(row.match_id)
            if participation and participation.numero_maillot:
                numero_participation = participation.numero_maillot.strip() or None
            numero_stats_data = (row.stats_data.get("numero") or "").strip() or None
            numero_display = numero_participation or numero_stats_data

            points_gagnes = int(row.stats_data.get("points_gagnes") or 0)
            points_gagnes_service = int(row.stats_data.get("points_gagnes_service") or 0)
            points_gagnes_sideout_raw = row.stats_data.get("points_gagnes_sideout")
            if points_gagnes_sideout_raw is None:
                points_gagnes_sideout = max(0, points_gagnes - points_gagnes_service)
            else:
                points_gagnes_sideout = max(0, int(points_gagnes_sideout_raw))
            services_total = int(
                row.stats_data.get("services")
                or row.stats_data.get("nb_services")
                or 0
            )

            ratio_points_gagnes = row.stats_data.get("ratio_points_gagnes") or 0
            ratio_points_pct = round(float(ratio_points_gagnes) * 100, 1)
            break_point_ratio_raw = row.stats_data.get("break_point_ratio")
            if break_point_ratio_raw is not None:
                break_point_ratio_pct = round(float(break_point_ratio_raw) * 100, 1)
            elif services_total > 0:
                break_point_ratio_pct = round((points_gagnes_service / services_total) * 100, 1)
            else:
                break_point_ratio_pct = 0.0

            sideout_contribution_raw = row.stats_data.get("sideout_contribution_ratio")
            if sideout_contribution_raw is not None:
                sideout_contribution_pct = round(float(sideout_contribution_raw) * 100, 1)
            elif points_gagnes > 0:
                sideout_contribution_pct = round((points_gagnes_sideout / points_gagnes) * 100, 1)
            else:
                sideout_contribution_pct = 0.0

            role_code = row.stats_data.get("role_principal")
            role_confidence = float(row.stats_data.get("role_confiance") or 0.0)
            role_indices = [
                str(item).strip()
                for item in (row.stats_data.get("indices_roles") or [])
                if str(item).strip()
            ]
            role_sources: list[str] = []
            for hint in role_indices:
                source_label = _role_hint_source(hint)
                source_counts[source_label] += 1
                if source_label not in role_sources:
                    role_sources.append(source_label)
                if hint not in evidence_items and len(evidence_items) < 10:
                    evidence_items.append(hint)

            if role_code:
                role_known_count += 1
                role_counts_local[role_code] += 1
                role_confidences.append(role_confidence)

            per_match_stats.append(
                {
                    "match_id": row.match_id,
                    "date": match.date_match.isoformat() if match and match.date_match else None,
                    "adversaire": adversaire,
                    "competition_id": match.competition.id if match and match.competition else None,
                    "numero": numero_display,
                    "niveau_competition": niveau_competition,
                    "niveau_equipe": niveau_equipe,
                    "niveau_adverse": niveau_adverse,
                    "niveau_principal": niveau_principal,
                    "niveau_rank": _level_rank(niveau_principal),
                    "equipe_id": match.equipe_a.id if match and side == "A" and match.equipe_a else (match.equipe_b.id if match and side == "B" and match.equipe_b else None),
                    "adversaire_id": match.equipe_b.id if match and side == "A" and match.equipe_b else (match.equipe_a.id if match and side == "B" and match.equipe_a else None),
                    "ratio_points_pct": ratio_points_pct,
                    "break_point_ratio_pct": break_point_ratio_pct,
                    "points_gagnes_sideout": points_gagnes_sideout,
                    "sideout_contribution_pct": sideout_contribution_pct,
                    "role_code": role_code,
                    "role_label": role_label(role_code),
                    "role_plausibility_pct": round(role_confidence * 100, 1),
                    "role_sources": role_sources,
                    "role_indices": role_indices,
                    "stats": row.stats_data,
                }
            )

        analyzed_matches = len(filtered_stats_rows)
        if analyzed_matches > 0:
            average_confidence = (
                sum(role_confidences) / len(role_confidences)
                if role_confidences
                else 0.0
            )
            consistency_ratio = (
                max(role_counts_local.values()) / role_known_count
                if role_known_count > 0
                else 0.0
            )
            coverage_ratio = role_known_count / analyzed_matches if analyzed_matches > 0 else 0.0

            plausibility_pct = round(
                (0.55 * average_confidence + 0.35 * consistency_ratio + 0.10 * coverage_ratio) * 100,
                1,
            )

            if not role_principal_global and role_counts_local:
                role_principal_global = max(
                    role_counts_local.items(), key=lambda item: (item[1], item[0])
                )[0]

            role_codes = (
                set(role_scores_moyens.keys())
                | set(role_distribution_matchs.keys())
                | set(role_counts_local.keys())
            )
            role_rows = [
                {
                    "code": role_code,
                    "label": role_label(role_code),
                    "score_pct": round(float(role_scores_moyens.get(role_code, 0.0)) * 100, 1),
                    "matches": int(
                        role_distribution_matchs.get(
                            role_code,
                            role_counts_local.get(role_code, 0),
                        )
                    ),
                }
                for role_code in sorted(
                    role_codes,
                    key=lambda code: (
                        -float(role_scores_moyens.get(code, 0.0)),
                        -int(role_distribution_matchs.get(code, role_counts_local.get(code, 0))),
                        code,
                    ),
                )
            ]

            source_total = sum(source_counts.values())
            source_rows = [
                {
                    "label": label,
                    "count": count,
                    "pct": round((count / source_total) * 100, 1) if source_total > 0 else 0.0,
                }
                for label, count in sorted(
                    source_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ]

            role_overview = {
                "available": bool(role_principal_global or role_rows),
                "principal_code": role_principal_global,
                "principal_label": role_label(role_principal_global),
                "plausibility_pct": plausibility_pct,
                "consistency_pct": round(consistency_ratio * 100, 1),
                "average_confidence_pct": round(average_confidence * 100, 1),
                "coverage_pct": round(coverage_ratio * 100, 1),
                "match_count": analyzed_matches,
                "roles": role_rows,
                "sources": source_rows,
                "evidence": evidence_items,
            }

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
                    "points_gagnes_sideout": (
                        max(0, int(pms.get("points_gagnes_sideout")))
                        if pms.get("points_gagnes_sideout") is not None
                        else max(0, int(pms.get("points_gagnes") or 0) - int(pms.get("points_gagnes_service") or 0))
                    ),
                    "services": int(pms.get("services") or 0),
                    "max_serie": int(pms.get("max_serie") or 0),
                    "temps_jeu_estime": pms.get("temps_jeu_estime"),
                    "ratio_points_pct": item["ratio_points_pct"],
                    "break_point_ratio_pct": item["break_point_ratio_pct"],
                    "sideout_contribution_pct": item["sideout_contribution_pct"],
                    "role_principal": pms.get("role_principal"),
                    "role_plausibility_pct": round(float(pms.get("role_confiance") or 0.0) * 100, 1),
                }
            )

    recent_matchs = []
    for row in filtered_rows[:10]:
        match = row["match"]
        equipe_joueur = row["equipe_joueur"]
        adversaire = row["adversaire"]
        side = row["side"]
        if side == "A":
            score_for = match.sets_equipe_a
            score_against = match.sets_equipe_b
            score = f"{score_for}-{score_against}" if match.match_joue else "â€”"
            domicile_exterieur = "Domicile"
        elif side == "B":
            score_for = match.sets_equipe_b
            score_against = match.sets_equipe_a
            score = f"{score_for}-{score_against}" if match.match_joue else "â€”"
            domicile_exterieur = "ExtÃ©rieur"
        else:
            score = f"{match.sets_equipe_a or 0}-{match.sets_equipe_b or 0}" if match.match_joue else "â€”"
            domicile_exterieur = "Inconnu"
        recent_matchs.append(
            {
                "match_id": match.id,
                "date": match.date_match,
                "competition_id": row["competition"].id if row["competition"] else None,
                "equipe_nom": equipe_joueur.nom if equipe_joueur else "?",
                "equipe_id": equipe_joueur.id if equipe_joueur else None,
                "adversaire_nom": adversaire.nom if adversaire else "?",
                "adversaire_id": adversaire.id if adversaire else None,
                "club_id": row["club"].id if row["club"] else None,
                "club_nom": row["club"].nom if row["club"] else None,
                "score": score,
                "victoire": row["victoire"],
                "niveau": row["niveau"],
                "domicile_exterieur": domicile_exterieur,
            }
        )

    match_rows = []
    for row in filtered_rows:
        match = row["match"]
        side = row["side"]
        competition = row["competition"]
        if side == "A":
            score_for = match.sets_equipe_a
            score_against = match.sets_equipe_b
            score = f"{score_for}-{score_against}" if match.match_joue else "â€”"
            domicile_exterieur = "Domicile"
        elif side == "B":
            score_for = match.sets_equipe_b
            score_against = match.sets_equipe_a
            score = f"{score_for}-{score_against}" if match.match_joue else "â€”"
            domicile_exterieur = "ExtÃ©rieur"
        else:
            score = f"{match.sets_equipe_a or 0}-{match.sets_equipe_b or 0}" if match.match_joue else "â€”"
            domicile_exterieur = "Inconnu"
        match_rows.append(
            {
                "match_id": match.id,
                "date": match.date_match,
                "saison": row["saison"].code if row["saison"] else None,
                "competition": competition.nom if competition else None,
                "competition_id": competition.id if competition else None,
                "equipe_id": row["equipe_joueur"].id if row["equipe_joueur"] else None,
                "equipe_nom": row["equipe_joueur"].nom if row["equipe_joueur"] else "?",
                "adversaire_id": row["adversaire"].id if row["adversaire"] else None,
                "adversaire_nom": row["adversaire"].nom if row["adversaire"] else "?",
                "niveau": row["niveau"],
                "score": score,
                "victoire": row["victoire"],
                "domicile_exterieur": domicile_exterieur,
            }
        )

    map_markers = []
    for row in filtered_rows:
        match = row["match"]
        home_team = match.equipe_a
        if not home_team or not home_team.club:
            continue
        club = home_team.club
        lat = club.latitude
        lng = club.longitude
        if lat is None or lng is None:
            for salle in club.salles:
                if salle.latitude is not None and salle.longitude is not None:
                    lat = salle.latitude
                    lng = salle.longitude
                    break
        if lat is None or lng is None:
            continue
        map_markers.append(
            {
                "lat": lat,
                "lng": lng,
                "label": f"{row['equipe_joueur'].nom if row['equipe_joueur'] else '?'} vs {row['adversaire'].nom if row['adversaire'] else '?'}",
                "color": "#22c55e" if row["victoire"] is True else ("#ef4444" if row["victoire"] is False else "#3b82f6"),
                "popup_html": (
                    f"<strong><a href='/matchs/{match.id}'>"
                    f"{row['equipe_joueur'].nom if row['equipe_joueur'] else '?'} vs {row['adversaire'].nom if row['adversaire'] else '?'}"
                    f"</a></strong><br>"
                    f"{match.date_match.strftime('%d/%m/%Y') if match.date_match else 'Date inconnue'}"
                    f"<br>{'Domicile' if row['side'] == 'A' else ('ExtÃ©rieur' if row['side'] == 'B' else 'Inconnu')}"
                ),
            }
        )

    active_filter_count = 0
    if selected_saison_ids:
        active_filter_count += 1
    if date_from_obj or date_to_obj:
        active_filter_count += 1
    if selected_equipe_ids:
        active_filter_count += 1
    if selected_club_ids:
        active_filter_count += 1
    if selected_competition_ids:
        active_filter_count += 1
    if selected_niveaux:
        active_filter_count += 1
    if resultat:
        active_filter_count += 1
    if domicile_exterieur:
        active_filter_count += 1

    allowed_tabs = {"resume", "stats", "matchs", "carte"}
    initial_tab = tab if tab in allowed_tabs else "resume"

    return templates.TemplateResponse(
        "joueurs/detail.html",
        {
            "request": request,
            "joueur": joueur,
            "matchs": matchs,
            "stats": stats,
            "recent_matchs": recent_matchs,
            "match_rows": match_rows,
            "player_profile": player_profile,
            "estimated_age": estimated_age,
            "numero_stats": numero_stats,
            "jersey_cards": jersey_cards,
            "jersey_profile": jersey_profile,
            "level_timeline": level_timeline,
            "level_rank_labels": level_rank_labels,
            "level_reference_order_text": level_reference_order_text,
            "level_timeline_summary": level_timeline_summary,
            "aggregated_stats": aggregated_stats,
            "role_overview": role_overview,
            "per_match_stats": per_match_stats,
            "match_evolution_stats": match_evolution_stats,
            "initial_tab": initial_tab,
            "filter_options": filter_options,
            "hide_filters": hide_filters,
            "filter_state": {
                "saison_ids": sorted(selected_saison_ids),
                "date_from": date_from_obj.isoformat() if date_from_obj else "",
                "date_to": date_to_obj.isoformat() if date_to_obj else "",
                "equipe_ids": sorted(selected_equipe_ids),
                "club_ids": sorted(selected_club_ids),
                "competition_ids": sorted(selected_competition_ids),
                "niveaux": sorted(selected_niveaux),
                "resultat": resultat or "",
                "domicile_exterieur": domicile_exterieur or "",
            },
            "active_filter_count": active_filter_count,
            "base_match_count": len(base_rows),
            "map_markers": map_markers,
        },
    )
