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
)


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
    return templates.TemplateResponse("joueurs/detail.html", {
        "request": request, "joueur": joueur, "matchs": matchs,
        "stats": stats, "detailed_stats": detailed_stats,
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

    return templates.TemplateResponse("equipes/detail.html", {
        "request": request, "equipe": equipe, "matchs": matchs,
        "victoires": victoires, "defaites": len([m for m in matchs if m.match_joue]) - victoires,
        "roster": roster,
        "sets_gagnes": sets_gagnes, "sets_perdus": sets_perdus,
        "niveau_evolution_json": json.dumps(niveau_evolution, ensure_ascii=False, default=str),
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
    club = club_repo.get(club_id)
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

    return templates.TemplateResponse("matchs/detail.html", {
        "request": request, "match": match,
        "participants_a": participants_a, "participants_b": participants_b,
        "officiels_a": officiels_a, "officiels_b": officiels_b,
        "sim_data_json": json.dumps(sim_data, ensure_ascii=False),
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
        competitions = repo.get_by_saison(saison_id_int, genre=genre, categorie=categorie)
    else:
        offset = (page - 1) * limit
        competitions = repo.get_all(limit=limit, offset=offset, genre=genre, categorie=categorie)
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

    # Classement complet avec évolution
    classement = competition_repo.get_classement(competition_id)
    evolution_json = []
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
        "matchs": matchs,
        "equipes": equipes,
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
    "REGIONAL": 2, "RÉGIONAL": 2, "REGIONALE": 2, "RÉGIONALE": 2,
    "PRENATIONAL": 3, "PRÉNATIONAL": 3, "PRENATIONALE": 3, "PRÉNATIONALE": 3,
    "PRE-NATIONAL": 3, "PRÉ-NATIONAL": 3, "PRE-NATIONALE": 3, "PRÉ-NATIONALE": 3,
    "NATIONAL": 4, "NATIONALE": 4,
    "ELITE": 5, "ÉLITE": 5,
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
