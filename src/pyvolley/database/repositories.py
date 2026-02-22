"""
Repositories pour l'accès aux données.

Pattern Repository pour abstraire les opérations CRUD
et fournir des méthodes de recherche avancées.
"""

from typing import Optional, List, Type, TypeVar, Generic
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, func, or_, case, extract, distinct, desc

from pyvolley.database.models import (
    Base, JoueurDB, ClubDB, ClubAliasDB, EquipeDB, MatchDB,
    SaisonDB, CompetitionDB, PouleDB, EntiteFFVBDB, SetDB,
    ParticipationMatchDB, OfficielMatchDB, ArbitreDB, ArbitreMatchDB,
    SanctionDB, FormationDB, ChangementDB, TimeoutDB,
)


T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Repository de base avec opérations CRUD génériques."""

    def __init__(self, session: Session, model: Type[T]):
        self.session = session
        self.model = model

    def get(self, id: int) -> Optional[T]:
        return self.session.get(self.model, id)

    def get_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        stmt = select(self.model).limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    def add(self, entity: T) -> T:
        self.session.add(entity)
        self.session.flush()
        return entity

    def add_all(self, entities: List[T]) -> List[T]:
        self.session.add_all(entities)
        self.session.flush()
        return entities

    def update(self, entity: T) -> T:
        self.session.merge(entity)
        self.session.flush()
        return entity

    def delete(self, entity: T) -> None:
        self.session.delete(entity)
        self.session.flush()

    def count(self) -> int:
        stmt = select(func.count()).select_from(self.model)
        return self.session.scalar(stmt) or 0


# ─── Joueur ────────────────────────────────────────────────────────

class JoueurRepository(BaseRepository[JoueurDB]):
    def __init__(self, session: Session):
        super().__init__(session, JoueurDB)

    def get_by_licence(self, licence: str) -> Optional[JoueurDB]:
        return self.session.scalar(select(JoueurDB).where(JoueurDB.licence == licence))

    def search_by_name(self, query: str, limit: int = 20) -> List[JoueurDB]:
        pattern = f"%{query}%"
        stmt = (
            select(JoueurDB)
            .where(
                or_(
                    JoueurDB.nom.ilike(pattern),
                    JoueurDB.prenom.ilike(pattern),
                    func.concat(JoueurDB.nom, " ", JoueurDB.prenom).ilike(pattern),
                )
            )
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def get_or_create(self, licence: str, nom: str, prenom: str) -> tuple[JoueurDB, bool]:
        existing = self.get_by_licence(licence)
        if existing:
            return existing, False
        new = JoueurDB(licence=licence, nom=nom, prenom=prenom)
        self.add(new)
        return new, True

    def get_stats(self, joueur_id: int) -> dict:
        joueur = self.get(joueur_id)
        if not joueur:
            return {}
        matchs_count = self.session.scalar(
            select(func.count())
            .select_from(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
        ) or 0

        # Equipes jouées
        equipe_ids = self.session.scalars(
            select(distinct(ParticipationMatchDB.equipe_id))
            .where(ParticipationMatchDB.joueur_id == joueur_id)
        ).all()
        equipes = []
        for eid in equipe_ids:
            eq = self.session.get(EquipeDB, eid)
            if eq:
                equipes.append(eq.nom)

        # Saisons jouées
        saisons = []
        saison_ids = self.session.scalars(
            select(distinct(MatchDB.saison_id))
            .join(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
            .where(MatchDB.saison_id.isnot(None))
        ).all()
        for sid in saison_ids:
            s = self.session.get(SaisonDB, sid)
            if s:
                saisons.append(s.code)

        # Capitainats et libero
        capitaine_count = self.session.scalar(
            select(func.count()).select_from(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
            .where(ParticipationMatchDB.est_capitaine == True)
        ) or 0
        libero_count = self.session.scalar(
            select(func.count()).select_from(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
            .where(ParticipationMatchDB.est_libero == True)
        ) or 0

        return {
            "joueur": joueur,
            "matchs_joues": matchs_count,
            "equipes": equipes,
            "saisons": saisons,
            "capitaine_count": capitaine_count,
            "libero_count": libero_count,
        }

    def get_match_stats(self, joueur_id: int, match_id: int) -> dict:
        """Statistiques d'un joueur pour un match spécifique."""
        participation = self.session.scalar(
            select(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
            .where(ParticipationMatchDB.match_id == match_id)
        )
        if not participation:
            return {}

        match = self.session.get(MatchDB, match_id)
        if not match:
            return {}

        # Déterminer le côté (A ou B)
        side = None
        if match.equipe_a_id == participation.equipe_id:
            side = "A"
        elif match.equipe_b_id == participation.equipe_id:
            side = "B"

        # Chercher les formations pour savoir quand le joueur était titulaire
        sets_titulaire = 0
        sets_entrant = 0
        numero = participation.numero_maillot

        if numero and match.sets:
            for s in match.sets:
                for f in s.formations:
                    if side and f.equipe == side:
                        positions = [f.position_1, f.position_2, f.position_3,
                                     f.position_4, f.position_5, f.position_6]
                        if numero in positions:
                            sets_titulaire += 1
                for c in s.changements:
                    if c.joueur_entrant == numero:
                        sets_entrant += 1

        return {
            "participation": participation,
            "match": match,
            "side": side,
            "numero_maillot": numero,
            "est_capitaine": participation.est_capitaine,
            "est_libero": participation.est_libero,
            "sets_titulaire": sets_titulaire,
            "sets_entrant": sets_entrant,
        }


# ─── Club ──────────────────────────────────────────────────────────

class ClubRepository(BaseRepository[ClubDB]):
    def __init__(self, session: Session):
        super().__init__(session, ClubDB)

    def search_by_name(self, query: str, limit: int = 20) -> List[ClubDB]:
        pattern = f"%{query}%"
        stmt = select(ClubDB).where(ClubDB.nom.ilike(pattern)).limit(limit)
        return list(self.session.scalars(stmt))

    def get_or_create(self, nom: str) -> tuple[ClubDB, bool]:
        existing = self.session.scalar(select(ClubDB).where(ClubDB.nom == nom))
        if existing:
            return existing, False
        new = ClubDB(nom=nom)
        self.add(new)
        return new, True

    def get_by_alias(self, alias: str) -> Optional[ClubDB]:
        """Cherche un club via un alias."""
        match = self.session.scalar(
            select(ClubAliasDB).where(ClubAliasDB.alias == alias)
        )
        return match.club if match else None


# ─── Equipe ────────────────────────────────────────────────────────

class EquipeRepository(BaseRepository[EquipeDB]):
    def __init__(self, session: Session):
        super().__init__(session, EquipeDB)

    def search_by_name(self, query: str, limit: int = 20) -> List[EquipeDB]:
        pattern = f"%{query}%"
        stmt = select(EquipeDB).where(EquipeDB.nom.ilike(pattern)).limit(limit)
        return list(self.session.scalars(stmt))

    def get_or_create(
        self, nom: str, saison_id: Optional[int] = None, club_id: Optional[int] = None,
    ) -> tuple[EquipeDB, bool]:
        stmt = select(EquipeDB).where(EquipeDB.nom == nom)
        if saison_id:
            stmt = stmt.where(EquipeDB.saison_id == saison_id)
        existing = self.session.scalar(stmt)
        if existing:
            return existing, False
        new = EquipeDB(nom=nom, club_id=club_id, saison_id=saison_id)
        self.add(new)
        return new, True

    def get_by_club(self, club_id: int) -> List[EquipeDB]:
        return list(self.session.scalars(
            select(EquipeDB).where(EquipeDB.club_id == club_id)
        ))

    def get_by_saison(self, saison_id: int) -> List[EquipeDB]:
        return list(self.session.scalars(
            select(EquipeDB).where(EquipeDB.saison_id == saison_id)
        ))


# ─── Match ─────────────────────────────────────────────────────────

class MatchRepository(BaseRepository[MatchDB]):
    def __init__(self, session: Session):
        super().__init__(session, MatchDB)

    def get_by_code(self, code_match: str, saison_id: Optional[int] = None) -> Optional[MatchDB]:
        stmt = select(MatchDB).where(MatchDB.code_match == code_match)
        if saison_id:
            stmt = stmt.where(MatchDB.saison_id == saison_id)
        return self.session.scalar(stmt)

    def search(
        self,
        equipe_nom: Optional[str] = None,
        competition_id: Optional[int] = None,
        poule_id: Optional[int] = None,
        saison_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[MatchDB]:
        stmt = select(MatchDB)
        if competition_id:
            stmt = stmt.where(MatchDB.competition_id == competition_id)
        if poule_id:
            stmt = stmt.where(MatchDB.poule_id == poule_id)
        if saison_id:
            stmt = stmt.where(MatchDB.saison_id == saison_id)
        if equipe_nom:
            equipe_ids = self.session.scalars(
                select(EquipeDB.id).where(EquipeDB.nom.ilike(f"%{equipe_nom}%"))
            ).all()
            if equipe_ids:
                stmt = stmt.where(
                    or_(
                        MatchDB.equipe_a_id.in_(equipe_ids),
                        MatchDB.equipe_b_id.in_(equipe_ids),
                    )
                )
            else:
                return []
        stmt = stmt.order_by(MatchDB.date_match.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def get_by_joueur(self, joueur_id: int, limit: int = 50) -> List[MatchDB]:
        stmt = (
            select(MatchDB)
            .join(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
            .order_by(MatchDB.date_match.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def get_by_equipe(self, equipe_id: int, limit: int = 50) -> List[MatchDB]:
        stmt = (
            select(MatchDB)
            .where(
                or_(MatchDB.equipe_a_id == equipe_id, MatchDB.equipe_b_id == equipe_id)
            )
            .order_by(MatchDB.date_match.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def exists(self, code_match: str, saison_id: Optional[int] = None) -> bool:
        return self.get_by_code(code_match, saison_id) is not None

    def get_with_details(self, match_id: int) -> Optional[MatchDB]:
        """Charge un match avec toutes ses relations (sets, participations, etc.)."""
        stmt = (
            select(MatchDB)
            .options(
                joinedload(MatchDB.sets).joinedload(SetDB.formations),
                joinedload(MatchDB.sets).joinedload(SetDB.changements),
                joinedload(MatchDB.sets).joinedload(SetDB.timeouts),
                joinedload(MatchDB.participations).joinedload(ParticipationMatchDB.joueur),
                joinedload(MatchDB.participations).joinedload(ParticipationMatchDB.equipe),
                joinedload(MatchDB.arbitrages).joinedload(ArbitreMatchDB.arbitre),
                joinedload(MatchDB.sanctions),
                joinedload(MatchDB.officiels),
                joinedload(MatchDB.equipe_a),
                joinedload(MatchDB.equipe_b),
                joinedload(MatchDB.competition),
                joinedload(MatchDB.saison),
            )
            .where(MatchDB.id == match_id)
        )
        return self.session.scalar(stmt)

    def get_stats_by_month(self, saison_id: Optional[int] = None) -> list:
        """Nombre de matchs par mois."""
        stmt = (
            select(
                extract("year", MatchDB.date_match).label("year"),
                extract("month", MatchDB.date_match).label("month"),
                func.count().label("count"),
            )
            .where(MatchDB.date_match.isnot(None))
            .group_by("year", "month")
            .order_by("year", "month")
        )
        if saison_id:
            stmt = stmt.where(MatchDB.saison_id == saison_id)
        return list(self.session.execute(stmt))

    def count_by_saison(self) -> list:
        """Nombre de matchs par saison."""
        stmt = (
            select(SaisonDB.code, func.count(MatchDB.id))
            .join(SaisonDB, MatchDB.saison_id == SaisonDB.id)
            .group_by(SaisonDB.code)
            .order_by(SaisonDB.code)
        )
        return list(self.session.execute(stmt))


# ─── Saison ────────────────────────────────────────────────────────

class SaisonRepository(BaseRepository[SaisonDB]):
    def __init__(self, session: Session):
        super().__init__(session, SaisonDB)

    def get_by_code(self, code: str) -> Optional[SaisonDB]:
        return self.session.scalar(select(SaisonDB).where(SaisonDB.code == code))


# ─── Competition ───────────────────────────────────────────────────

class CompetitionRepository(BaseRepository[CompetitionDB]):
    def __init__(self, session: Session):
        super().__init__(session, CompetitionDB)

    def get_by_saison(self, saison_id: int) -> List[CompetitionDB]:
        return list(self.session.scalars(
            select(CompetitionDB).where(CompetitionDB.saison_id == saison_id)
        ))

    def search_by_name(self, query: str, limit: int = 20) -> List[CompetitionDB]:
        return list(self.session.scalars(
            select(CompetitionDB).where(CompetitionDB.nom.ilike(f"%{query}%")).limit(limit)
        ))


# ─── Poule ─────────────────────────────────────────────────────────

class PouleRepository(BaseRepository[PouleDB]):
    def __init__(self, session: Session):
        super().__init__(session, PouleDB)

    def get_by_competition(self, competition_id: int) -> List[PouleDB]:
        return list(self.session.scalars(
            select(PouleDB).where(PouleDB.competition_id == competition_id)
        ))


# ─── EntiteFFVB ────────────────────────────────────────────────────

class EntiteFFVBRepository(BaseRepository[EntiteFFVBDB]):
    def __init__(self, session: Session):
        super().__init__(session, EntiteFFVBDB)

    def get_by_code(self, code: str) -> Optional[EntiteFFVBDB]:
        return self.session.scalar(
            select(EntiteFFVBDB).where(EntiteFFVBDB.code == code)
        )


# ─── Arbitre ───────────────────────────────────────────────────────

class ArbitreRepository(BaseRepository[ArbitreDB]):
    def __init__(self, session: Session):
        super().__init__(session, ArbitreDB)

    def search_by_name(self, query: str, limit: int = 20) -> List[ArbitreDB]:
        pattern = f"%{query}%"
        stmt = (
            select(ArbitreDB)
            .where(
                or_(
                    ArbitreDB.nom.ilike(pattern),
                    ArbitreDB.prenom.ilike(pattern),
                    func.concat(ArbitreDB.nom, " ", ArbitreDB.prenom).ilike(pattern),
                )
            )
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def get_stats(self, arbitre_id: int) -> dict:
        arbitre = self.get(arbitre_id)
        if not arbitre:
            return {}
        matchs_count = self.session.scalar(
            select(func.count()).select_from(ArbitreMatchDB)
            .where(ArbitreMatchDB.arbitre_id == arbitre_id)
        ) or 0

        # Roles breakdown
        roles = self.session.execute(
            select(ArbitreMatchDB.role, func.count())
            .where(ArbitreMatchDB.arbitre_id == arbitre_id)
            .group_by(ArbitreMatchDB.role)
        ).all()
        roles_dict = {r: c for r, c in roles}

        return {
            "arbitre": arbitre,
            "matchs_count": matchs_count,
            "roles": roles_dict,
        }

    def get_matchs(self, arbitre_id: int, limit: int = 50) -> List[MatchDB]:
        stmt = (
            select(MatchDB)
            .join(ArbitreMatchDB)
            .where(ArbitreMatchDB.arbitre_id == arbitre_id)
            .order_by(MatchDB.date_match.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))
