"""
Routes web — Joueurs (liste et détail).
"""

import unicodedata
from datetime import date as dt_date
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


def _parse_date(value: Optional[str]) -> Optional[dt_date]:
    if not value:
        return None
    try:
        return dt_date.fromisoformat(value)
    except ValueError:
        return None


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
            {"request": request, "message": "Joueur non trouvé"},
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

        side = None
        equipe_joueur = None
        adversaire = None
        if match.equipe_a_id == participation.equipe_id:
            side = "A"
            equipe_joueur = match.equipe_a
            adversaire = match.equipe_b
        elif match.equipe_b_id == participation.equipe_id:
            side = "B"
            equipe_joueur = match.equipe_b
            adversaire = match.equipe_a

        if side is None:
            continue

        niveau_principal = (
            match.competition.niveau if match.competition and match.competition.niveau else None
        ) or (equipe_joueur.niveau if equipe_joueur and equipe_joueur.niveau else None)

        victoire = None
        if match.match_joue:
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
        "niveaux": sorted(niveaux_set),
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
        else:
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

    numero_counts: dict[str, int] = {}
    for row in filtered_rows:
        participation = row["participation"]
        numero = (participation.numero_maillot or "").strip()
        if not numero:
            continue
        numero_counts[numero] = numero_counts.get(numero, 0) + 1

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
    stats_rows = stats_service.repo.get_for_joueur(joueur_id, limit=1200)

    aggregated_stats = None
    per_match_stats = []
    match_evolution_stats = []
    if stats_rows:
        filtered_stats_rows = [row for row in stats_rows if row.match_id in filtered_match_ids]
        detailed_models = [
            JoueurMatchDetailedStats.model_validate(row.stats_data)
            for row in filtered_stats_rows
        ]
        aggregated = aggregate_joueur_stats(detailed_models)
        if aggregated is not None:
            aggregated_stats = aggregated.model_dump(mode="json")

        matchs_by_id = {m.id: m for m in matchs}
        for row in filtered_stats_rows:
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

    recent_matchs = []
    for row in filtered_rows[:10]:
        match = row["match"]
        equipe_joueur = row["equipe_joueur"]
        adversaire = row["adversaire"]
        side = row["side"]
        if side == "A":
            score_for = match.sets_equipe_a
            score_against = match.sets_equipe_b
        else:
            score_for = match.sets_equipe_b
            score_against = match.sets_equipe_a
        recent_matchs.append(
            {
                "match_id": match.id,
                "date": match.date_match,
                "equipe_nom": equipe_joueur.nom if equipe_joueur else "?",
                "adversaire_nom": adversaire.nom if adversaire else "?",
                "score": f"{score_for}-{score_against}" if match.match_joue else "—",
                "victoire": row["victoire"],
                "niveau": row["niveau"],
                "domicile_exterieur": "Domicile" if side == "A" else "Extérieur",
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
        else:
            score_for = match.sets_equipe_b
            score_against = match.sets_equipe_a
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
                "score": f"{score_for}-{score_against}" if match.match_joue else "—",
                "victoire": row["victoire"],
                "domicile_exterieur": "Domicile" if side == "A" else "Extérieur",
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
                    f"<br>{'Domicile' if row['side'] == 'A' else 'Extérieur'}"
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
            "numero_stats": numero_stats,
            "aggregated_stats": aggregated_stats,
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
