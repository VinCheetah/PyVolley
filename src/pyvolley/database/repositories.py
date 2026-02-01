"""
Repositories pour l'accès aux données.

Pattern Repository pour abstraire les opérations CRUD
et fournir des méthodes de recherche avancées.
"""

from typing import Optional, List, Type, TypeVar, Generic
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, and_

from pyvolley.database.models import (
    Base, JoueurDB, ClubDB, EquipeDB, MatchDB, 
    SaisonDB, CompetitionDB, ParticipationMatchDB
)


T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Repository de base avec opérations CRUD génériques."""
    
    def __init__(self, session: Session, model: Type[T]):
        self.session = session
        self.model = model
    
    def get(self, id: int) -> Optional[T]:
        """Récupère une entité par son ID."""
        return self.session.get(self.model, id)
    
    def get_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """Récupère toutes les entités."""
        stmt = select(self.model).limit(limit).offset(offset)
        return list(self.session.scalars(stmt))
    
    def add(self, entity: T) -> T:
        """Ajoute une entité."""
        self.session.add(entity)
        self.session.flush()
        return entity
    
    def add_all(self, entities: List[T]) -> List[T]:
        """Ajoute plusieurs entités."""
        self.session.add_all(entities)
        self.session.flush()
        return entities
    
    def update(self, entity: T) -> T:
        """Met à jour une entité."""
        self.session.merge(entity)
        self.session.flush()
        return entity
    
    def delete(self, entity: T) -> None:
        """Supprime une entité."""
        self.session.delete(entity)
        self.session.flush()
    
    def count(self) -> int:
        """Compte le nombre d'entités."""
        stmt = select(func.count()).select_from(self.model)
        return self.session.scalar(stmt) or 0


class JoueurRepository(BaseRepository[JoueurDB]):
    """Repository pour les joueurs."""
    
    def __init__(self, session: Session):
        super().__init__(session, JoueurDB)
    
    def get_by_licence(self, licence: str) -> Optional[JoueurDB]:
        """Récupère un joueur par sa licence."""
        stmt = select(JoueurDB).where(JoueurDB.licence == licence)
        return self.session.scalar(stmt)
    
    def search_by_name(
        self, 
        query: str, 
        limit: int = 20
    ) -> List[JoueurDB]:
        """Recherche des joueurs par nom/prénom."""
        pattern = f"%{query}%"
        stmt = (
            select(JoueurDB)
            .where(
                or_(
                    JoueurDB.nom.ilike(pattern),
                    JoueurDB.prenom.ilike(pattern),
                    func.concat(JoueurDB.nom, " ", JoueurDB.prenom).ilike(pattern)
                )
            )
            .limit(limit)
        )
        return list(self.session.scalars(stmt))
    
    def get_or_create(
        self, 
        licence: str, 
        nom: str, 
        prenom: str
    ) -> tuple[JoueurDB, bool]:
        """
        Récupère un joueur par licence ou le crée.
        
        Returns:
            Tuple (joueur, created)
        """
        existing = self.get_by_licence(licence)
        if existing:
            return existing, False
        
        new_joueur = JoueurDB(licence=licence, nom=nom, prenom=prenom)
        self.add(new_joueur)
        return new_joueur, True
    
    def get_stats(self, joueur_id: int) -> dict:
        """Récupère les statistiques d'un joueur."""
        joueur = self.get(joueur_id)
        if not joueur:
            return {}
        
        # Compter les matchs
        stmt = (
            select(func.count())
            .select_from(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
        )
        matchs_count = self.session.scalar(stmt) or 0
        
        return {
            "joueur": joueur,
            "matchs_joues": matchs_count,
        }


class ClubRepository(BaseRepository[ClubDB]):
    """Repository pour les clubs."""
    
    def __init__(self, session: Session):
        super().__init__(session, ClubDB)
    
    def search_by_name(self, query: str, limit: int = 20) -> List[ClubDB]:
        """Recherche des clubs par nom."""
        pattern = f"%{query}%"
        stmt = (
            select(ClubDB)
            .where(ClubDB.nom.ilike(pattern))
            .limit(limit)
        )
        return list(self.session.scalars(stmt))
    
    def get_or_create(
        self, 
        nom: str, 
        ligue: Optional[str] = None
    ) -> tuple[ClubDB, bool]:
        """Récupère un club ou le crée."""
        stmt = select(ClubDB).where(ClubDB.nom == nom)
        if ligue:
            stmt = stmt.where(ClubDB.ligue == ligue)
        
        existing = self.session.scalar(stmt)
        if existing:
            return existing, False
        
        new_club = ClubDB(nom=nom, ligue=ligue)
        self.add(new_club)
        return new_club, True
    
    def get_by_ligue(self, ligue: str) -> List[ClubDB]:
        """Récupère les clubs d'une ligue."""
        stmt = select(ClubDB).where(ClubDB.ligue == ligue)
        return list(self.session.scalars(stmt))


class EquipeRepository(BaseRepository[EquipeDB]):
    """Repository pour les équipes."""
    
    def __init__(self, session: Session):
        super().__init__(session, EquipeDB)
    
    def search_by_name(self, query: str, limit: int = 20) -> List[EquipeDB]:
        """Recherche des équipes par nom."""
        pattern = f"%{query}%"
        stmt = (
            select(EquipeDB)
            .where(EquipeDB.nom.ilike(pattern))
            .limit(limit)
        )
        return list(self.session.scalars(stmt))
    
    def get_or_create(
        self, 
        nom: str, 
        club_id: Optional[int] = None
    ) -> tuple[EquipeDB, bool]:
        """Récupère une équipe ou la crée."""
        stmt = select(EquipeDB).where(EquipeDB.nom == nom)
        
        existing = self.session.scalar(stmt)
        if existing:
            return existing, False
        
        new_equipe = EquipeDB(nom=nom, club_id=club_id)
        self.add(new_equipe)
        return new_equipe, True
    
    def get_by_club(self, club_id: int) -> List[EquipeDB]:
        """Récupère les équipes d'un club."""
        stmt = select(EquipeDB).where(EquipeDB.club_id == club_id)
        return list(self.session.scalars(stmt))


class MatchRepository(BaseRepository[MatchDB]):
    """Repository pour les matchs."""
    
    def __init__(self, session: Session):
        super().__init__(session, MatchDB)
    
    def get_by_code(
        self, 
        code_match: str, 
        saison_id: Optional[int] = None
    ) -> Optional[MatchDB]:
        """Récupère un match par son code."""
        stmt = select(MatchDB).where(MatchDB.code_match == code_match)
        if saison_id:
            stmt = stmt.where(MatchDB.saison_id == saison_id)
        return self.session.scalar(stmt)
    
    def search(
        self,
        equipe_nom: Optional[str] = None,
        competition_id: Optional[int] = None,
        saison_id: Optional[int] = None,
        date_debut: Optional[str] = None,
        date_fin: Optional[str] = None,
        limit: int = 50
    ) -> List[MatchDB]:
        """Recherche avancée de matchs."""
        stmt = select(MatchDB)
        
        if competition_id:
            stmt = stmt.where(MatchDB.competition_id == competition_id)
        
        if saison_id:
            stmt = stmt.where(MatchDB.saison_id == saison_id)
        
        # TODO: Ajouter filtres date et équipe
        
        stmt = stmt.order_by(MatchDB.date_match.desc()).limit(limit)
        return list(self.session.scalars(stmt))
    
    def get_by_joueur(self, joueur_id: int, limit: int = 50) -> List[MatchDB]:
        """Récupère les matchs d'un joueur."""
        stmt = (
            select(MatchDB)
            .join(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
            .order_by(MatchDB.date_match.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))
    
    def get_by_equipe(self, equipe_id: int, limit: int = 50) -> List[MatchDB]:
        """Récupère les matchs d'une équipe."""
        stmt = (
            select(MatchDB)
            .where(
                or_(
                    MatchDB.equipe_a_id == equipe_id,
                    MatchDB.equipe_b_id == equipe_id
                )
            )
            .order_by(MatchDB.date_match.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))
    
    def exists(
        self, 
        code_match: str, 
        saison_id: Optional[int] = None
    ) -> bool:
        """Vérifie si un match existe."""
        return self.get_by_code(code_match, saison_id) is not None
