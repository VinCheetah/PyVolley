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
)


def get_session() -> Generator[Session, None, None]:
    """Dépendance pour obtenir une session de base de données."""
    with get_db() as session:
        yield session


def get_joueur_repo(
    session: Session = Depends(get_session)
) -> JoueurRepository:
    """Dépendance pour le repository des joueurs."""
    return JoueurRepository(session)


def get_club_repo(
    session: Session = Depends(get_session)
) -> ClubRepository:
    """Dépendance pour le repository des clubs."""
    return ClubRepository(session)


def get_equipe_repo(
    session: Session = Depends(get_session)
) -> EquipeRepository:
    """Dépendance pour le repository des équipes."""
    return EquipeRepository(session)


def get_match_repo(
    session: Session = Depends(get_session)
) -> MatchRepository:
    """Dépendance pour le repository des matchs."""
    return MatchRepository(session)
