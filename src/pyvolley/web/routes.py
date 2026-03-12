"""
Routes web pour l'interface utilisateur PyVolley.
"""

import json
from typing import Optional
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from pyvolley.web.app import templates
from pyvolley.api.dependencies import (
    get_joueur_repo,
    get_club_repo,
    get_equipe_repo,
    get_match_repo,
    get_saison_repo,
    get_competition_repo,
    get_arbitre_repo,
    get_poule_repo,
    get_session,
)
from pyvolley.database.repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    MatchRepository,
    SaisonRepository,
    CompetitionRepository,
    ArbitreRepository,
    PouleRepository,
)
from pyvolley.scrapers.ffvb.utils import build_equipe_ffvb_url
from pyvolley.core.config import get_settings


web_router = APIRouter()


def _parse_optional_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


# ============== Dashboard ==============

@web_router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
    competition_repo: CompetitionRepository = Depends(get_competition_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    stats = {
        "matchs": match_repo.count(),
        "joueurs": joueur_repo.count(),
        "clubs": club_repo.count(),
        "equipes": equipe_repo.count(),
        "arbitres": arbitre_repo.count(),
        "competitions": competition_repo.count(),
    }
    derniers_matchs = match_repo.search(limit=10)
    saisons = saison_repo.get_all(limit=20)

    # Stats pour les graphiques
    matchs_par_saison = match_repo.count_by_saison()
    matchs_par_mois = match_repo.get_stats_by_month()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": stats,
        "derniers_matchs": derniers_matchs,
        "saisons": saisons,
        "matchs_par_saison": [
            {"saison": code, "count": count} for code, count in matchs_par_saison
        ],
        "matchs_par_mois": [
            {"year": int(y), "month": int(m), "count": c}
            for y, m, c in matchs_par_mois
        ],
    })


# ============== Recherche ==============

@web_router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: Optional[str] = Query(None, min_length=2),
    genre: Optional[str] = Query(None),
    niveau: Optional[str] = Query(None),
    saison_id: Optional[int] = Query(None),
    ligue: Optional[str] = Query(None),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
):
    results = {
        "joueurs": [], "clubs": [], "equipes": [], "arbitres": [],
        "query": q or "",
        "genre": genre or "",
        "niveau": niveau or "",
        "saison_id": saison_id,
        "ligue": ligue or "",
    }

    if q:
        results["joueurs"] = joueur_repo.search_by_name(
            q, genre=genre, saison_id=saison_id, limit=30,
        )
        results["clubs"] = club_repo.search_by_name(q, limit=30)
        results["equipes"] = equipe_repo.search_by_name(
            q, genre=genre, niveau=niveau, saison_id=saison_id, limit=30,
        )
        results["arbitres"] = arbitre_repo.search_by_name(
            q, ligue=ligue, limit=30,
        )

    # Options pour les filtres
    saisons = saison_repo.get_all(limit=20)
    genres = equipe_repo.get_distinct_genres()
    niveaux = equipe_repo.get_distinct_niveaux()
    ligues = arbitre_repo.get_distinct_ligues()

    return templates.TemplateResponse("search.html", {
        "request": request,
        **results,
        "saisons": saisons,
        "genres": genres,
        "niveaux": niveaux,
        "ligues": ligues,
    })


# ============== Joueurs ==============

@web_router.get("/joueurs", response_class=HTMLResponse)
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
    return templates.TemplateResponse("joueurs/list.html", {
        "request": request, "joueurs": joueurs, "query": q,
        "page": page, "total": total,
        "has_next": offset + limit < total, "has_prev": page > 1,
        "genre": genre or "", "genres": genres,
    })


@web_router.get("/joueurs/{joueur_id}", response_class=HTMLResponse)
async def joueur_detail(
    request: Request,
    joueur_id: int,
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    joueur = joueur_repo.get(joueur_id)
    if not joueur:
        return templates.TemplateResponse("error.html",
            {"request": request, "message": "Joueur non trouvé"}, status_code=404)
    matchs = match_repo.get_by_joueur(joueur_id, limit=200)
    stats = joueur_repo.get_stats(joueur_id)
    detailed_stats = joueur_repo.get_detailed_stats(joueur_id)

    # Calcul des statistiques de performance agrégées
    aggregated_stats = None
    per_match_stats = []
    from pyvolley.database.converters import match_db_to_core
    from pyvolley.analysis.joueur_stats import analyze_joueur_match, aggregate_joueur_stats

    all_detailed = []
    for m in matchs:
        if not m.has_details:
            continue
        m_full = match_repo.get_with_details(m.id)
        if not m_full:
            continue
        participants_a = [p for p in (m_full.participations or []) if p.equipe_id == m_full.equipe_a_id]
        participants_b = [p for p in (m_full.participations or []) if p.equipe_id == m_full.equipe_b_id]
        match_core = match_db_to_core(m_full, participants_a, participants_b)
        s = analyze_joueur_match(match_core, joueur.licence)
        if s:
            all_detailed.append(s)
            per_match_stats.append({
                "match_id": m.id,
                "date": m.date_match,
                "adversaire": (m.equipe_b.nom if m.equipe_a_id and any(
                    p.equipe_id == m.equipe_a_id for p in (m_full.participations or []) if p.joueur_id == joueur_id
                ) else m.equipe_a.nom) if m.equipe_a and m.equipe_b else "?",
                "stats": s,
            })

    aggregated_stats = aggregate_joueur_stats(all_detailed)

    return templates.TemplateResponse("joueurs/detail.html", {
        "request": request, "joueur": joueur, "matchs": matchs,
        "stats": stats, "detailed_stats": detailed_stats,
        "aggregated_stats": aggregated_stats,
        "per_match_stats": per_match_stats,
    })


# ============== Équipes ==============

@web_router.get("/equipes", response_class=HTMLResponse)
async def equipes_list(
    request: Request,
    q: Optional[str] = None,
    genre: Optional[str] = None,
    niveau: Optional[str] = None,
    categorie: Optional[str] = None,
    saison_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    repo: EquipeRepository = Depends(get_equipe_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
):
    limit = 50
    offset = (page - 1) * limit
    if q or genre or niveau or categorie or saison_id:
        equipes = repo.search_by_name(
            q or "%", genre=genre, niveau=niveau,
            categorie=categorie, saison_id=saison_id, limit=limit,
        )
    else:
        equipes = repo.get_all(limit=limit, offset=offset)
    total = repo.count()
    saisons = saison_repo.get_all(limit=20)
    genres = repo.get_distinct_genres()
    niveaux = repo.get_distinct_niveaux()
    categories = repo.get_distinct_categories()
    return templates.TemplateResponse("equipes/list.html", {
        "request": request, "equipes": equipes, "query": q,
        "page": page, "total": total,
        "has_next": offset + limit < total, "has_prev": page > 1,
        "saisons": saisons, "current_saison_id": saison_id,
        "genre": genre or "", "genres": genres,
        "niveau": niveau or "", "niveaux": niveaux,
        "categorie": categorie or "", "categories": categories,
    })


@web_router.get("/equipes/{equipe_id}", response_class=HTMLResponse)
async def equipe_detail(
    request: Request,
    equipe_id: int,
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    equipe = equipe_repo.get_with_details(equipe_id)
    if not equipe:
        return templates.TemplateResponse("error.html",
            {"request": request, "message": "Équipe non trouvée"}, status_code=404)
    matchs = match_repo.get_by_equipe(equipe_id, limit=200)
    victoires = sum(1 for m in matchs if _is_winner(m, equipe))
    roster = equipe_repo.get_roster(equipe_id)

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

    # Construire les données d'évolution de niveau
    niveau_evolution = _build_niveau_evolution(matchs, equipe)

    # URL FFVB pour l'équipe (planning du club sur le site de l'entité)
    url_ffvb = None
    if (equipe.club and equipe.club.code_ffvb
            and equipe.competition and equipe.competition.entite
            and equipe.saison):
        settings = get_settings()
        # La saison en BDD est "2025-2026", FFVB attend "2025/2026"
        saison_ffvb = equipe.saison.code.replace("-", "/")
        url_ffvb = build_equipe_ffvb_url(
            base_url=settings.ffvb_base_url,
            entity_code=equipe.competition.entite.code,
            saison=saison_ffvb,
            club_code_ffvb=equipe.club.code_ffvb,
        )

    return templates.TemplateResponse("equipes/detail.html", {
        "request": request, "equipe": equipe, "matchs": matchs,
        "victoires": victoires, "defaites": len([m for m in matchs if m.match_joue]) - victoires,
        "roster": roster,
        "sets_gagnes": sets_gagnes, "sets_perdus": sets_perdus,
        "niveau_evolution_json": json.dumps(niveau_evolution, ensure_ascii=False, default=str),
        "url_ffvb": url_ffvb,
    })


# ============== Clubs ==============

@web_router.get("/clubs", response_class=HTMLResponse)
async def clubs_list(
    request: Request,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: ClubRepository = Depends(get_club_repo),
):
    limit = 50
    offset = (page - 1) * limit
    clubs = repo.search_by_name(q, limit=limit) if q else repo.get_all(limit=limit, offset=offset)
    total = repo.count()
    return templates.TemplateResponse("clubs/list.html", {
        "request": request, "clubs": clubs, "query": q,
        "page": page, "total": total,
        "has_next": offset + limit < total, "has_prev": page > 1,
    })


@web_router.get("/clubs/{club_id}", response_class=HTMLResponse)
async def club_detail(
    request: Request,
    club_id: int,
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    club = club_repo.get_with_details(club_id)
    if not club:
        return templates.TemplateResponse("error.html",
            {"request": request, "message": "Club non trouvé"}, status_code=404)
    equipes = equipe_repo.get_by_club(club_id)
    return templates.TemplateResponse("clubs/detail.html", {
        "request": request, "club": club, "equipes": equipes,
    })


# ============== Matchs ==============

@web_router.get("/matchs", response_class=HTMLResponse)
async def matchs_list(
    request: Request,
    page: int = Query(1, ge=1),
    saison_id: Optional[str] = Query(None),
    competition_id: Optional[int] = None,
    departements: Optional[str] = None,
    repo: MatchRepository = Depends(get_match_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
):
    saison_id_int = _parse_optional_int(saison_id)

    # Parse départements (comma-separated codes)
    dept_list = (
        [d.strip() for d in departements.split(',') if d.strip()]
        if departements else None
    )

    limit = 50
    offset = (page - 1) * limit
    matchs = repo.search(
        saison_id=saison_id_int,
        competition_id=competition_id,
        departements=dept_list,
        limit=limit,
    )
    total = repo.count()
    saisons = saison_repo.get_all(limit=20)
    return templates.TemplateResponse("matchs/list.html", {
        "request": request, "matchs": matchs,
        "page": page, "total": total,
        "has_next": offset + limit < total, "has_prev": page > 1,
        "saisons": saisons, "current_saison_id": saison_id_int,
        "selected_departements": dept_list or [],
    })


@web_router.get("/matchs/{match_id}", response_class=HTMLResponse)
async def match_detail(
    request: Request,
    match_id: int,
    repo: MatchRepository = Depends(get_match_repo),
):
    match = repo.get_with_details(match_id)
    if not match:
        return templates.TemplateResponse("error.html",
            {"request": request, "message": "Match non trouvé"}, status_code=404)

    # Séparer les participations par équipe
    participants_a = [p for p in (match.participations or []) if p.equipe_id == match.equipe_a_id]
    participants_b = [p for p in (match.participations or []) if p.equipe_id == match.equipe_b_id]

    # Séparer les officiels par équipe
    officiels_a = [o for o in (match.officiels or []) if o.equipe == "A"]
    officiels_b = [o for o in (match.officiels or []) if o.equipe == "B"]

    # Construire les données de simulation pour l'embarqué
    sim_data = _build_simulation_data(match, participants_a, participants_b, officiels_a, officiels_b)

    # Calculer les statistiques détaillées par joueur
    player_stats_a = []
    player_stats_b = []
    if match.has_details:
        from pyvolley.database.converters import match_db_to_core
        from pyvolley.analysis.joueur_stats import analyze_joueur_match

        match_core = match_db_to_core(match, participants_a, participants_b)
        for p in participants_a:
            if p.joueur:
                s = analyze_joueur_match(match_core, p.joueur.licence)
                if s:
                    player_stats_a.append({"stats": s, "joueur_id": p.joueur_id})
        for p in participants_b:
            if p.joueur:
                s = analyze_joueur_match(match_core, p.joueur.licence)
                if s:
                    player_stats_b.append({"stats": s, "joueur_id": p.joueur_id})

    return templates.TemplateResponse("matchs/detail.html", {
        "request": request, "match": match,
        "participants_a": participants_a, "participants_b": participants_b,
        "officiels_a": officiels_a, "officiels_b": officiels_b,
        "sim_data_json": json.dumps(sim_data, ensure_ascii=False),
        "player_stats_a": player_stats_a,
        "player_stats_b": player_stats_b,
    })


# ============== Arbitres ==============

@web_router.get("/arbitres", response_class=HTMLResponse)
async def arbitres_list(
    request: Request,
    q: Optional[str] = None,
    ligue: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    limit = 50
    offset = (page - 1) * limit
    if q:
        arbitres = repo.search_by_name(q, ligue=ligue, limit=limit)
    else:
        arbitres = repo.get_all(limit=limit, offset=offset)
    total = repo.count()
    ligues = repo.get_distinct_ligues()
    return templates.TemplateResponse("arbitres/list.html", {
        "request": request, "arbitres": arbitres, "query": q,
        "page": page, "total": total,
        "has_next": offset + limit < total, "has_prev": page > 1,
        "ligue": ligue or "", "ligues": ligues,
    })


@web_router.get("/arbitres/{arbitre_id}", response_class=HTMLResponse)
async def arbitre_detail(
    request: Request,
    arbitre_id: int,
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    arbitre = arbitre_repo.get(arbitre_id)
    if not arbitre:
        return templates.TemplateResponse("error.html",
            {"request": request, "message": "Arbitre non trouvé"}, status_code=404)
    stats = arbitre_repo.get_stats(arbitre_id)
    matchs = arbitre_repo.get_matchs(arbitre_id, limit=50)
    return templates.TemplateResponse("arbitres/detail.html", {
        "request": request, "arbitre": arbitre, "stats": stats, "matchs": matchs,
    })


# ============== Compétitions ==============

@web_router.get("/competitions", response_class=HTMLResponse)
async def competitions_list(
    request: Request,
    saison_id: Optional[str] = Query(None),
    genre: Optional[str] = None,
    categorie: Optional[str] = None,
    page: int = Query(1, ge=1),
    repo: CompetitionRepository = Depends(get_competition_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
):
    saison_id_int = _parse_optional_int(saison_id)

    limit = 50
    if saison_id_int:
        competitions = repo.get_by_saison(saison_id_int, genre=genre, categorie=categorie,
                                          exclude_code_only=True)
    else:
        offset = (page - 1) * limit
        competitions = repo.get_all(limit=limit, offset=offset, genre=genre, categorie=categorie,
                                    exclude_code_only=True)
    total = repo.count()
    saisons = saison_repo.get_all(limit=20)
    genres = repo.get_distinct_genres()
    categories = repo.get_distinct_categories()
    return templates.TemplateResponse("competitions/list.html", {
        "request": request, "competitions": competitions, "total": total,
        "page": page, "has_next": False, "has_prev": page > 1,
        "saisons": saisons, "current_saison_id": saison_id_int,
        "genre": genre or "", "genres": genres,
        "categorie": categorie or "", "categories": categories,
    })


@web_router.get("/competitions/{competition_id}", response_class=HTMLResponse)
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
        return templates.TemplateResponse("error.html",
            {"request": request, "message": "Compétition non trouvée"}, status_code=404)

    # Detect youth competition
    from pyvolley.scrapers.ffvb.jeunes import is_youth_competition, get_tour_label
    is_jeunes = is_youth_competition(competition.nom)

    if is_jeunes:
        return await _render_youth_competition(
            request, competition, competition_repo, match_repo, equipe_repo,
        )

    is_multi_poule = competition.poules and len(competition.poules) > 1

    # Classement complet avec évolution
    classement = None
    evolution_json = []
    poules_classements = []

    if is_multi_poule:
        # Multi-poule : classement séparé par poule
        poules_classements_raw = competition_repo.get_classements_par_poule(competition_id)
        poules_classements = []
        for poule, cls in poules_classements_raw:
            evo = [e.model_dump(mode="json") for e in cls.evolution] if cls.evolution else []
            poules_classements.append({
                "poule": poule,
                "classement": cls,
                "evolution_json": evo,
            })
    else:
        # Single poule : classement global
        classement = competition_repo.get_classement(competition_id)
        if classement and classement.evolution:
            evolution_json = [e.model_dump(mode="json") for e in classement.evolution]

    # Matchs de la compétition
    matchs = match_repo.search(competition_id=competition_id, limit=500)

    # Équipes
    equipes = competition_repo.get_equipes_for_competition(competition_id)

    return templates.TemplateResponse("competitions/detail.html", {
        "request": request,
        "competition": competition,
        "classement": classement,
        "evolution_json": evolution_json,
        "poules_classements": poules_classements,
        "is_multi_poule": is_multi_poule,
        "matchs": matchs,
        "equipes": equipes,
    })


def _build_bracket_tree(bracket_matchs_sorted: list) -> dict | None:
    """Build structured bracket tree from 12 sorted matches (3 rounds × 4).

    Returns a dict with upper/lower QF, SF, final, bronze, consolation &
    placement matches, properly mapped by team flow analysis.
    """
    if len(bracket_matchs_sorted) < 12:
        return None

    round1 = bracket_matchs_sorted[0:4]   # QF
    round2 = bracket_matchs_sorted[4:8]   # SF + consolation
    round3 = bracket_matchs_sorted[8:12]  # Finals + placement

    def _winner_loser(m):
        if not m.match_joue:
            return None, None
        sa, sb = (m.sets_equipe_a or 0), (m.sets_equipe_b or 0)
        if sa > sb:
            return m.equipe_a_id, m.equipe_b_id
        return m.equipe_b_id, m.equipe_a_id

    # ── QF results ──
    qf_winners: dict[int, int] = {}   # qf_index → winner_id
    qf_losers: dict[int, int] = {}    # qf_index → loser_id
    for i, m in enumerate(round1):
        w, l = _winner_loser(m)
        if w:
            qf_winners[i] = w
        if l:
            qf_losers[i] = l

    qf_winner_set = set(qf_winners.values())
    qf_loser_set = set(qf_losers.values())

    # ── Classify R2 as SF or consolation ──
    sf_matches: list = []
    consolation_matches: list = []
    for m in round2:
        teams = {m.equipe_a_id, m.equipe_b_id}
        if teams <= qf_winner_set:
            sf_matches.append(m)
        elif teams <= qf_loser_set:
            consolation_matches.append(m)
        else:
            sf_matches.append(m)  # fallback

    # ── Map QF → SF by team tracking ──
    qf_to_sf: dict[int, int] = {}
    for si, sf in enumerate(sf_matches):
        sf_teams = {sf.equipe_a_id, sf.equipe_b_id}
        for qi, wid in qf_winners.items():
            if wid in sf_teams:
                qf_to_sf[qi] = si

    upper_qf_idx = sorted(qi for qi, si in qf_to_sf.items() if si == 0)
    lower_qf_idx = sorted(qi for qi, si in qf_to_sf.items() if si == 1)
    if len(upper_qf_idx) != 2:
        upper_qf_idx, lower_qf_idx = [0, 1], [2, 3]

    # ── Map consolation to QF pairs (by losers) ──
    upper_consolation = lower_consolation = None
    upper_losers = {qf_losers.get(i) for i in upper_qf_idx} - {None}
    lower_losers = {qf_losers.get(i) for i in lower_qf_idx} - {None}
    for c in consolation_matches:
        c_teams = {c.equipe_a_id, c.equipe_b_id}
        if c_teams <= upper_losers:
            upper_consolation = c
        elif c_teams <= lower_losers:
            lower_consolation = c

    # ── Classify R3 by team provenance ──
    sf_w_set, sf_l_set = set(), set()
    for m in sf_matches:
        w, l = _winner_loser(m)
        if w:
            sf_w_set.add(w)
        if l:
            sf_l_set.add(l)

    c_w_set, c_l_set = set(), set()
    for m in consolation_matches:
        w, l = _winner_loser(m)
        if w:
            c_w_set.add(w)
        if l:
            c_l_set.add(l)

    final_match = bronze_match = place_5_6 = place_7_8 = None
    for m in round3:
        teams = {m.equipe_a_id, m.equipe_b_id}
        if teams <= sf_w_set:
            final_match = m
        elif teams <= sf_l_set:
            bronze_match = m
        elif teams <= c_w_set:
            place_5_6 = m
        elif teams <= c_l_set:
            place_7_8 = m

    return {
        "qf_upper": [round1[i] for i in upper_qf_idx],
        "qf_lower": [round1[i] for i in lower_qf_idx],
        "sf_upper": sf_matches[0] if sf_matches else None,
        "sf_lower": sf_matches[1] if len(sf_matches) > 1 else None,
        "final": final_match,
        "bronze": bronze_match,
        "consolation_upper": upper_consolation,
        "consolation_lower": lower_consolation,
        "place_5_6": place_5_6,
        "place_7_8": place_7_8,
    }


def _build_challenge_bracket(cross_poules_data: list) -> dict | None:
    """Build challenge bracket from 2 cross-bracket poules.

    Challenge format: 2 brassage pools of 4 → 2 cross-bracket rounds.
    Round 1 (lower code poule) = 4 semi-finals.
    Round 2 (higher code poule) = 4 placement finals.

    Winners of semis pair up in finals, losers pair up for placement.
    Two mini-brackets result: upper (places 1-4) and lower (places 5-8).

    Returns dict with ``upper`` and ``lower`` mini-brackets, each having
    ``semi1``, ``semi2``, ``final``, ``bronze`` match objects.
    """
    if len(cross_poules_data) != 2:
        return None

    sorted_cross = sorted(cross_poules_data, key=lambda p: p["poule_code"])
    semis_matchs = sorted(sorted_cross[0]["matchs"], key=lambda m: m.code_match or "")
    finals_matchs = sorted(sorted_cross[1]["matchs"], key=lambda m: m.code_match or "")

    def _winner_loser(m):
        if not m.match_joue:
            return None, None
        sa, sb = (m.sets_equipe_a or 0), (m.sets_equipe_b or 0)
        if sa > sb:
            return m.equipe_a_id, m.equipe_b_id
        return m.equipe_b_id, m.equipe_a_id

    # Map semi match → (winner_id, loser_id)
    semi_wl: dict[int, tuple] = {}
    for sm in semis_matchs:
        w, l = _winner_loser(sm)
        semi_wl[sm.id] = (w, l)

    # For each finals match, find which semi matches' WINNERS appear in it
    from collections import defaultdict as _dd
    winner_feeds: dict[int, list] = _dd(list)  # finals.id → [semi match objects]

    for fm in finals_matchs:
        fm_teams = {fm.equipe_a_id, fm.equipe_b_id}
        for sm in semis_matchs:
            w, _ = semi_wl.get(sm.id, (None, None))
            if w and w in fm_teams:
                winner_feeds[fm.id].append(sm)

    # Group: finals matchs pairing two semi-winners vs two semi-losers
    mini_brackets = []
    used_finals: set[int] = set()

    for fm in finals_matchs:
        if fm.id in used_finals:
            continue
        if fm.id in winner_feeds and len(winner_feeds[fm.id]) == 2:
            pair_semis = winner_feeds[fm.id]
            # Find the loser-pair finals match
            pair_losers = set()
            for sm in pair_semis:
                _, l = semi_wl.get(sm.id, (None, None))
                if l:
                    pair_losers.add(l)

            loser_fm = None
            for ofm in finals_matchs:
                if ofm.id != fm.id and ofm.id not in used_finals:
                    ofm_teams = {ofm.equipe_a_id, ofm.equipe_b_id}
                    if ofm_teams <= pair_losers:
                        loser_fm = ofm
                        break

            mini_brackets.append({
                "semi1": pair_semis[0],
                "semi2": pair_semis[1],
                "final": fm,
                "bronze": loser_fm,
            })
            used_finals.add(fm.id)
            if loser_fm:
                used_finals.add(loser_fm.id)

    if len(mini_brackets) != 2:
        return None

    # Higher match code in final = grand final → upper bracket
    mini_brackets.sort(key=lambda mb: mb["final"].code_match or "")

    return {
        "lower": mini_brackets[0],   # places 5-8
        "upper": mini_brackets[1],   # places 1-4
        "semis_poule": sorted_cross[0],
        "finals_poule": sorted_cross[1],
    }


async def _render_youth_competition(
    request: Request,
    competition,
    competition_repo: CompetitionRepository,
    match_repo: MatchRepository,
    equipe_repo: EquipeRepository,
):
    """Render a Coupe de France Jeunes competition with tour-based layout.

    In youth competitions, a single poule code (e.g. "CMA") is reused across
    multiple tours (journées), with completely different sets of 3 teams each
    time. The ``journee`` field on MatchDB IS the actual tour number.

    Builds:
    - Per-tour view grouping matchs by journée
    - Mini-classements per (poule_code, journée) from round-robin of 3 teams
    - Finals data (journée "99") with bracket + ranking
    """
    from collections import defaultdict
    from dataclasses import dataclass as _dc
    from pyvolley.analysis.classement import MatchData, calculer_classement

    competition_id = competition.id

    # ── 1. Fetch all matchs with their poule eagerly loaded ──
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

        # Group matchs by poule code within this tour
        matchs_by_poule: dict[str, list] = defaultdict(list)
        poule_id_map: dict[str, int] = {}  # poule_code -> poule_id
        for m in tour_matchs:
            poule_code = m.poule.code if m.poule else "???"
            matchs_by_poule[poule_code].append(m)
            if m.poule and poule_code not in poule_id_map:
                poule_id_map[poule_code] = m.poule.id

        # Count unique teams in this tour
        tour_equipe_ids = set()
        for m in tour_matchs:
            if m.equipe_a_id:
                tour_equipe_ids.add(m.equipe_a_id)
            if m.equipe_b_id:
                tour_equipe_ids.add(m.equipe_b_id)

        # Compute mini-classement for each poule in this tour
        poule_classements = []
        for poule_code in sorted(matchs_by_poule.keys()):
            poule_matchs = matchs_by_poule[poule_code]
            # Convert to MatchData for classement calculation
            match_data_list = []
            for m in poule_matchs:
                if m.match_joue and (m.sets_equipe_a or 0) + (m.sets_equipe_b or 0) > 0:
                    match_data_list.append(MatchData(
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
                    ))
            if match_data_list:
                cls_lines = calculer_classement(match_data_list)
                poule_classements.append({
                    "poule_code": poule_code,
                    "poule_id": poule_id_map.get(poule_code),
                    "classement": cls_lines,
                    "matchs": poule_matchs,
                    "nb_equipes": len({m.equipe_a_id for m in poule_matchs}
                                      | {m.equipe_b_id for m in poule_matchs}),
                })

        # Label
        if tour_num == 99:
            label = "Phases finales"
        else:
            label = f"Tour {tour_num}"

        tours_data.append({
            "tour_num": tour_num,
            "label": label,
            "poule_classements": poule_classements,
            "nb_poules": len(matchs_by_poule),
            "nb_equipes": len(tour_equipe_ids),
            "nb_matchs": len(tour_matchs),
            "nb_matchs_joues": sum(1 for m in tour_matchs if m.match_joue),
            "matchs": tour_matchs,
        })

    # ── 4. Separate finals (J99) from qualifying tours ──
    finals_tour = None
    qualifying_tours = []

    for td in tours_data:
        if td["tour_num"] == 99:
            finals_tour = td
        else:
            qualifying_tours.append(td)

    # ── 5. Build finals aggregate classement ──
    finals_classement = None
    finals_bracket_matchs = []
    finals_pool_classements = []
    finals_format = "none"
    bracket_8 = None
    bracket_tree = None
    classement_9_12 = None
    challenge_bracket = None
    challenge_pools = []

    if finals_tour:
        # ── Classify finals poules by structure ──
        brassage_pools = []    # Small round-robin (3 teams / 3 matchs)
        pools_4_teams = []     # Round-robin of 4 (6 matchs)
        bracket_poules = []    # Full bracket (≥10 matchs, ≥7 teams)
        cross_poules = []      # Cross-bracket rounds (more teams than matchs)

        for pc in finals_tour["poule_classements"]:
            nb_eq = pc["nb_equipes"]
            nb_matchs = len(pc["matchs"])

            if nb_eq > nb_matchs:
                # More teams than matches → cross-bracket round
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
            # In standard format, 4-team/6-match pools are classement 9-12
            classement_9_12 = pools_4_teams[0] if pools_4_teams else None
            finals_pool_classements = brassage_pools
        elif cross_poules:
            finals_format = "challenge"
            # In challenge format, 4-team pools are brassage
            challenge_pools = pools_4_teams
            finals_pool_classements = []
        else:
            finals_format = "simple"
            finals_pool_classements = brassage_pools + pools_4_teams

        # ═══════════ STANDARD FORMAT (CdF): bracket + classement 9-12 ═══════════
        bracket_classement = []
        if finals_format == "standard" and bracket_8:
            finals_bracket_matchs = bracket_8["matchs"]
            bracket_cls = bracket_8["classement"]

            bracket_matchs_sorted = sorted(
                finals_bracket_matchs, key=lambda m: m.code_match or ""
            )

            bracket_tree = _build_bracket_tree(bracket_matchs_sorted)

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

        # ═══════════ CHALLENGE FORMAT: pools + cross-brackets ═══════════
        elif finals_format == "challenge" and cross_poules:
            challenge_bracket = _build_challenge_bracket(cross_poules)

            if challenge_bracket:
                # Compute classement across ALL finals matches
                all_finals_matchs = finals_tour["matchs"]
                match_data_list = []
                for m in all_finals_matchs:
                    if m.match_joue and (
                        (m.sets_equipe_a or 0) + (m.sets_equipe_b or 0) > 0
                    ):
                        match_data_list.append(MatchData(
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
                        ))

                if match_data_list:
                    all_cls = calculer_classement(match_data_list)
                    cls_by_id = {e.equipe_id: e for e in all_cls}

                    # Derive placement from bracket results
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

    # ── 6. All equipes ──
    equipes = competition_repo.get_equipes_for_competition(competition_id)

    return templates.TemplateResponse("competitions/detail_jeunes.html", {
        "request": request,
        "competition": competition,
        "tours_data": tours_data,
        "qualifying_tours": qualifying_tours,
        "finals_tour": finals_tour,
        "finals_format": finals_format,
        "finals_classement": finals_classement,
        "finals_bracket_matchs": finals_bracket_matchs,
        "finals_pool_classements": finals_pool_classements,
        "classement_9_12": classement_9_12 if finals_format == "standard" else None,
        "bracket_8": bracket_8 if finals_format == "standard" else None,
        "bracket_tree": bracket_tree,
        "challenge_bracket": challenge_bracket,
        "challenge_pools": challenge_pools,
        "matchs": all_matchs,
        "equipes": equipes,
        "is_youth": True,
    })


@web_router.get("/poules/{poule_id}", response_class=HTMLResponse)
async def poule_detail(
    request: Request,
    poule_id: int,
    poule_repo: PouleRepository = Depends(get_poule_repo),
    competition_repo: CompetitionRepository = Depends(get_competition_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Page de détail d'une poule, vue comme compétition à part entière.

    Chaque poule d'une compétition multi-poule a ses propres classement,
    évolution, matchs et statistiques.
    """
    poule = poule_repo.get_with_details(poule_id)
    if not poule:
        return templates.TemplateResponse("error.html",
            {"request": request, "message": "Poule non trouvée"}, status_code=404)

    competition = poule.competition

    # Detect youth competition (single-day "plateaux" — no evolution needed)
    from pyvolley.scrapers.ffvb.jeunes import is_youth_competition
    is_youth = is_youth_competition(competition.nom) if competition else False

    # Classement spécifique à cette poule
    classement = competition_repo.get_classement_for_poule(poule_id)
    evolution_json = []
    if not is_youth and classement and classement.evolution:
        evolution_json = [e.model_dump(mode="json") for e in classement.evolution]

    # Matchs de la poule uniquement
    matchs = match_repo.search(competition_id=competition.id, limit=500)
    matchs = [m for m in matchs if m.poule_id == poule_id]

    # Équipes de la poule (déduites des matchs)
    equipe_ids = set()
    for m in matchs:
        if m.equipe_a_id:
            equipe_ids.add(m.equipe_a_id)
        if m.equipe_b_id:
            equipe_ids.add(m.equipe_b_id)

    # Poules sœurs (autres poules de la même compétition)
    sibling_poules = sorted(
        [p for p in competition.poules if p.id != poule_id],
        key=lambda p: p.code,
    )

    return templates.TemplateResponse("poules/detail.html", {
        "request": request,
        "poule": poule,
        "competition": competition,
        "classement": classement,
        "evolution_json": evolution_json,
        "matchs": matchs,
        "nb_equipes": len(equipe_ids),
        "sibling_poules": sibling_poules,
        "is_youth": is_youth,
    })


# ============== Statistiques ==============

@web_router.get("/statistiques", response_class=HTMLResponse)
async def stats_page(
    request: Request,
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
    competition_repo: CompetitionRepository = Depends(get_competition_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    stats = {
        "matchs": match_repo.count(),
        "joueurs": joueur_repo.count(),
        "clubs": club_repo.count(),
        "equipes": equipe_repo.count(),
        "arbitres": arbitre_repo.count(),
        "competitions": competition_repo.count(),
    }
    matchs_par_saison = match_repo.count_by_saison()
    matchs_par_mois = match_repo.get_stats_by_month()
    saisons = saison_repo.get_all(limit=20)

    return templates.TemplateResponse("statistiques.html", {
        "request": request, "stats": stats,
        "matchs_par_saison": [
            {"saison": code, "count": count} for code, count in matchs_par_saison
        ],
        "matchs_par_mois": [
            {"year": int(y), "month": int(m), "count": c}
            for y, m, c in matchs_par_mois
        ],
        "saisons": saisons,
    })


# ============== Palmarès / Stats amusantes ==============

@web_router.get("/palmares", response_class=HTMLResponse)
async def palmares_page(
    request: Request,
    saison_id: Optional[int] = Query(None),
    genre: Optional[str] = Query(None),
    categorie: Optional[str] = Query(None),
    niveau_min: Optional[str] = Query(None),
    niveau_max: Optional[str] = Query(None),
    departement: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from pyvolley.database.stats_service import StatsAmusantesService, StatsFilters

    service = StatsAmusantesService(session)
    filters = StatsFilters(
        saison_id=saison_id,
        genre=genre,
        categorie=categorie,
        niveau_min=niveau_min,
        niveau_max=niveau_max,
        departement=departement,
    )

    all_stats = service.get_all_stats(filters)
    filter_options = service.get_filter_options()

    return templates.TemplateResponse("palmares.html", {
        "request": request,
        **all_stats,
        "filter_options": filter_options,
        "current_filters": {
            "saison_id": saison_id,
            "genre": genre or "",
            "categorie": categorie or "",
            "niveau_min": niveau_min or "",
            "niveau_max": niveau_max or "",
            "departement": departement or "",
        },
    })


# ============== Helpers ==============

def _is_winner(match, equipe) -> bool:
    if match.equipe_a_id == equipe.id:
        return match.sets_equipe_a > match.sets_equipe_b
    elif match.equipe_b_id == equipe.id:
        return match.sets_equipe_b > match.sets_equipe_a
    return False


def _build_simulation_data(match, participants_a, participants_b, officiels_a, officiels_b) -> dict:
    """Construit les données JSON pour le visualiseur de simulation embarqué."""
    equipe_a_name = match.equipe_a.nom if match.equipe_a else "Équipe A"
    equipe_b_name = match.equipe_b.nom if match.equipe_b else "Équipe B"

    # Joueurs
    joueurs_a = []
    for p in participants_a:
        joueurs_a.append({
            "numero": p.numero_maillot or "?",
            "nom": p.joueur.nom if p.joueur else "?",
            "prenom": p.joueur.prenom if p.joueur else "",
            "est_capitaine": p.est_capitaine,
            "est_libero": p.est_libero,
        })

    joueurs_b = []
    for p in participants_b:
        joueurs_b.append({
            "numero": p.numero_maillot or "?",
            "nom": p.joueur.nom if p.joueur else "?",
            "prenom": p.joueur.prenom if p.joueur else "",
            "est_capitaine": p.est_capitaine,
            "est_libero": p.est_libero,
        })

    # Officiels
    off_a = [{"role": o.role, "nom": o.nom, "prenom": o.prenom} for o in officiels_a]
    off_b = [{"role": o.role, "nom": o.nom, "prenom": o.prenom} for o in officiels_b]

    # Arbitres
    arbitres = []
    for am in (match.arbitrages or []):
        arbitres.append({
            "nom": am.arbitre.nom if am.arbitre else "?",
            "prenom": am.arbitre.prenom if am.arbitre else "",
            "role": am.role,
        })

    # Sets
    sets_data = []
    for s in (match.sets or []):
        set_entry = {
            "numero": s.numero,
            "score_a": s.score_a or 0,
            "score_b": s.score_b or 0,
            "heure_debut": s.heure_debut,
            "heure_fin": s.heure_fin,
            "duree_minutes": s.duree_minutes,
            "service_initial": s.service_initial,
            "formation_a": {},
            "formation_b": {},
            "changements_a": [],
            "changements_b": [],
            "timeouts_a": [],
            "timeouts_b": [],
        }

        # Formations
        for f in (s.formations or []):
            key = f"formation_{f.equipe.lower()}"
            set_entry[key] = {
                "position_1": f.position_1 or "",
                "position_2": f.position_2 or "",
                "position_3": f.position_3 or "",
                "position_4": f.position_4 or "",
                "position_5": f.position_5 or "",
                "position_6": f.position_6 or "",
            }

        # Changements
        for c in (s.changements or []):
            entry = {
                "joueur_entrant": c.joueur_entrant,
                "joueur_sortant": c.joueur_sortant,
                "position": c.position,
                "score_a": c.score_a,
                "score_b": c.score_b,
            }
            if c.equipe == "A":
                set_entry["changements_a"].append(entry)
            else:
                set_entry["changements_b"].append(entry)

        # Timeouts
        for t in (s.timeouts or []):
            entry = {"score_a": t.score_a, "score_b": t.score_b}
            if t.equipe == "A":
                set_entry["timeouts_a"].append(entry)
            else:
                set_entry["timeouts_b"].append(entry)

        sets_data.append(set_entry)

    # Sanctions
    sanctions = []
    for s in (match.sanctions or []):
        sanctions.append({
            "type": s.type_sanction,
            "equipe": s.equipe,
            "set_numero": s.set_numero,
            "joueur_numero": s.joueur_numero,
            "score_a": s.score_a,
            "score_b": s.score_b,
        })

    return {
        "code_match": match.code_match,
        "date": str(match.date_match) if match.date_match else "",
        "lieu": match.salle or "",
        "salle": match.salle or "",
        "competition": match.competition.nom if match.competition else "",
        "journee": match.journee or "",
        "duree_totale": match.duree_totale or "",
        "equipe_a": {"nom": equipe_a_name, "joueurs": joueurs_a, "officiels": off_a},
        "equipe_b": {"nom": equipe_b_name, "joueurs": joueurs_b, "officiels": off_b},
        "sets_a": match.sets_equipe_a,
        "sets_b": match.sets_equipe_b,
        "vainqueur": match.vainqueur or "",
        "sets": sets_data,
        "arbitres": arbitres,
        "sanctions": sanctions,
    }


# Hiérarchie des niveaux de volley (du plus bas au plus haut)
_NIVEAU_ORDER = {
    "LOISIR": 0,
    "DEPARTEMENTAL": 1, "DÉPARTEMENTAL": 1, "DEPARTEMENTALE": 1, "DÉPARTEMENTALE": 1,
    "PRE_REGIONALE": 2, "PRÉ_RÉGIONALE": 2, "PREREGIONALE": 2,
    "REGIONAL": 3, "RÉGIONAL": 3, "REGIONALE": 3, "RÉGIONALE": 3,
    "PRE_NATIONALE": 4, "PRÉNATIONAL": 4, "PRENATIONAL": 4,
    "PRENATIONALE": 4, "PRÉNATIONALE": 4,
    "PRE-NATIONAL": 4, "PRÉ-NATIONAL": 4, "PRE-NATIONALE": 4, "PRÉ-NATIONALE": 4,
    "NATIONAL": 5, "NATIONALE": 5,
    "N3": 5, "N2": 6, "N1": 7,
    "ELITE": 8, "ÉLITE": 8,
    "PRO": 9, "PRO B": 9, "PRO A": 10,
}


def _niveau_rank(niveau_str: Optional[str]) -> Optional[int]:
    """Retourne le rang numérique d'un niveau, ou None si inconnu."""
    if not niveau_str:
        return None
    return _NIVEAU_ORDER.get(niveau_str.upper().strip())


def _build_niveau_evolution(matchs, equipe) -> list:
    """Construit les données d'évolution du niveau pour le graphique.

    Pour chaque match joué, on regarde la compétition / le niveau de l'équipe
    au moment du match. Cela permet de tracer l'évolution temporelle.

    Retourne une liste triée par date avec :
    - date: date du match
    - niveau: nom du niveau
    - niveau_rank: rang numérique pour l'axe Y
    - adversaire: nom de l'adversaire
    - resultat: 'V' ou 'D'
    - score: 'X-Y'
    - match_id: id du match
    - competition: nom de la compétition
    """
    points = []
    for m in matchs:
        if not m.match_joue or not m.date_match:
            continue

        # Déterminer le niveau de la compétition du match
        niveau = None
        if m.competition:
            niveau = m.competition.niveau
        # Sinon essayer via l'équipe elle-même
        if not niveau and equipe.niveau:
            niveau = equipe.niveau

        rank = _niveau_rank(niveau)
        if rank is None and niveau:
            # Niveau inconnu mais existant : lui donner un rang par défaut
            rank = 2  # régional par défaut

        is_team_a = m.equipe_a_id == equipe.id
        opponent = m.equipe_b if is_team_a else m.equipe_a
        won = (is_team_a and m.sets_equipe_a > m.sets_equipe_b) or \
              (not is_team_a and m.sets_equipe_b > m.sets_equipe_a)

        if is_team_a:
            score = f"{m.sets_equipe_a}-{m.sets_equipe_b}"
        else:
            score = f"{m.sets_equipe_b}-{m.sets_equipe_a}"

        points.append({
            "date": str(m.date_match),
            "niveau": niveau or "Inconnu",
            "niveau_rank": rank if rank is not None else 2,
            "adversaire": opponent.nom if opponent else "?",
            "resultat": "V" if won else "D",
            "score": score,
            "match_id": m.id,
            "competition": m.competition.nom if m.competition else "",
        })

    # Trier par date
    points.sort(key=lambda p: p["date"])
    return points
