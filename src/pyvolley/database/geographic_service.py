"""
Service d'analyse géographique et territoriale du volley-ball français.

Agrège et analyse les données aux échelons National, Régional (Ligues) et
Départemental (Comités) en exploitant les informations existantes dans la base
(ClubDB.departement, ClubDB.ligue, EquipeDB, CompetitionDB).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, distinct, and_, or_, desc
from sqlalchemy.orm import Session

from pyvolley.database.models import (
    ClubDB, EquipeDB, CompetitionDB, MatchDB, JoueurDB,
    ParticipationMatchDB, GeoStatsDB, SaisonDB,
)
from pyvolley.database.repositories import GeoStatsRepository


@dataclass
class TerritoireSummary:
    code: str
    nom: str
    echelon: str  # "national", "region", "departement"
    nb_clubs: int = 0
    nb_equipes: int = 0
    nb_joueurs_actifs: int = 0
    nb_matchs_joues: int = 0
    repartition_genre: Dict[str, int] = field(default_factory=dict)
    repartition_categories: Dict[str, int] = field(default_factory=dict)
    repartition_niveaux: Dict[str, int] = field(default_factory=dict)


class GeographicStatsService:
    """Service d'agrégation et de consultation territoriale."""

    def __init__(self, session: Session):
        self.session = session
        self.repo = GeoStatsRepository(session)

    def compute_territorial_rollups(self, saison_id: Optional[int] = None) -> int:
        """Calcule et persiste les agrégats territoriaux pour une saison (ou globale si None)."""
        count = 0

        # 1. Échelon National
        national_stats = self._aggregate_scope(saison_id=saison_id)
        self.repo.upsert({
            "saison_id": saison_id,
            "echelon": "national",
            "code_territoire": "FR",
            "nom_territoire": "France entière",
            "nb_clubs": national_stats["nb_clubs"],
            "nb_equipes": national_stats["nb_equipes"],
            "nb_joueurs_actifs": national_stats["nb_joueurs"],
            "nb_matchs_joues": national_stats["nb_matchs"],
            "repartition_genre": national_stats["genres"],
            "repartition_categories": national_stats["categories"],
            "repartition_niveaux": national_stats["niveaux"],
        })
        count += 1

        # 2. Échelon Régional (par ligue renseignée sur ClubDB)
        ligues = list(
            self.session.scalars(
                select(distinct(ClubDB.ligue)).where(ClubDB.ligue.is_not(None), ClubDB.ligue != "")
            )
        )
        for ligue in ligues:
            l_stats = self._aggregate_scope(saison_id=saison_id, ligue=ligue)
            self.repo.upsert({
                "saison_id": saison_id,
                "echelon": "region",
                "code_territoire": ligue,
                "nom_territoire": ligue,
                "nb_clubs": l_stats["nb_clubs"],
                "nb_equipes": l_stats["nb_equipes"],
                "nb_joueurs_actifs": l_stats["nb_joueurs"],
                "nb_matchs_joues": l_stats["nb_matchs"],
                "repartition_genre": l_stats["genres"],
                "repartition_categories": l_stats["categories"],
                "repartition_niveaux": l_stats["niveaux"],
            })
            count += 1

        # 3. Échelon Départemental (par code département sur ClubDB)
        departements = list(
            self.session.scalars(
                select(distinct(ClubDB.departement)).where(
                    ClubDB.departement.is_not(None), ClubDB.departement != ""
                )
            )
        )
        for dept in departements:
            d_stats = self._aggregate_scope(saison_id=saison_id, departement=dept)
            self.repo.upsert({
                "saison_id": saison_id,
                "echelon": "departement",
                "code_territoire": dept,
                "nom_territoire": f"Département {dept}",
                "nb_clubs": d_stats["nb_clubs"],
                "nb_equipes": d_stats["nb_equipes"],
                "nb_joueurs_actifs": d_stats["nb_joueurs"],
                "nb_matchs_joues": d_stats["nb_matchs"],
                "repartition_genre": d_stats["genres"],
                "repartition_categories": d_stats["categories"],
                "repartition_niveaux": d_stats["niveaux"],
            })
            count += 1

        self.session.commit()
        return count

    def _aggregate_scope(
        self,
        saison_id: Optional[int] = None,
        ligue: Optional[str] = None,
        departement: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Agrège les métriques pour un périmètre donné."""
        # Filtre clubs
        club_q = select(ClubDB.id)
        if ligue:
            club_q = club_q.where(ClubDB.ligue == ligue)
        if departement:
            club_q = club_q.where(ClubDB.departement == departement)

        nb_clubs = self.session.scalar(select(func.count()).select_from(club_q.subquery())) or 0

        # Filtre équipes
        eq_q = select(EquipeDB.id).where(EquipeDB.club_id.in_(club_q))
        if saison_id:
            eq_q = eq_q.where(EquipeDB.saison_id == saison_id)

        nb_equipes = self.session.scalar(select(func.count()).select_from(eq_q.subquery())) or 0

        # Filtre matchs
        m_q = select(MatchDB.id).where(
            or_(
                MatchDB.equipe_a_id.in_(eq_q),
                MatchDB.equipe_b_id.in_(eq_q),
            )
        )
        if saison_id:
            m_q = m_q.where(MatchDB.saison_id == saison_id)

        nb_matchs = self.session.scalar(select(func.count()).select_from(m_q.subquery())) or 0

        # Joueurs distincts actifs
        j_q = (
            select(func.count(distinct(ParticipationMatchDB.joueur_id)))
            .where(ParticipationMatchDB.match_id.in_(m_q))
        )
        nb_joueurs = self.session.scalar(j_q) or 0

        # Répartition par genre (via CompetitionDB)
        genre_q = (
            select(
                func.coalesce(CompetitionDB.genre, "Non spécifié").label("genre"),
                func.count(distinct(ParticipationMatchDB.joueur_id)).label("count"),
            )
            .select_from(ParticipationMatchDB)
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .join(CompetitionDB, MatchDB.competition_id == CompetitionDB.id, isouter=True)
            .where(ParticipationMatchDB.match_id.in_(m_q))
            .group_by(CompetitionDB.genre)
        )
        genres = {str(row.genre): row.count for row in self.session.execute(genre_q)}

        # Répartition par niveau (via CompetitionDB)
        niveau_q = (
            select(
                func.coalesce(CompetitionDB.niveau, "Autres").label("niveau"),
                func.count(distinct(MatchDB.id)).label("count"),
            )
            .select_from(MatchDB)
            .join(CompetitionDB, MatchDB.competition_id == CompetitionDB.id, isouter=True)
            .where(MatchDB.id.in_(m_q))
            .group_by(CompetitionDB.niveau)
            .order_by(desc("count"))
            .limit(10)
        )
        niveaux = {str(row.niveau): row.count for row in self.session.execute(niveau_q)}

        # Répartition par catégorie
        cat_q = (
            select(
                func.coalesce(CompetitionDB.categorie, "Séniors").label("categorie"),
                func.count(distinct(MatchDB.id)).label("count"),
            )
            .select_from(MatchDB)
            .join(CompetitionDB, MatchDB.competition_id == CompetitionDB.id, isouter=True)
            .where(MatchDB.id.in_(m_q))
            .group_by(CompetitionDB.categorie)
            .order_by(desc("count"))
            .limit(10)
        )
        categories = {str(row.categorie): row.count for row in self.session.execute(cat_q)}

        return {
            "nb_clubs": nb_clubs,
            "nb_equipes": nb_equipes,
            "nb_joueurs": nb_joueurs,
            "nb_matchs": nb_matchs,
            "genres": genres,
            "niveaux": niveaux,
            "categories": categories,
        }

    def get_national_overview(self, saison_id: Optional[int] = None) -> TerritoireSummary:
        """Récupère ou calcule à la volée le résumé national."""
        row = self.repo.get_by_key("national", "FR", saison_id)
        if not row:
            self.compute_territorial_rollups(saison_id)
            row = self.repo.get_by_key("national", "FR", saison_id)

        if not row:
            return TerritoireSummary(code="FR", nom="France", echelon="national")

        return TerritoireSummary(
            code=row.code_territoire,
            nom=row.nom_territoire,
            echelon=row.echelon,
            nb_clubs=row.nb_clubs,
            nb_equipes=row.nb_equipes,
            nb_joueurs_actifs=row.nb_joueurs_actifs,
            nb_matchs_joues=row.nb_matchs_joues,
            repartition_genre=row.repartition_genre or {},
            repartition_categories=row.repartition_categories or {},
            repartition_niveaux=row.repartition_niveaux or {},
        )

    def get_regions_list(self, saison_id: Optional[int] = None) -> List[TerritoireSummary]:
        """Liste de toutes les régions avec leurs indicateurs clés."""
        rows = self.repo.get_by_echelon("region", saison_id)
        if not rows:
            self.compute_territorial_rollups(saison_id)
            rows = self.repo.get_by_echelon("region", saison_id)

        return [
            TerritoireSummary(
                code=r.code_territoire,
                nom=r.nom_territoire,
                echelon=r.echelon,
                nb_clubs=r.nb_clubs,
                nb_equipes=r.nb_equipes,
                nb_joueurs_actifs=r.nb_joueurs_actifs,
                nb_matchs_joues=r.nb_matchs_joues,
                repartition_genre=r.repartition_genre or {},
                repartition_categories=r.repartition_categories or {},
                repartition_niveaux=r.repartition_niveaux or {},
            )
            for r in rows
        ]

    def get_departements_list(self, ligue: Optional[str] = None, saison_id: Optional[int] = None) -> List[TerritoireSummary]:
        """Liste des départements avec possibilité de filtrer par ligue d'appartenance."""
        stmt = select(GeoStatsDB).where(
            GeoStatsDB.echelon == "departement",
            GeoStatsDB.saison_id == saison_id,
        )
        if ligue:
            # Récupère les départements des clubs appartenant à cette ligue
            dept_in_ligue = select(distinct(ClubDB.departement)).where(ClubDB.ligue == ligue)
            stmt = stmt.where(GeoStatsDB.code_territoire.in_(dept_in_ligue))

        stmt = stmt.order_by(desc(GeoStatsDB.nb_clubs))
        rows = list(self.session.scalars(stmt))

        return [
            TerritoireSummary(
                code=r.code_territoire,
                nom=r.nom_territoire,
                echelon=r.echelon,
                nb_clubs=r.nb_clubs,
                nb_equipes=r.nb_equipes,
                nb_joueurs_actifs=r.nb_joueurs_actifs,
                nb_matchs_joues=r.nb_matchs_joues,
                repartition_genre=r.repartition_genre or {},
                repartition_categories=r.repartition_categories or {},
                repartition_niveaux=r.repartition_niveaux or {},
            )
            for r in rows
        ]
