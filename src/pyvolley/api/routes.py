"""
Routes API pour PyVolley.
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query

from pyvolley.api.dependencies import (
    get_joueur_repo,
    get_club_repo,
    get_equipe_repo,
    get_match_repo,
    get_saison_repo,
    get_competition_repo,
    get_arbitre_repo,
)
from pyvolley.api.schemas import (
    JoueurResponse,
    JoueurDetail,
    ClubResponse,
    ClubDetail,
    EquipeResponse,
    EquipeDetail,
    ArbitreResponse,
    ArbitreDetail,
    SaisonResponse,
    CompetitionResponse,
    CompetitionDetail,
    MatchResponse,
    MatchDetail,
    SetDetailResponse,
    FormationResponse,
    ChangementResponse,
    TimeoutResponse,
    ParticipationResponse,
    ArbitreMatchResponse,
    OfficielResponse,
    SanctionResponse,
    SearchResult,
    StatsOverview,
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


router = APIRouter()


# ============== Santé ==============

@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "pyvolley-api"}


# ============== Recherche globale ==============

@router.get("/search", response_model=SearchResult)
async def search(
    q: str = Query(..., min_length=2, description="Terme de recherche"),
    limit: int = Query(10, ge=1, le=50),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    """Recherche globale dans joueurs, clubs, équipes et arbitres."""
    joueurs = joueur_repo.search_by_name(q, limit=limit)
    clubs = club_repo.search_by_name(q, limit=limit)
    equipes = equipe_repo.search_by_name(q, limit=limit)
    arbitres = arbitre_repo.search_by_name(q, limit=limit)

    return SearchResult(
        joueurs=[JoueurResponse.model_validate(j) for j in joueurs],
        clubs=[ClubResponse.model_validate(c) for c in clubs],
        equipes=[EquipeResponse.model_validate(e) for e in equipes],
        arbitres=[ArbitreResponse.model_validate(a) for a in arbitres],
        total=len(joueurs) + len(clubs) + len(equipes) + len(arbitres),
    )


# ============== Joueurs ==============

@router.get("/joueurs", response_model=List[JoueurResponse])
async def list_joueurs(
    q: Optional[str] = Query(None, min_length=2),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: JoueurRepository = Depends(get_joueur_repo),
):
    if q:
        joueurs = repo.search_by_name(q, limit=limit)
    else:
        joueurs = repo.get_all(limit=limit, offset=offset)
    return [JoueurResponse.model_validate(j) for j in joueurs]


@router.get("/joueurs/{joueur_id}", response_model=JoueurDetail)
async def get_joueur(
    joueur_id: int,
    repo: JoueurRepository = Depends(get_joueur_repo),
):
    joueur = repo.get(joueur_id)
    if not joueur:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")
    stats = repo.get_stats(joueur_id)
    return JoueurDetail(
        id=joueur.id,
        licence=joueur.licence,
        nom=joueur.nom,
        prenom=joueur.prenom,
        matchs_joues=stats.get("matchs_joues", 0),
        equipes=stats.get("equipes", []),
        saisons=stats.get("saisons", []),
        capitaine_count=stats.get("capitaine_count", 0),
        libero_count=stats.get("libero_count", 0),
    )


@router.get("/joueurs/{joueur_id}/matchs", response_model=List[MatchResponse])
async def get_joueur_matchs(
    joueur_id: int,
    limit: int = Query(50, ge=1, le=200),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    joueur = joueur_repo.get(joueur_id)
    if not joueur:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")
    matchs = match_repo.get_by_joueur(joueur_id, limit=limit)
    return [_match_to_response(m) for m in matchs]


@router.get("/joueurs/{joueur_id}/matchs/{match_id}/stats")
async def get_joueur_match_stats(
    joueur_id: int,
    match_id: int,
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
):
    stats = joueur_repo.get_match_stats(joueur_id, match_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Participation non trouvée")
    return {
        "joueur_id": joueur_id,
        "match_id": match_id,
        "side": stats["side"],
        "numero_maillot": stats["numero_maillot"],
        "est_capitaine": stats["est_capitaine"],
        "est_libero": stats["est_libero"],
        "sets_titulaire": stats["sets_titulaire"],
        "sets_entrant": stats["sets_entrant"],
    }


# ============== Clubs ==============

@router.get("/clubs", response_model=List[ClubResponse])
async def list_clubs(
    q: Optional[str] = Query(None, min_length=2),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: ClubRepository = Depends(get_club_repo),
):
    if q:
        clubs = repo.search_by_name(q, limit=limit)
    else:
        clubs = repo.get_all(limit=limit, offset=offset)
    return [ClubResponse.model_validate(c) for c in clubs]


@router.get("/clubs/{club_id}", response_model=ClubDetail)
async def get_club(
    club_id: int,
    repo: ClubRepository = Depends(get_club_repo),
):
    club = repo.get(club_id)
    if not club:
        raise HTTPException(status_code=404, detail="Club non trouvé")
    return ClubDetail(
        id=club.id,
        nom=club.nom,
        nom_court=club.nom_court,
        ville=club.ville,
        departement=club.departement,
        code_ffvb=club.code_ffvb,
        equipes_count=len(club.equipes) if club.equipes else 0,
    )


# ============== Équipes ==============

@router.get("/equipes", response_model=List[EquipeResponse])
async def list_equipes(
    q: Optional[str] = Query(None, min_length=2),
    club_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: EquipeRepository = Depends(get_equipe_repo),
):
    if q:
        equipes = repo.search_by_name(q, limit=limit)
    elif club_id:
        equipes = repo.get_by_club(club_id)
    else:
        equipes = repo.get_all(limit=limit, offset=offset)
    return [EquipeResponse.model_validate(e) for e in equipes]


@router.get("/equipes/{equipe_id}", response_model=EquipeDetail)
async def get_equipe(
    equipe_id: int,
    repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    equipe = repo.get(equipe_id)
    if not equipe:
        raise HTTPException(status_code=404, detail="Équipe non trouvée")
    matchs = match_repo.get_by_equipe(equipe_id, limit=200)
    victoires = sum(1 for m in matchs if _is_winner(m, equipe))
    return EquipeDetail(
        id=equipe.id,
        nom=equipe.nom,
        club_id=equipe.club_id,
        genre=equipe.genre,
        categorie=equipe.categorie,
        club_nom=equipe.club.nom if equipe.club else None,
        saison_code=equipe.saison.code if equipe.saison else None,
        matchs_count=len(matchs),
        victoires=victoires,
        defaites=len(matchs) - victoires,
    )


@router.get("/equipes/{equipe_id}/matchs", response_model=List[MatchResponse])
async def get_equipe_matchs(
    equipe_id: int,
    limit: int = Query(50, ge=1, le=200),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    equipe = equipe_repo.get(equipe_id)
    if not equipe:
        raise HTTPException(status_code=404, detail="Équipe non trouvée")
    matchs = match_repo.get_by_equipe(equipe_id, limit=limit)
    return [_match_to_response(m) for m in matchs]


# ============== Arbitres ==============

@router.get("/arbitres", response_model=List[ArbitreResponse])
async def list_arbitres(
    q: Optional[str] = Query(None, min_length=2),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    if q:
        arbitres = repo.search_by_name(q, limit=limit)
    else:
        arbitres = repo.get_all(limit=limit, offset=offset)
    return [ArbitreResponse.model_validate(a) for a in arbitres]


@router.get("/arbitres/{arbitre_id}", response_model=ArbitreDetail)
async def get_arbitre(
    arbitre_id: int,
    repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    arbitre = repo.get(arbitre_id)
    if not arbitre:
        raise HTTPException(status_code=404, detail="Arbitre non trouvé")
    stats = repo.get_stats(arbitre_id)
    return ArbitreDetail(
        id=arbitre.id,
        nom=arbitre.nom,
        prenom=arbitre.prenom,
        licence=arbitre.licence,
        ligue=arbitre.ligue,
        matchs_count=stats.get("matchs_count", 0),
        roles=stats.get("roles", {}),
    )


@router.get("/arbitres/{arbitre_id}/matchs", response_model=List[MatchResponse])
async def get_arbitre_matchs(
    arbitre_id: int,
    limit: int = Query(50, ge=1, le=200),
    repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    arbitre = repo.get(arbitre_id)
    if not arbitre:
        raise HTTPException(status_code=404, detail="Arbitre non trouvé")
    matchs = repo.get_matchs(arbitre_id, limit=limit)
    return [_match_to_response(m) for m in matchs]


# ============== Saisons ==============

@router.get("/saisons", response_model=List[SaisonResponse])
async def list_saisons(
    repo: SaisonRepository = Depends(get_saison_repo),
):
    saisons = repo.get_all(limit=50)
    return [SaisonResponse.model_validate(s) for s in saisons]


# ============== Compétitions ==============

@router.get("/competitions", response_model=List[CompetitionResponse])
async def list_competitions(
    q: Optional[str] = Query(None, min_length=2),
    saison_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    repo: CompetitionRepository = Depends(get_competition_repo),
):
    if q:
        competitions = repo.search_by_name(q, limit=limit)
    elif saison_id:
        competitions = repo.get_by_saison(saison_id)
    else:
        competitions = repo.get_all(limit=limit)
    return [CompetitionResponse.model_validate(c) for c in competitions]


# ============== Matchs ==============

@router.get("/matchs", response_model=List[MatchResponse])
async def list_matchs(
    competition_id: Optional[int] = None,
    saison_id: Optional[int] = None,
    equipe_nom: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: MatchRepository = Depends(get_match_repo),
):
    matchs = repo.search(
        competition_id=competition_id,
        saison_id=saison_id,
        equipe_nom=equipe_nom,
        limit=limit,
    )
    return [_match_to_response(m) for m in matchs]


@router.get("/matchs/{match_id}", response_model=MatchDetail)
async def get_match(
    match_id: int,
    repo: MatchRepository = Depends(get_match_repo),
):
    match = repo.get_with_details(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match non trouvé")
    return _match_to_detail(match)


# ============== Statistiques ==============

@router.get("/stats", response_model=StatsOverview)
async def get_stats(
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
    competition_repo: CompetitionRepository = Depends(get_competition_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
):
    saisons = saison_repo.get_all(limit=50)
    matchs_par_saison_raw = match_repo.count_by_saison()
    matchs_par_mois_raw = match_repo.get_stats_by_month()

    return StatsOverview(
        total_matchs=match_repo.count(),
        total_joueurs=joueur_repo.count(),
        total_clubs=club_repo.count(),
        total_equipes=equipe_repo.count(),
        total_arbitres=arbitre_repo.count(),
        total_competitions=competition_repo.count(),
        saisons=[s.code for s in saisons],
        matchs_par_saison={code: count for code, count in matchs_par_saison_raw},
        matchs_par_mois=[
            {"year": int(y), "month": int(m), "count": c}
            for y, m, c in matchs_par_mois_raw
        ],
    )


# ============== Helpers ==============

def _match_to_response(m) -> MatchResponse:
    return MatchResponse(
        id=m.id,
        code_match=m.code_match,
        date=m.date_match,
        heure=m.heure_match,
        lieu=m.lieu,
        equipe_a_nom=m.equipe_a.nom if m.equipe_a else "???",
        equipe_b_nom=m.equipe_b.nom if m.equipe_b else "???",
        score_sets=m.score_sets,
        sets_equipe_a=m.sets_equipe_a,
        sets_equipe_b=m.sets_equipe_b,
        vainqueur=m.vainqueur,
        has_details=m.has_details,
    )


def _match_to_detail(match) -> MatchDetail:
    sets_detail = []
    for s in (match.sets or []):
        formations = [
            FormationResponse(
                equipe=f.equipe,
                position_1=f.position_1, position_2=f.position_2,
                position_3=f.position_3, position_4=f.position_4,
                position_5=f.position_5, position_6=f.position_6,
            )
            for f in (s.formations or [])
        ]
        changements = [
            ChangementResponse(
                equipe=c.equipe,
                joueur_entrant=c.joueur_entrant,
                joueur_sortant=c.joueur_sortant,
                position=c.position,
                score_a=c.score_a, score_b=c.score_b,
            )
            for c in (s.changements or [])
        ]
        timeouts = [
            TimeoutResponse(equipe=t.equipe, score_a=t.score_a, score_b=t.score_b)
            for t in (s.timeouts or [])
        ]
        sets_detail.append(SetDetailResponse(
            numero=s.numero,
            score_a=s.score_a or 0,
            score_b=s.score_b or 0,
            heure_debut=s.heure_debut,
            heure_fin=s.heure_fin,
            duree_minutes=s.duree_minutes,
            service_initial=s.service_initial,
            formations=formations,
            changements=changements,
            timeouts=timeouts,
        ))

    participations = [
        ParticipationResponse(
            joueur_id=p.joueur.id,
            joueur_nom=p.joueur.nom,
            joueur_prenom=p.joueur.prenom,
            joueur_licence=p.joueur.licence,
            equipe_nom=p.equipe.nom if p.equipe else "",
            equipe_id=p.equipe_id,
            numero_maillot=p.numero_maillot,
            est_capitaine=p.est_capitaine,
            est_libero=p.est_libero,
        )
        for p in (match.participations or [])
    ]

    arbitres_match = [
        ArbitreMatchResponse(
            arbitre_id=am.arbitre.id,
            nom=am.arbitre.nom,
            prenom=am.arbitre.prenom,
            role=am.role,
        )
        for am in (match.arbitrages or [])
    ]

    officiels = [
        OfficielResponse(
            role=o.role, nom=o.nom, prenom=o.prenom,
            licence=o.licence, equipe=o.equipe,
        )
        for o in (match.officiels or [])
    ]

    sanctions = [
        SanctionResponse(
            type_sanction=s.type_sanction,
            set_numero=s.set_numero,
            equipe=s.equipe,
            joueur_numero=s.joueur_numero,
            score_a=s.score_a, score_b=s.score_b,
        )
        for s in (match.sanctions or [])
    ]

    return MatchDetail(
        id=match.id,
        code_match=match.code_match,
        date=match.date_match,
        heure=match.heure_match,
        lieu=match.lieu,
        salle=match.salle,
        equipe_a_nom=match.equipe_a.nom if match.equipe_a else "???",
        equipe_b_nom=match.equipe_b.nom if match.equipe_b else "???",
        equipe_a_id=match.equipe_a_id,
        equipe_b_id=match.equipe_b_id,
        score_sets=match.score_sets,
        sets_equipe_a=match.sets_equipe_a,
        sets_equipe_b=match.sets_equipe_b,
        vainqueur=match.vainqueur,
        has_details=match.has_details,
        competition_nom=match.competition.nom if match.competition else None,
        saison_code=match.saison.code if match.saison else None,
        journee=match.journee,
        duree_totale=match.duree_totale,
        remarques=match.remarques,
        sets=sets_detail,
        participations=participations,
        arbitres=arbitres_match,
        officiels=officiels,
        sanctions=sanctions,
    )


def _is_winner(match, equipe) -> bool:
    if match.equipe_a_id == equipe.id:
        return match.sets_equipe_a > match.sets_equipe_b
    elif match.equipe_b_id == equipe.id:
        return match.sets_equipe_b > match.sets_equipe_a
    return False
