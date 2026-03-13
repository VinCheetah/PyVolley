"""
Repositories pour l'accès aux données.

Pattern Repository pour abstraire les opérations CRUD
et fournir des méthodes de recherche avancées.
"""

from typing import Optional, List, Type, TypeVar, Generic
from sqlalchemy.orm import Session, joinedload, subqueryload
from sqlalchemy import select, func, or_, case, extract, distinct, desc, asc, and_, literal_column

from pyvolley.database.models import (
    Base, JoueurDB, ClubDB, ClubAliasDB, EquipeDB, MatchDB,
    SaisonDB, CompetitionDB, PouleDB, EntiteFFVBDB, SetDB,
    ParticipationMatchDB, OfficielMatchDB, ArbitreDB, ArbitreMatchDB,
    SanctionDB, FormationDB, ChangementDB, TimeoutDB, StatsCacheDB,
)
from pyvolley.analysis.classement import (
    MatchData, ClassementComplet, calculer_classement_complet,
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

    def search_by_name(
        self,
        query: str,
        genre: Optional[str] = None,
        saison_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[JoueurDB]:
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
        )
        # Filtrer par genre via les équipes dans lesquelles le joueur a participé
        if genre or saison_id:
            stmt = stmt.join(ParticipationMatchDB).join(EquipeDB)
            if genre:
                stmt = stmt.where(EquipeDB.genre == genre)
            if saison_id:
                stmt = stmt.where(EquipeDB.saison_id == saison_id)
            stmt = stmt.distinct()
        stmt = stmt.limit(limit)
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

        # Equipes jouées (avec infos complètes)
        equipe_ids = self.session.scalars(
            select(distinct(ParticipationMatchDB.equipe_id))
            .where(ParticipationMatchDB.joueur_id == joueur_id)
        ).all()
        equipes = []
        for eid in equipe_ids:
            eq = self.session.get(EquipeDB, eid)
            if eq:
                equipes.append(eq)

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

        # Victoires / défaites
        victoires = 0
        defaites = 0
        matchs_joueur = self.session.execute(
            select(MatchDB.equipe_a_id, MatchDB.equipe_b_id,
                   MatchDB.sets_equipe_a, MatchDB.sets_equipe_b,
                   ParticipationMatchDB.equipe_id)
            .join(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
            .where(MatchDB.match_joue == True)
        ).all()
        for eq_a_id, eq_b_id, sets_a, sets_b, part_eq_id in matchs_joueur:
            if part_eq_id == eq_a_id:
                if sets_a > sets_b:
                    victoires += 1
                elif sets_b > sets_a:
                    defaites += 1
            elif part_eq_id == eq_b_id:
                if sets_b > sets_a:
                    victoires += 1
                elif sets_a > sets_b:
                    defaites += 1

        # Sets gagnés / perdus
        sets_gagnes = 0
        sets_perdus = 0
        for eq_a_id, eq_b_id, sets_a, sets_b, part_eq_id in matchs_joueur:
            if part_eq_id == eq_a_id:
                sets_gagnes += sets_a
                sets_perdus += sets_b
            elif part_eq_id == eq_b_id:
                sets_gagnes += sets_b
                sets_perdus += sets_a

        # Genre (déduit des équipes)
        genre = None
        for eq in equipes:
            if eq.genre:
                genre = eq.genre
                break

        return {
            "joueur": joueur,
            "matchs_joues": matchs_count,
            "equipes": equipes,
            "equipes_noms": [eq.nom for eq in equipes],
            "saisons": saisons,
            "capitaine_count": capitaine_count,
            "libero_count": libero_count,
            "victoires": victoires,
            "defaites": defaites,
            "sets_gagnes": sets_gagnes,
            "sets_perdus": sets_perdus,
            "genre": genre,
        }

    def get_detailed_stats(self, joueur_id: int) -> dict:
        """Statistiques détaillées d'un joueur : par saison, championnats, performances."""
        joueur = self.get(joueur_id)
        if not joueur:
            return {}

        # Stats par saison
        stats_par_saison = []
        saison_rows = self.session.execute(
            select(
                SaisonDB.code,
                SaisonDB.id,
                func.count(distinct(MatchDB.id)).label("matchs"),
            )
            .select_from(ParticipationMatchDB)
            .join(MatchDB)
            .join(SaisonDB, MatchDB.saison_id == SaisonDB.id)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
            .group_by(SaisonDB.code, SaisonDB.id)
            .order_by(SaisonDB.code)
        ).all()

        for saison_code, saison_id, nb_matchs in saison_rows:
            # Victoires de cette saison
            matchs_saison = self.session.execute(
                select(MatchDB.equipe_a_id, MatchDB.equipe_b_id,
                       MatchDB.sets_equipe_a, MatchDB.sets_equipe_b,
                       ParticipationMatchDB.equipe_id)
                .join(ParticipationMatchDB)
                .where(ParticipationMatchDB.joueur_id == joueur_id)
                .where(MatchDB.saison_id == saison_id)
                .where(MatchDB.match_joue == True)
            ).all()

            v = d = 0
            for eq_a_id, eq_b_id, sets_a, sets_b, part_eq_id in matchs_saison:
                if part_eq_id == eq_a_id:
                    if sets_a > sets_b:
                        v += 1
                    elif sets_b > sets_a:
                        d += 1
                elif part_eq_id == eq_b_id:
                    if sets_b > sets_a:
                        v += 1
                    elif sets_a > sets_b:
                        d += 1

            # Équipes de cette saison
            equipes_saison = self.session.execute(
                select(distinct(EquipeDB.nom), EquipeDB.id, EquipeDB.niveau, EquipeDB.genre)
                .select_from(ParticipationMatchDB)
                .join(EquipeDB)
                .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
                .where(ParticipationMatchDB.joueur_id == joueur_id)
                .where(MatchDB.saison_id == saison_id)
            ).all()

            # Compétitions de cette saison
            competitions_saison = self.session.execute(
                select(
                    distinct(CompetitionDB.nom),
                    CompetitionDB.niveau,
                    CompetitionDB.genre,
                    CompetitionDB.categorie,
                )
                .select_from(ParticipationMatchDB)
                .join(MatchDB)
                .join(CompetitionDB, MatchDB.competition_id == CompetitionDB.id)
                .where(ParticipationMatchDB.joueur_id == joueur_id)
                .where(MatchDB.saison_id == saison_id)
            ).all()

            stats_par_saison.append({
                "saison": saison_code,
                "matchs": nb_matchs,
                "victoires": v,
                "defaites": d,
                "equipes": [
                    {"nom": nom, "id": eid, "niveau": niv, "genre": g}
                    for nom, eid, niv, g in equipes_saison
                ],
                "competitions": [
                    {"nom": nom, "niveau": niv, "genre": g, "categorie": cat}
                    for nom, niv, g, cat in competitions_saison
                ],
            })

        # Matchs par mois (pour graphique d'activité)
        matchs_par_mois = self.session.execute(
            select(
                extract("year", MatchDB.date_match).label("year"),
                extract("month", MatchDB.date_match).label("month"),
                func.count(distinct(MatchDB.id)).label("count"),
            )
            .select_from(ParticipationMatchDB)
            .join(MatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
            .where(MatchDB.date_match.isnot(None))
            .group_by("year", "month")
            .order_by("year", "month")
        ).all()

        return {
            "stats_par_saison": stats_par_saison,
            "matchs_par_mois": [
                {"year": int(y), "month": int(m), "count": c}
                for y, m, c in matchs_par_mois
            ],
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

    def get_with_details(self, club_id: int) -> Optional[ClubDB]:
        """Récupère un club avec ses salles et aliases (eager loading)."""
        from pyvolley.database.models import SalleClubDB
        stmt = (
            select(ClubDB)
            .options(
                joinedload(ClubDB.salles),
                joinedload(ClubDB.aliases),
            )
            .where(ClubDB.id == club_id)
        )
        return self.session.scalar(stmt)


# ─── Equipe ────────────────────────────────────────────────────────

class EquipeRepository(BaseRepository[EquipeDB]):
    def __init__(self, session: Session):
        super().__init__(session, EquipeDB)

    def search_by_name(
        self,
        query: str,
        genre: Optional[str] = None,
        categorie: Optional[str] = None,
        niveau: Optional[str] = None,
        saison_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[EquipeDB]:
        pattern = f"%{query}%"
        stmt = (
            select(EquipeDB)
            .options(joinedload(EquipeDB.club), joinedload(EquipeDB.saison), joinedload(EquipeDB.competition))
            .where(EquipeDB.nom.ilike(pattern))
        )
        if genre:
            stmt = stmt.where(EquipeDB.genre == genre)
        if categorie:
            stmt = stmt.where(EquipeDB.categorie == categorie)
        if niveau:
            stmt = stmt.where(EquipeDB.niveau == niveau)
        if saison_id:
            stmt = stmt.where(EquipeDB.saison_id == saison_id)
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).unique())

    def get_or_create(
        self, nom: str, saison_id: Optional[int] = None, club_id: Optional[int] = None,
        competition_id: Optional[int] = None,
    ) -> tuple[EquipeDB, bool]:
        stmt = select(EquipeDB).where(EquipeDB.nom == nom)
        if saison_id:
            stmt = stmt.where(EquipeDB.saison_id == saison_id)
        if competition_id:
            stmt = stmt.where(EquipeDB.competition_id == competition_id)
        existing = self.session.scalar(stmt)
        if existing:
            return existing, False
        new = EquipeDB(nom=nom, club_id=club_id, saison_id=saison_id, competition_id=competition_id)
        self.add(new)
        return new, True

    def get_by_club(self, club_id: int) -> List[EquipeDB]:
        return list(self.session.scalars(
            select(EquipeDB)
            .options(joinedload(EquipeDB.saison), joinedload(EquipeDB.competition))
            .where(EquipeDB.club_id == club_id)
        ).unique())

    def get_by_saison(self, saison_id: int) -> List[EquipeDB]:
        return list(self.session.scalars(
            select(EquipeDB).where(EquipeDB.saison_id == saison_id)
        ))

    def get_with_details(self, equipe_id: int) -> Optional[EquipeDB]:
        """Charge une équipe avec ses relations (club, saison, compétition)."""
        stmt = (
            select(EquipeDB)
            .options(
                joinedload(EquipeDB.club),
                joinedload(EquipeDB.saison),
                joinedload(EquipeDB.competition),
            )
            .where(EquipeDB.id == equipe_id)
        )
        return self.session.scalar(stmt)

    def get_roster(self, equipe_id: int) -> List[dict]:
        """Effectif complet de l'équipe avec nombre de matchs joués par joueur.

        Retourne une liste de dicts triés par nombre de présences décroissant :
        [{"joueur": JoueurDB, "matchs_joues": int, "capitaine_count": int,
          "libero_count": int, "numero_maillot": str}, ...]
        """
        rows = self.session.execute(
            select(
                JoueurDB,
                func.count(distinct(ParticipationMatchDB.match_id)).label("matchs_joues"),
                func.sum(
                    case((ParticipationMatchDB.est_capitaine == True, 1), else_=0)
                ).label("capitaine_count"),
                func.sum(
                    case((ParticipationMatchDB.est_libero == True, 1), else_=0)
                ).label("libero_count"),
                # Numéro de maillot le plus fréquent
                func.max(ParticipationMatchDB.numero_maillot).label("numero_maillot"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .where(ParticipationMatchDB.equipe_id == equipe_id)
            .group_by(JoueurDB.id)
            .order_by(desc("matchs_joues"), JoueurDB.nom)
        ).all()

        return [
            {
                "joueur": joueur,
                "matchs_joues": matchs_joues,
                "capitaine_count": capitaine_count or 0,
                "libero_count": libero_count or 0,
                "numero_maillot": numero_maillot,
            }
            for joueur, matchs_joues, capitaine_count, libero_count, numero_maillot in rows
        ]

    def get_distinct_genres(self) -> List[str]:
        """Retourne tous les genres distincts existants."""
        return list(self.session.scalars(
            select(distinct(EquipeDB.genre)).where(EquipeDB.genre.isnot(None)).order_by(EquipeDB.genre)
        ))

    def get_distinct_niveaux(self) -> List[str]:
        """Retourne tous les niveaux distincts existants."""
        return list(self.session.scalars(
            select(distinct(EquipeDB.niveau)).where(EquipeDB.niveau.isnot(None)).order_by(EquipeDB.niveau)
        ))

    def get_distinct_categories(self) -> List[str]:
        """Retourne toutes les catégories distinctes existantes."""
        return list(self.session.scalars(
            select(distinct(EquipeDB.categorie)).where(EquipeDB.categorie.isnot(None)).order_by(EquipeDB.categorie)
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
        departements: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[MatchDB]:
        stmt = (
            select(MatchDB)
            .options(
                joinedload(MatchDB.equipe_a),
                joinedload(MatchDB.equipe_b),
                joinedload(MatchDB.competition).joinedload(CompetitionDB.entite),
                joinedload(MatchDB.saison),
                joinedload(MatchDB.poule),
            )
        )
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
        if departements:
            # Filtre géographique : par département du club, lieu du match,
            # et/ou entité organisatrice (ligue/comité → département)
            from pyvolley.core.geo_data import get_cities_for_departments, get_departments_for_entite
            conditions = []
            # 1. Via le département du club
            club_equipe_ids = list(self.session.scalars(
                select(EquipeDB.id)
                .join(ClubDB, EquipeDB.club_id == ClubDB.id)
                .where(ClubDB.departement.in_(departements))
            ))
            if club_equipe_ids:
                conditions.append(
                    or_(
                        MatchDB.equipe_a_id.in_(club_equipe_ids),
                        MatchDB.equipe_b_id.in_(club_equipe_ids),
                    )
                )
            # 2. Via la salle du match (mapping ville → département)
            cities = get_cities_for_departments(departements)
            if cities:
                conditions.append(MatchDB.salle.in_(cities))
            # 3. Via l'entité organisatrice de la compétition
            # Trouver les entités dont les départements correspondent
            dept_set = set(departements)
            matching_entite_ids = []
            all_entites = list(self.session.scalars(
                select(EntiteFFVBDB)
            ))
            for entite in all_entites:
                entite_depts = get_departments_for_entite(entite.code)
                if entite_depts and dept_set.intersection(entite_depts):
                    matching_entite_ids.append(entite.id)
            if matching_entite_ids:
                # Trouver les compétitions liées à ces entités
                comp_ids = list(self.session.scalars(
                    select(CompetitionDB.id)
                    .where(CompetitionDB.entite_id.in_(matching_entite_ids))
                ))
                if comp_ids:
                    conditions.append(MatchDB.competition_id.in_(comp_ids))
            if conditions:
                stmt = stmt.where(or_(*conditions))
            else:
                return []
        stmt = stmt.order_by(MatchDB.date_match.desc()).limit(limit)
        return list(self.session.scalars(stmt).unique())

    def get_by_joueur(self, joueur_id: int, limit: int = 50) -> List[MatchDB]:
        stmt = (
            select(MatchDB)
            .join(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur_id)
            .options(
                joinedload(MatchDB.equipe_a), joinedload(MatchDB.equipe_b),
                joinedload(MatchDB.saison), joinedload(MatchDB.competition),
            )
            .order_by(MatchDB.date_match.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).unique())

    def get_by_equipe(self, equipe_id: int, limit: int = 50) -> List[MatchDB]:
        stmt = (
            select(MatchDB)
            .where(
                or_(MatchDB.equipe_a_id == equipe_id, MatchDB.equipe_b_id == equipe_id)
            )
            .options(
                joinedload(MatchDB.equipe_a), joinedload(MatchDB.equipe_b),
                joinedload(MatchDB.saison),
                joinedload(MatchDB.competition).joinedload(CompetitionDB.entite),
            )
            .order_by(MatchDB.date_match.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).unique())

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
                joinedload(MatchDB.competition).joinedload(CompetitionDB.entite),
                joinedload(MatchDB.saison),
                joinedload(MatchDB.poule),
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

    def get_by_saison(self, saison_id: int, genre: Optional[str] = None,
                      categorie: Optional[str] = None,
                      exclude_code_only: bool = False) -> List[CompetitionDB]:
        stmt = (
            select(CompetitionDB)
            .options(joinedload(CompetitionDB.saison))
            .where(CompetitionDB.saison_id == saison_id)
        )
        if genre:
            stmt = stmt.where(CompetitionDB.genre == genre)
        if categorie:
            stmt = stmt.where(CompetitionDB.categorie == categorie)
        if exclude_code_only:
            # Exclude competitions whose name is just its code (e.g. "PFA", "VMB")
            # These are individual FFVB poules imported as competitions.
            stmt = stmt.where(CompetitionDB.nom != CompetitionDB.code_competition)
        stmt = stmt.order_by(CompetitionDB.genre, CompetitionDB.categorie, CompetitionDB.nom)
        return list(self.session.scalars(stmt).unique())

    def get_all(self, limit: int = 100, offset: int = 0,
                genre: Optional[str] = None,
                categorie: Optional[str] = None,
                exclude_code_only: bool = False) -> List[CompetitionDB]:
        stmt = (
            select(CompetitionDB)
            .options(joinedload(CompetitionDB.saison))
        )
        if genre:
            stmt = stmt.where(CompetitionDB.genre == genre)
        if categorie:
            stmt = stmt.where(CompetitionDB.categorie == categorie)
        if exclude_code_only:
            stmt = stmt.where(CompetitionDB.nom != CompetitionDB.code_competition)
        stmt = stmt.order_by(CompetitionDB.genre, CompetitionDB.categorie, CompetitionDB.nom)
        stmt = stmt.limit(limit).offset(offset)
        return list(self.session.scalars(stmt).unique())

    def search_by_name(self, query: str, genre: Optional[str] = None,
                       categorie: Optional[str] = None, limit: int = 20) -> List[CompetitionDB]:
        stmt = (
            select(CompetitionDB)
            .options(joinedload(CompetitionDB.saison))
            .where(CompetitionDB.nom.ilike(f"%{query}%"))
        )
        if genre:
            stmt = stmt.where(CompetitionDB.genre == genre)
        if categorie:
            stmt = stmt.where(CompetitionDB.categorie == categorie)
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).unique())

    def get_distinct_genres(self) -> List[str]:
        """Retourne tous les genres distincts des compétitions."""
        return list(self.session.scalars(
            select(distinct(CompetitionDB.genre))
            .where(CompetitionDB.genre.isnot(None))
            .order_by(CompetitionDB.genre)
        ))

    def get_distinct_categories(self) -> List[str]:
        """Retourne toutes les catégories distinctes des compétitions."""
        return list(self.session.scalars(
            select(distinct(CompetitionDB.categorie))
            .where(CompetitionDB.categorie.isnot(None))
            .order_by(CompetitionDB.categorie)
        ))

    def get_with_details(self, competition_id: int) -> Optional[CompetitionDB]:
        """Charge une compétition avec ses relations (saison, entité, poules + matchs)."""
        stmt = (
            select(CompetitionDB)
            .options(
                joinedload(CompetitionDB.saison),
                joinedload(CompetitionDB.entite),
                joinedload(CompetitionDB.poules).subqueryload(PouleDB.matchs),
            )
            .where(CompetitionDB.id == competition_id)
        )
        return self.session.scalar(stmt)

    def get_matchs_for_classement(
        self, competition_id: int, *, poule_id: Optional[int] = None
    ) -> List[MatchData]:
        """Récupère les matchs d'une compétition sous forme de MatchData.

        Inclut les scores de chaque set pour calculer les points totaux.
        Si poule_id est fourni, seuls les matchs de cette poule sont retournés.
        """
        stmt = (
            select(MatchDB)
            .options(
                joinedload(MatchDB.equipe_a),
                joinedload(MatchDB.equipe_b),
                joinedload(MatchDB.sets),
            )
            .where(MatchDB.competition_id == competition_id)
            .order_by(MatchDB.date_match.asc(), MatchDB.journee.asc())
        )
        if poule_id is not None:
            stmt = stmt.where(MatchDB.poule_id == poule_id)
        matchs_db = list(self.session.scalars(stmt).unique())

        result: List[MatchData] = []
        for m in matchs_db:
            if not m.equipe_a or not m.equipe_b:
                continue

            # Calculer les points totaux à partir des sets
            points_a = sum(s.score_a or 0 for s in m.sets)
            points_b = sum(s.score_b or 0 for s in m.sets)

            result.append(MatchData(
                match_id=m.id,
                equipe_a_id=m.equipe_a_id,
                equipe_a_nom=m.equipe_a.nom,
                equipe_b_id=m.equipe_b_id,
                equipe_b_nom=m.equipe_b.nom,
                sets_a=m.sets_equipe_a,
                sets_b=m.sets_equipe_b,
                points_a=points_a,
                points_b=points_b,
                journee=m.journee,
                date_match=m.date_match,
                match_joue=m.match_joue,
            ))

        return result

    def get_classement(self, competition_id: int) -> Optional[ClassementComplet]:
        """Calcule le classement complet d'une compétition avec évolution.

        Returns:
            ClassementComplet ou None si la compétition n'existe pas.
        """
        comp = self.get_with_details(competition_id)
        if not comp:
            return None

        matchs_data = self.get_matchs_for_classement(competition_id)

        # Nom de l'organisateur
        organisateur = comp.entite.nom if comp.entite else None

        return calculer_classement_complet(
            matchs=matchs_data,
            competition_id=comp.id,
            competition_nom=comp.nom,
            saison=comp.saison.code if comp.saison else None,
            genre=comp.genre,
            categorie=comp.categorie,
            niveau=comp.niveau,
            division=comp.division,
            organisateur=organisateur,
        )

    def get_classements_par_poule(
        self, competition_id: int
    ) -> List[tuple["PouleDB", ClassementComplet]]:
        """Calcule un classement séparé pour chaque poule d'une compétition.

        Returns:
            Liste de tuples (PouleDB, ClassementComplet) triée par code de poule.
        """
        comp = self.get_with_details(competition_id)
        if not comp or not comp.poules:
            return []

        organisateur = comp.entite.nom if comp.entite else None
        result = []

        for poule in sorted(comp.poules, key=lambda p: p.code):
            matchs_data = self.get_matchs_for_classement(
                competition_id, poule_id=poule.id
            )
            if not matchs_data:
                continue
            classement = calculer_classement_complet(
                matchs=matchs_data,
                competition_id=comp.id,
                competition_nom=f"{comp.nom} — {poule.nom or poule.code}",
                saison=comp.saison.code if comp.saison else None,
                genre=comp.genre,
                categorie=comp.categorie,
                niveau=comp.niveau,
                division=comp.division,
                organisateur=organisateur,
            )
            result.append((poule, classement))

        return result

    def get_equipes_for_competition(self, competition_id: int) -> List[EquipeDB]:
        """Retourne les équipes inscrites dans une compétition."""
        return list(self.session.scalars(
            select(EquipeDB)
            .options(joinedload(EquipeDB.club))
            .where(EquipeDB.competition_id == competition_id)
            .order_by(EquipeDB.nom)
        ).unique())

    def get_classement_for_poule(self, poule_id: int) -> Optional[ClassementComplet]:
        """Calcule le classement pour une poule spécifique.

        Pour le mode multi-poule où chaque poule est aussi vue comme
        une compétition à part entière (avec ses propres stats/évolution).
        """
        poule = self.session.scalar(
            select(PouleDB)
            .options(
                joinedload(PouleDB.competition).joinedload(CompetitionDB.saison),
                joinedload(PouleDB.competition).joinedload(CompetitionDB.entite),
            )
            .where(PouleDB.id == poule_id)
        )
        if not poule or not poule.competition:
            return None

        comp = poule.competition
        matchs_data = self.get_matchs_for_classement(
            comp.id, poule_id=poule_id
        )
        if not matchs_data:
            return None

        organisateur = comp.entite.nom if comp.entite else None
        return calculer_classement_complet(
            matchs=matchs_data,
            competition_id=comp.id,
            competition_nom=f"{comp.nom} — {poule.nom or poule.code}",
            saison=comp.saison.code if comp.saison else None,
            genre=comp.genre,
            categorie=comp.categorie,
            niveau=comp.niveau,
            division=comp.division,
            organisateur=organisateur,
        )


# ─── Poule ─────────────────────────────────────────────────────────

class PouleRepository(BaseRepository[PouleDB]):
    def __init__(self, session: Session):
        super().__init__(session, PouleDB)

    def get_by_competition(self, competition_id: int) -> List[PouleDB]:
        return list(self.session.scalars(
            select(PouleDB).where(PouleDB.competition_id == competition_id)
        ))

    def get_with_details(self, poule_id: int) -> Optional[PouleDB]:
        """Charge une poule avec ses relations (compétition, saison, entité, matchs)."""
        stmt = (
            select(PouleDB)
            .options(
                joinedload(PouleDB.competition).joinedload(CompetitionDB.saison),
                joinedload(PouleDB.competition).joinedload(CompetitionDB.entite),
                joinedload(PouleDB.competition).joinedload(CompetitionDB.poules),
                joinedload(PouleDB.matchs),
            )
            .where(PouleDB.id == poule_id)
        )
        return self.session.scalar(stmt)


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

    def search_by_name(
        self,
        query: str,
        ligue: Optional[str] = None,
        limit: int = 20,
    ) -> List[ArbitreDB]:
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
        )
        if ligue:
            stmt = stmt.where(ArbitreDB.ligue == ligue)
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def get_distinct_ligues(self) -> List[str]:
        """Retourne toutes les ligues distinctes."""
        return list(self.session.scalars(
            select(distinct(ArbitreDB.ligue))
            .where(ArbitreDB.ligue.isnot(None))
            .order_by(ArbitreDB.ligue)
        ))

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

        # Saisons arbitrées
        saisons = self.session.execute(
            select(SaisonDB.code, func.count(distinct(MatchDB.id)))
            .select_from(ArbitreMatchDB)
            .join(MatchDB)
            .join(SaisonDB, MatchDB.saison_id == SaisonDB.id)
            .where(ArbitreMatchDB.arbitre_id == arbitre_id)
            .group_by(SaisonDB.code)
            .order_by(SaisonDB.code)
        ).all()
        saisons_list = [{"saison": code, "matchs": count} for code, count in saisons]

        # Compétitions arbitrées
        competitions = self.session.execute(
            select(CompetitionDB.nom, CompetitionDB.genre, func.count(distinct(MatchDB.id)))
            .select_from(ArbitreMatchDB)
            .join(MatchDB)
            .join(CompetitionDB, MatchDB.competition_id == CompetitionDB.id)
            .where(ArbitreMatchDB.arbitre_id == arbitre_id)
            .group_by(CompetitionDB.nom, CompetitionDB.genre)
        ).all()
        competitions_list = [
            {"nom": nom, "genre": genre, "matchs": count}
            for nom, genre, count in competitions
        ]

        return {
            "arbitre": arbitre,
            "matchs_count": matchs_count,
            "roles": roles_dict,
            "saisons": saisons_list,
            "competitions": competitions_list,
        }

    def get_matchs(self, arbitre_id: int, limit: int = 50) -> List[MatchDB]:
        stmt = (
            select(MatchDB)
            .join(ArbitreMatchDB)
            .where(ArbitreMatchDB.arbitre_id == arbitre_id)
            .options(joinedload(MatchDB.equipe_a), joinedload(MatchDB.equipe_b))
            .order_by(MatchDB.date_match.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).unique())


# =====================================================================
# StatsCacheRepository
# =====================================================================

class StatsCacheRepository(BaseRepository[StatsCacheDB]):
    """Repository pour le cache des statistiques pré-calculées."""

    def __init__(self, session: Session):
        super().__init__(session, StatsCacheDB)

    def get_by_filter_key(self, filter_key: str) -> Optional[StatsCacheDB]:
        """Récupère une entrée de cache par sa clé de filtre."""
        return self.session.scalar(
            select(StatsCacheDB).where(StatsCacheDB.filter_key == filter_key)
        )

    def upsert(self, filter_key: str, stats_data: dict, match_count: int) -> StatsCacheDB:
        """Crée ou met à jour une entrée de cache pour la clé donnée."""
        from datetime import datetime
        entry = self.get_by_filter_key(filter_key)
        if entry is None:
            entry = StatsCacheDB(
                filter_key=filter_key,
                stats_data=stats_data,
                match_count=match_count,
                computed_at=datetime.now(),
            )
            self.session.add(entry)
        else:
            entry.stats_data = stats_data
            entry.match_count = match_count
            entry.computed_at = datetime.now()
        self.session.flush()
        return entry

    def is_stale(self, filter_key: str, current_match_count: int) -> bool:
        """Retourne True si le cache est absent ou que le nombre de matchs a changé."""
        entry = self.get_by_filter_key(filter_key)
        if entry is None:
            return True
        return entry.match_count != current_match_count

    def delete_all(self) -> int:
        """Supprime toutes les entrées de cache. Retourne le nombre de lignes supprimées."""
        from sqlalchemy import delete as sa_delete
        result = self.session.execute(sa_delete(StatsCacheDB))
        self.session.flush()
        return result.rowcount

    def list_all(self) -> list:
        """Retourne toutes les entrées de cache, triées par date de calcul décroissante."""
        return list(self.session.scalars(
            select(StatsCacheDB).order_by(StatsCacheDB.computed_at.desc())
        ))
