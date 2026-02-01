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
)
from pyvolley.api.schemas import (
    JoueurResponse,
    JoueurDetail,
    ClubResponse,
    ClubDetail,
    EquipeResponse,
    EquipeDetail,
    MatchResponse,
    MatchDetail,
    SearchResult,
    StatsOverview,
)
from pyvolley.database.repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    MatchRepository,
)


router = APIRouter()


# ============== Santé ==============

@router.get("/health")
async def health_check():
    """Vérifie que l'API est opérationnelle."""
    return {"status": "ok", "service": "pyvolley-api"}


# ============== Recherche globale ==============

@router.get("/search", response_model=SearchResult)
async def search(
    q: str = Query(..., min_length=2, description="Terme de recherche"),
    limit: int = Query(10, ge=1, le=50),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
):
    """
    Recherche globale dans joueurs, clubs et équipes.
    """
    joueurs = joueur_repo.search_by_name(q, limit=limit)
    clubs = club_repo.search_by_name(q, limit=limit)
    equipes = equipe_repo.search_by_name(q, limit=limit)
    
    return SearchResult(
        joueurs=[JoueurResponse.model_validate(j) for j in joueurs],
        clubs=[ClubResponse.model_validate(c) for c in clubs],
        equipes=[EquipeResponse.model_validate(e) for e in equipes],
        total=len(joueurs) + len(clubs) + len(equipes),
    )


# ============== Joueurs ==============

@router.get("/joueurs", response_model=List[JoueurResponse])
async def list_joueurs(
    q: Optional[str] = Query(None, min_length=2),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: JoueurRepository = Depends(get_joueur_repo),
):
    """Liste les joueurs avec recherche optionnelle."""
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
    """Récupère les détails d'un joueur."""
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
    )


@router.get("/joueurs/{joueur_id}/matchs", response_model=List[MatchResponse])
async def get_joueur_matchs(
    joueur_id: int,
    limit: int = Query(20, ge=1, le=100),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Récupère les matchs d'un joueur."""
    joueur = joueur_repo.get(joueur_id)
    if not joueur:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")
    
    matchs = match_repo.get_by_joueur(joueur_id, limit=limit)
    
    return [
        MatchResponse(
            id=m.id,
            code_match=m.code_match,
            date=m.date_match,
            heure=str(m.heure_match) if m.heure_match else None,
            lieu=m.lieu,
            equipe_a_nom=m.equipe_a.nom if m.equipe_a else "",
            equipe_b_nom=m.equipe_b.nom if m.equipe_b else "",
            score_final=m.score_final,
            vainqueur_nom=m.vainqueur_nom,
        )
        for m in matchs
    ]


# ============== Clubs ==============

@router.get("/clubs", response_model=List[ClubResponse])
async def list_clubs(
    q: Optional[str] = Query(None, min_length=2),
    ligue: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: ClubRepository = Depends(get_club_repo),
):
    """Liste les clubs avec recherche optionnelle."""
    if q:
        clubs = repo.search_by_name(q, limit=limit)
    elif ligue:
        clubs = repo.get_by_ligue(ligue)
    else:
        clubs = repo.get_all(limit=limit, offset=offset)
    
    return [ClubResponse.model_validate(c) for c in clubs]


@router.get("/clubs/{club_id}", response_model=ClubDetail)
async def get_club(
    club_id: int,
    repo: ClubRepository = Depends(get_club_repo),
):
    """Récupère les détails d'un club."""
    club = repo.get(club_id)
    if not club:
        raise HTTPException(status_code=404, detail="Club non trouvé")
    
    return ClubDetail(
        id=club.id,
        nom=club.nom,
        ligue=club.ligue,
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
    """Liste les équipes avec recherche optionnelle."""
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
    """Récupère les détails d'une équipe."""
    equipe = repo.get(equipe_id)
    if not equipe:
        raise HTTPException(status_code=404, detail="Équipe non trouvée")
    
    matchs = match_repo.get_by_equipe(equipe_id, limit=100)
    victoires = sum(1 for m in matchs if m.vainqueur_nom == equipe.nom)
    
    return EquipeDetail(
        id=equipe.id,
        nom=equipe.nom,
        club_id=equipe.club_id,
        club_nom=equipe.club.nom if equipe.club else None,
        matchs_count=len(matchs),
        victoires=victoires,
        defaites=len(matchs) - victoires,
    )


@router.get("/equipes/{equipe_id}/matchs", response_model=List[MatchResponse])
async def get_equipe_matchs(
    equipe_id: int,
    limit: int = Query(20, ge=1, le=100),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Récupère les matchs d'une équipe."""
    equipe = equipe_repo.get(equipe_id)
    if not equipe:
        raise HTTPException(status_code=404, detail="Équipe non trouvée")
    
    matchs = match_repo.get_by_equipe(equipe_id, limit=limit)
    
    return [
        MatchResponse(
            id=m.id,
            code_match=m.code_match,
            date=m.date_match,
            heure=str(m.heure_match) if m.heure_match else None,
            lieu=m.lieu,
            equipe_a_nom=m.equipe_a.nom if m.equipe_a else "",
            equipe_b_nom=m.equipe_b.nom if m.equipe_b else "",
            score_final=m.score_final,
            vainqueur_nom=m.vainqueur_nom,
        )
        for m in matchs
    ]


# ============== Matchs ==============

@router.get("/matchs", response_model=List[MatchResponse])
async def list_matchs(
    competition_id: Optional[int] = None,
    saison_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: MatchRepository = Depends(get_match_repo),
):
    """Liste les matchs avec filtres optionnels."""
    matchs = repo.search(
        competition_id=competition_id,
        saison_id=saison_id,
        limit=limit,
    )
    
    return [
        MatchResponse(
            id=m.id,
            code_match=m.code_match,
            date=m.date_match,
            heure=str(m.heure_match) if m.heure_match else None,
            lieu=m.lieu,
            equipe_a_nom=m.equipe_a.nom if m.equipe_a else "",
            equipe_b_nom=m.equipe_b.nom if m.equipe_b else "",
            score_final=m.score_final,
            vainqueur_nom=m.vainqueur_nom,
        )
        for m in matchs
    ]


@router.get("/matchs/{match_id}", response_model=MatchDetail)
async def get_match(
    match_id: int,
    repo: MatchRepository = Depends(get_match_repo),
):
    """Récupère les détails d'un match."""
    match = repo.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match non trouvé")
    
    from pyvolley.api.schemas import SetResponse
    
    return MatchDetail(
        id=match.id,
        code_match=match.code_match,
        date=match.date_match,
        heure=str(match.heure_match) if match.heure_match else None,
        lieu=match.lieu,
        salle=match.salle,
        equipe_a_nom=match.equipe_a.nom if match.equipe_a else "",
        equipe_b_nom=match.equipe_b.nom if match.equipe_b else "",
        score_final=match.score_final,
        vainqueur_nom=match.vainqueur_nom,
        competition_nom=match.competition.nom if match.competition else None,
        journee=match.journee,
        duree_totale=match.duree_totale,
        sets=[
            SetResponse(
                numero=s.numero,
                score_a=s.score_a or 0,
                score_b=s.score_b or 0,
                heure_debut=str(s.heure_debut) if s.heure_debut else None,
                heure_fin=str(s.heure_fin) if s.heure_fin else None,
            )
            for s in (match.sets or [])
        ],
        remarques=match.remarques,
    )


# ============== Statistiques ==============

@router.get("/stats", response_model=StatsOverview)
async def get_stats(
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    """Récupère les statistiques globales."""
    return StatsOverview(
        total_matchs=match_repo.count(),
        total_joueurs=joueur_repo.count(),
        total_clubs=club_repo.count(),
        total_equipes=equipe_repo.count(),
    )
