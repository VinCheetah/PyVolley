"""
Routes web — Compétitions (liste, détail, et compétitions jeunes).
"""

from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse

from pyvolley.web.templateconfig import templates
from pyvolley.web.helpers.brackets import build_bracket_tree, build_challenge_bracket
from pyvolley.shared.helpers import parse_optional_int
from pyvolley.api.dependencies import (
    get_competition_repo,
    get_match_repo,
    get_equipe_repo,
    get_saison_repo,
)
from pyvolley.database.repositories import (
    CompetitionRepository,
    MatchRepository,
    EquipeRepository,
    SaisonRepository,
)
from pyvolley.analysis.classement import MatchData, calculer_classement

router = APIRouter()


@router.get("/competitions", response_class=HTMLResponse)
async def competitions_list(
    request: Request,
    saison_id: Optional[str] = Query(None),
    genre: Optional[str] = None,
    categorie: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: CompetitionRepository = Depends(get_competition_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
):
    saison_id_int = parse_optional_int(saison_id)

    limit = 50
    if saison_id_int:
        competitions = repo.get_by_saison(
            saison_id_int,
            genre=genre,
            categorie=categorie,
            exclude_code_only=True,
        )
    else:
        offset = (page - 1) * limit
        competitions = repo.get_all(
            limit=limit,
            offset=offset,
            genre=genre,
            categorie=categorie,
            exclude_code_only=True,
        )
    total = repo.count()
    saisons = saison_repo.get_all(limit=20)
    genres = repo.get_distinct_genres()
    categories = repo.get_distinct_categories()
    return templates.TemplateResponse(
        "competitions/list.html",
        {
            "request": request,
            "competitions": competitions,
            "total": total,
            "page": page,
            "has_next": False,
            "has_prev": page > 1,
            "saisons": saisons,
            "current_saison_id": saison_id_int,
            "genre": genre or "",
            "genres": genres,
            "categorie": categorie or "",
            "categories": categories,
        },
    )


@router.get("/competitions/{competition_id}", response_class=HTMLResponse)
async def competition_detail(
    request: Request,
    competition_id: int,
    competition_repo: CompetitionRepository = Depends(get_competition_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    """Page de détail d'une compétition avec classement et évolution."""
    competition = competition_repo.get_with_details(competition_id)
    if not competition:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Compétition non trouvée"},
            status_code=404,
        )

    # Detect youth competition
    from pyvolley.scrapers.ffvb.jeunes import is_youth_competition

    is_jeunes = is_youth_competition(competition.nom)

    if is_jeunes:
        return await _render_youth_competition(
            request, competition, competition_repo, match_repo, equipe_repo
        )

    is_multi_poule = competition.poules and len(competition.poules) > 1

    classement = None
    evolution_json = []
    poules_classements = []

    if is_multi_poule:
        poules_classements_raw = competition_repo.get_classements_par_poule(
            competition_id
        )
        for poule, cls in poules_classements_raw:
            evo = (
                [e.model_dump(mode="json") for e in cls.evolution]
                if cls.evolution
                else []
            )
            poules_classements.append(
                {"poule": poule, "classement": cls, "evolution_json": evo}
            )
    else:
        classement = competition_repo.get_classement(competition_id)
        if classement and classement.evolution:
            evolution_json = [
                e.model_dump(mode="json") for e in classement.evolution
            ]

    matchs = match_repo.search(competition_id=competition_id, limit=500)
    equipes = competition_repo.get_equipes_for_competition(competition_id)

    return templates.TemplateResponse(
        "competitions/detail.html",
        {
            "request": request,
            "competition": competition,
            "classement": classement,
            "evolution_json": evolution_json,
            "poules_classements": poules_classements,
            "is_multi_poule": is_multi_poule,
            "matchs": matchs,
            "equipes": equipes,
        },
    )


# ═══════════════════════════════════════════════════════════════════
#  Compétitions Jeunes (Coupe de France)
# ═══════════════════════════════════════════════════════════════════


async def _render_youth_competition(
    request: Request,
    competition,
    competition_repo: CompetitionRepository,
    match_repo: MatchRepository,
    equipe_repo: EquipeRepository,
):
    """Render a Coupe de France Jeunes competition with tour-based layout."""
    competition_id = competition.id

    # ── 1. Fetch all matchs ──
    all_matchs = match_repo.search(competition_id=competition_id, limit=10000)

    # ── 2. Group matchs by journée (= tour) ──
    matchs_by_tour: dict[str, list] = defaultdict(list)
    for m in all_matchs:
        tour_key = m.journee or "00"
        matchs_by_tour[tour_key].append(m)

    # ── 3. Build per-tour data ──
    tours_data = []
    for tour_key in sorted(matchs_by_tour.keys(), key=lambda k: int(k)):
        tour_matchs = matchs_by_tour[tour_key]
        tour_num = int(tour_key)

        matchs_by_poule: dict[str, list] = defaultdict(list)
        poule_id_map: dict[str, int] = {}
        for m in tour_matchs:
            poule_code = m.poule.code if m.poule else "???"
            matchs_by_poule[poule_code].append(m)
            if m.poule and poule_code not in poule_id_map:
                poule_id_map[poule_code] = m.poule.id

        tour_equipe_ids = set()
        for m in tour_matchs:
            if m.equipe_a_id:
                tour_equipe_ids.add(m.equipe_a_id)
            if m.equipe_b_id:
                tour_equipe_ids.add(m.equipe_b_id)

        poule_classements = _compute_poule_classements(
            matchs_by_poule, poule_id_map
        )

        label = "Phases finales" if tour_num == 99 else f"Tour {tour_num}"

        tours_data.append(
            {
                "tour_num": tour_num,
                "label": label,
                "poule_classements": poule_classements,
                "nb_poules": len(matchs_by_poule),
                "nb_equipes": len(tour_equipe_ids),
                "nb_matchs": len(tour_matchs),
                "nb_matchs_joues": sum(1 for m in tour_matchs if m.match_joue),
                "matchs": tour_matchs,
            }
        )

    # ── 4. Separate finals (J99) from qualifying tours ──
    finals_tour = None
    qualifying_tours = []
    for td in tours_data:
        if td["tour_num"] == 99:
            finals_tour = td
        else:
            qualifying_tours.append(td)

    # ── 5. Build finals data ──
    finals_data = _build_finals_data(finals_tour) if finals_tour else {}

    # ── 6. All equipes ──
    equipes = competition_repo.get_equipes_for_competition(competition_id)

    return templates.TemplateResponse(
        "competitions/detail_jeunes.html",
        {
            "request": request,
            "competition": competition,
            "tours_data": tours_data,
            "qualifying_tours": qualifying_tours,
            "finals_tour": finals_tour,
            "matchs": all_matchs,
            "equipes": equipes,
            "is_youth": True,
            **finals_data,
        },
    )


def _compute_poule_classements(
    matchs_by_poule: dict[str, list],
    poule_id_map: dict[str, int],
) -> list[dict]:
    """Compute mini-classements for each poule in a tour."""
    poule_classements = []
    for poule_code in sorted(matchs_by_poule.keys()):
        poule_matchs = matchs_by_poule[poule_code]
        match_data_list = []
        for m in poule_matchs:
            if m.match_joue and (m.sets_equipe_a or 0) + (m.sets_equipe_b or 0) > 0:
                match_data_list.append(
                    MatchData(
                        match_id=m.id,
                        equipe_a_id=m.equipe_a_id,
                        equipe_a_nom=m.equipe_a.nom if m.equipe_a else "?",
                        equipe_b_id=m.equipe_b_id,
                        equipe_b_nom=m.equipe_b.nom if m.equipe_b else "?",
                        sets_a=m.sets_equipe_a or 0,
                        sets_b=m.sets_equipe_b or 0,
                        points_a=0,
                        points_b=0,
                        match_joue=True,
                    )
                )
        if match_data_list:
            cls_lines = calculer_classement(match_data_list)
            poule_classements.append(
                {
                    "poule_code": poule_code,
                    "poule_id": poule_id_map.get(poule_code),
                    "classement": cls_lines,
                    "matchs": poule_matchs,
                    "nb_equipes": len(
                        {m.equipe_a_id for m in poule_matchs}
                        | {m.equipe_b_id for m in poule_matchs}
                    ),
                }
            )
    return poule_classements


def _build_finals_data(finals_tour: dict) -> dict:
    """Build all finals-related template context data.

    Returns a dict ready to be unpacked into the template context.
    """
    finals_classement = None
    finals_bracket_matchs = []
    finals_pool_classements = []
    finals_format = "none"
    bracket_8 = None
    bracket_tree = None
    classement_9_12 = None
    challenge_bracket = None
    challenge_pools = []

    # ── Classify finals poules by structure ──
    brassage_pools = []
    pools_4_teams = []
    bracket_poules = []
    cross_poules = []

    for pc in finals_tour["poule_classements"]:
        nb_eq = pc["nb_equipes"]
        nb_matchs = len(pc["matchs"])

        if nb_eq > nb_matchs:
            cross_poules.append(pc)
        elif nb_matchs >= 10 and nb_eq >= 7:
            bracket_poules.append(pc)
        elif nb_eq <= 3:
            brassage_pools.append(pc)
        elif nb_eq == 4 and nb_matchs == 6:
            pools_4_teams.append(pc)
        else:
            brassage_pools.append(pc)

    # ── Detect format ──
    if bracket_poules:
        finals_format = "standard"
        bracket_8 = bracket_poules[0]
        classement_9_12 = pools_4_teams[0] if pools_4_teams else None
        finals_pool_classements = brassage_pools
    elif cross_poules:
        finals_format = "challenge"
        challenge_pools = pools_4_teams
    else:
        finals_format = "simple"
        finals_pool_classements = brassage_pools + pools_4_teams

    # ═══ STANDARD FORMAT ═══
    bracket_classement = []
    if finals_format == "standard" and bracket_8:
        finals_bracket_matchs = bracket_8["matchs"]
        bracket_cls = bracket_8["classement"]

        bracket_matchs_sorted = sorted(
            finals_bracket_matchs, key=lambda m: m.code_match or ""
        )
        bracket_tree = build_bracket_tree(bracket_matchs_sorted)

        nb_matchs = len(bracket_matchs_sorted)
        if nb_matchs >= 12:
            last_round = bracket_matchs_sorted[-4:]
            placement_matchs = list(reversed(last_round))

            placed_teams = []
            for i, m in enumerate(placement_matchs):
                if not m.match_joue:
                    continue
                sa = m.sets_equipe_a or 0
                sb = m.sets_equipe_b or 0
                if sa > sb:
                    winner_id, loser_id = m.equipe_a_id, m.equipe_b_id
                else:
                    winner_id, loser_id = m.equipe_b_id, m.equipe_a_id
                rank_w = i * 2 + 1
                rank_l = i * 2 + 2
                placed_teams.append((rank_w, winner_id))
                placed_teams.append((rank_l, loser_id))

            bracket_cls_by_id = {e.equipe_id: e for e in bracket_cls}
            for rank, team_id in sorted(placed_teams):
                entry = bracket_cls_by_id.get(team_id)
                if entry:
                    entry.rang = rank
                    bracket_classement.append(entry)
        else:
            bracket_classement = list(bracket_cls)

        # Classement 9-12
        classement_9_12_entries = []
        if classement_9_12:
            cls_9_12 = classement_9_12["classement"]
            for i, entry in enumerate(cls_9_12):
                entry.rang = 9 + i
            classement_9_12_entries = list(cls_9_12)

        finals_classement = bracket_classement + classement_9_12_entries

    # ═══ CHALLENGE FORMAT ═══
    elif finals_format == "challenge" and cross_poules:
        challenge_bracket = build_challenge_bracket(cross_poules)

        if challenge_bracket:
            all_finals_matchs = finals_tour["matchs"]
            match_data_list = []
            for m in all_finals_matchs:
                if m.match_joue and (m.sets_equipe_a or 0) + (m.sets_equipe_b or 0) > 0:
                    match_data_list.append(
                        MatchData(
                            match_id=m.id,
                            equipe_a_id=m.equipe_a_id,
                            equipe_a_nom=m.equipe_a.nom if m.equipe_a else "?",
                            equipe_b_id=m.equipe_b_id,
                            equipe_b_nom=m.equipe_b.nom if m.equipe_b else "?",
                            sets_a=m.sets_equipe_a or 0,
                            sets_b=m.sets_equipe_b or 0,
                            points_a=0,
                            points_b=0,
                            match_joue=True,
                        )
                    )

            if match_data_list:
                all_cls = calculer_classement(match_data_list)
                cls_by_id = {e.equipe_id: e for e in all_cls}

                placed_teams = []
                for half, start_rank in [
                    (challenge_bracket["upper"], 1),
                    (challenge_bracket["lower"], 5),
                ]:
                    for match, rw, rl in [
                        (half["final"], start_rank, start_rank + 1),
                        (half["bronze"], start_rank + 2, start_rank + 3),
                    ]:
                        if match and match.match_joue:
                            sa = match.sets_equipe_a or 0
                            sb = match.sets_equipe_b or 0
                            if sa > sb:
                                placed_teams.append((rw, match.equipe_a_id))
                                placed_teams.append((rl, match.equipe_b_id))
                            else:
                                placed_teams.append((rw, match.equipe_b_id))
                                placed_teams.append((rl, match.equipe_a_id))

                finals_classement = []
                for rank, team_id in sorted(placed_teams):
                    entry = cls_by_id.get(team_id)
                    if entry:
                        entry.rang = rank
                        finals_classement.append(entry)

    return {
        "finals_format": finals_format,
        "finals_classement": finals_classement,
        "finals_bracket_matchs": finals_bracket_matchs,
        "finals_pool_classements": finals_pool_classements,
        "classement_9_12": classement_9_12 if finals_format == "standard" else None,
        "bracket_8": bracket_8 if finals_format == "standard" else None,
        "bracket_tree": bracket_tree,
        "challenge_bracket": challenge_bracket,
        "challenge_pools": challenge_pools,
    }
