"""
Routes web — Recherche globale.
"""

from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from pyvolley.web.templateconfig import templates
from pyvolley.web.helpers.time_filter import build_time_filter
from pyvolley.api.dependencies import (
    get_joueur_repo,
    get_club_repo,
    get_equipe_repo,
    get_arbitre_repo,
    get_saison_repo,
    get_entraineur_repo,
    get_session,
)
from pyvolley.database.models import (
    MatchDB,
    ParticipationMatchDB,
    EquipeDB,
    ArbitreMatchDB,
    OfficielMatchDB,
)
from pyvolley.database.repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    ArbitreRepository,
    SaisonRepository,
    EntraineurRepository,
)

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: Optional[str] = Query(None, min_length=2),
    genre: Optional[str] = Query(None),
    niveau: Optional[str] = Query(None),
    saison_id: Optional[int] = Query(None),
    saison_ids: Optional[list[int]] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    after_date: Optional[str] = Query(None),
    before_date: Optional[str] = Query(None),
    ligue: Optional[str] = Query(None),
    joueur_repo: JoueurRepository = Depends(get_joueur_repo),
    club_repo: ClubRepository = Depends(get_club_repo),
    equipe_repo: EquipeRepository = Depends(get_equipe_repo),
    arbitre_repo: ArbitreRepository = Depends(get_arbitre_repo),
    saison_repo: SaisonRepository = Depends(get_saison_repo),
    entraineur_repo: EntraineurRepository = Depends(get_entraineur_repo),
    session: Session = Depends(get_session),
):
    time_filter = build_time_filter(
        season_ids=saison_ids,
        season_id=saison_id,
        date_from=date_from,
        date_to=date_to,
        after_date=after_date,
        before_date=before_date,
    )

    results = {
        "joueurs": [],
        "clubs": [],
        "equipes": [],
        "arbitres": [],
        "entraineurs": [],
        "query": q or "",
        "genre": genre or "",
        "niveau": niveau or "",
        "saison_id": saison_id,
        **time_filter.to_context(),
        "ligue": ligue or "",
    }

    if q:
        results["joueurs"] = joueur_repo.search_by_name(
            q, genre=genre, saison_id=saison_id, limit=30
        )
        results["clubs"] = club_repo.search_by_name(q, limit=30)
        results["equipes"] = equipe_repo.search_by_name(
            q, genre=genre, niveau=niveau, saison_id=saison_id, limit=30
        )
        results["arbitres"] = arbitre_repo.search_by_name(q, ligue=ligue, limit=30)
        results["entraineurs"] = entraineur_repo.search_by_name(q, limit=20)

        if time_filter.is_active:
            match_ids_stmt = select(MatchDB.id)
            match_ids_stmt = time_filter.apply_to_match_stmt(match_ids_stmt, MatchDB)
            filtered_match_ids = set(session.scalars(match_ids_stmt).all())

            if filtered_match_ids:
                joueur_ids = {j.id for j in results["joueurs"]}
                if joueur_ids:
                    allowed_joueurs = set(
                        session.scalars(
                            select(ParticipationMatchDB.joueur_id)
                            .where(ParticipationMatchDB.match_id.in_(filtered_match_ids))
                            .where(ParticipationMatchDB.joueur_id.in_(joueur_ids))
                        ).all()
                    )
                    results["joueurs"] = [j for j in results["joueurs"] if j.id in allowed_joueurs]

                equipe_ids = {e.id for e in results["equipes"]}
                if equipe_ids:
                    allowed_equipes = set(
                        session.scalars(
                            select(ParticipationMatchDB.equipe_id)
                            .where(ParticipationMatchDB.match_id.in_(filtered_match_ids))
                            .where(ParticipationMatchDB.equipe_id.in_(equipe_ids))
                        ).all()
                    )
                    results["equipes"] = [e for e in results["equipes"] if e.id in allowed_equipes]

                arbitre_ids = {a.id for a in results["arbitres"]}
                if arbitre_ids:
                    allowed_arbitres = set(
                        session.scalars(
                            select(ArbitreMatchDB.arbitre_id)
                            .where(ArbitreMatchDB.match_id.in_(filtered_match_ids))
                            .where(ArbitreMatchDB.arbitre_id.in_(arbitre_ids))
                        ).all()
                    )
                    results["arbitres"] = [a for a in results["arbitres"] if a.id in allowed_arbitres]

                entraineur_ids = {
                    (e.get("id") if isinstance(e, dict) else getattr(e, "id", None))
                    for e in results["entraineurs"]
                }
                entraineur_ids.discard(None)
                if entraineur_ids:
                    allowed_entraineurs = set(
                        session.scalars(
                            select(OfficielMatchDB.personne_id)
                            .where(OfficielMatchDB.match_id.in_(filtered_match_ids))
                            .where(OfficielMatchDB.personne_id.isnot(None))
                            .where(OfficielMatchDB.personne_id.in_(entraineur_ids))
                        ).all()
                    )
                    results["entraineurs"] = [
                        e for e in results["entraineurs"]
                        if (e.get("id") if isinstance(e, dict) else getattr(e, "id", None)) in allowed_entraineurs
                    ]

                club_ids = {c.id for c in results["clubs"]}
                if club_ids:
                    allowed_clubs = set(
                        session.scalars(
                            select(EquipeDB.club_id)
                            .join(ParticipationMatchDB, ParticipationMatchDB.equipe_id == EquipeDB.id)
                            .where(ParticipationMatchDB.match_id.in_(filtered_match_ids))
                            .where(EquipeDB.club_id.isnot(None))
                            .where(EquipeDB.club_id.in_(club_ids))
                        ).all()
                    )
                    results["clubs"] = [c for c in results["clubs"] if c.id in allowed_clubs]
            else:
                results["joueurs"] = []
                results["clubs"] = []
                results["equipes"] = []
                results["arbitres"] = []
                results["entraineurs"] = []

    saisons = saison_repo.get_all(limit=20)
    genres = equipe_repo.get_distinct_genres()
    niveaux = equipe_repo.get_distinct_niveaux()
    ligues = arbitre_repo.get_distinct_ligues()

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            **results,
            "saisons": saisons,
            "genres": genres,
            "niveaux": niveaux,
            "ligues": ligues,
        },
    )
