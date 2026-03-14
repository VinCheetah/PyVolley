"""
Dépendances FastAPI pour l'injection de dépendances.
"""

from typing import Generator
from fastapi import Depends
from sqlalchemy.orm import Session

from pyvolley.database.connection import get_db
from pyvolley.database.repositories import (
    JoueurRepository,
    ClubRepository,
    EquipeRepository,
    MatchRepository,
    SaisonRepository,
    CompetitionRepository,
    ArbitreRepository,
    PouleRepository,
    EntraineurRepository,
)


def get_session() -> Generator[Session, None, None]:
    """Dépendance pour obtenir une session de base de données."""
    with get_db() as session:
        yield session


def get_joueur_repo(
    session: Session = Depends(get_session)
) -> JoueurRepository:
    return JoueurRepository(session)


def get_club_repo(
    session: Session = Depends(get_session)
) -> ClubRepository:
    return ClubRepository(session)


def get_equipe_repo(
    session: Session = Depends(get_session)
) -> EquipeRepository:
    return EquipeRepository(session)


def get_match_repo(
    session: Session = Depends(get_session)
) -> MatchRepository:
    return MatchRepository(session)


def get_saison_repo(
    session: Session = Depends(get_session)
) -> SaisonRepository:
    return SaisonRepository(session)


def get_competition_repo(
    session: Session = Depends(get_session)
) -> CompetitionRepository:
    return CompetitionRepository(session)


def get_arbitre_repo(
    session: Session = Depends(get_session)
) -> ArbitreRepository:
    return ArbitreRepository(session)


def get_poule_repo(
    session: Session = Depends(get_session)
) -> PouleRepository:
    return PouleRepository(session)


def get_entraineur_repo(
    session: Session = Depends(get_session)
) -> EntraineurRepository:
    return EntraineurRepository(session)
