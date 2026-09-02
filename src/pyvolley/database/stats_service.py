"""
Service de calcul de statistiques amusantes / palmarès.

Calcule des records et classements ludiques à partir des données
de matchs, joueurs, équipes et arbitres, avec filtrage avancé.
"""

import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from collections import defaultdict

from sqlalchemy import select, func, distinct, desc, asc, and_, or_, case, literal
from sqlalchemy.orm import Session, joinedload

from pyvolley.database.models import (
    JoueurDB, MatchDB, EquipeDB, SetDB, ClubDB, SaisonDB,
    CompetitionDB, ParticipationMatchDB, ArbitreDB, ArbitreMatchDB,
    EntiteFFVBDB,
)


# ─── Hiérarchie des niveaux ─────────────────────────────────────

_NIVEAU_ORDER = {
    "LOISIR": 0,
    "DEPARTEMENTAL": 1, "DÉPARTEMENTAL": 1, "DEPARTEMENTALE": 1, "DÉPARTEMENTALE": 1,
    "PRE_REGIONALE": 2, "PRÉ_RÉGIONALE": 2, "PREREGIONALE": 2,
    "REGIONAL": 3, "RÉGIONAL": 3, "REGIONALE": 3, "RÉGIONALE": 3,
    "PRE_NATIONALE": 4, "PRÉNATIONAL": 4, "PRENATIONAL": 4,
    "PRENATIONALE": 4, "PRÉNATIONALE": 4,
    "PRE-NATIONAL": 4, "PRÉ-NATIONAL": 4, "PRE-NATIONALE": 4, "PRÉ-NATIONALE": 4,
    "NATIONAL": 5, "NATIONALE": 5,
    "N3": 5, "N2": 6, "N1": 7,
    "ELITE": 8, "ÉLITE": 8,
    "PRO": 9, "PRO B": 9, "PRO A": 10,
}

_NIVEAUX_LABELS = {
    0: "Loisir", 1: "Départemental", 2: "Pré-régional",
    3: "Régional", 4: "Pré-national", 5: "National",
    6: "N2", 7: "N1", 8: "Élite", 9: "Pro B", 10: "Pro A",
}

_MIN_MATCHES_FOR_TEAM_WINRATE = 5


def _niveau_rank(niveau_str: Optional[str]) -> Optional[int]:
    if not niveau_str:
        return None
    return _NIVEAU_ORDER.get(niveau_str.upper().strip())


# ─── Filtres ────────────────────────────────────────────────────

@dataclass
class StatsFilters:
    """Filtres pour les statistiques amusantes."""
    saison_id: Optional[int] = None
    saison_ids: Optional[List[int]] = None
    date_from: Optional[datetime.date] = None
    date_to: Optional[datetime.date] = None
    genre: Optional[str] = None
    categorie: Optional[str] = None
    niveau_min: Optional[str] = None  # rang textuel
    niveau_max: Optional[str] = None
    departement: Optional[str] = None


# ─── Service ────────────────────────────────────────────────────

class StatsAmusantesService:
    """Calcule des statistiques ludiques sur les données volleyball."""

    def __init__(self, session: Session):
        self.session = session
        self._match_ids_cache: Dict[str, Optional[List[int]]] = {}

    # ─── Helpers de filtrage ────────────────────────────

    def _base_match_filter(self, stmt, filters: StatsFilters):
        """Applique les filtres communs sur les matchs (la table MatchDB doit être dans le FROM)."""
        season_ids = list(filters.saison_ids or [])
        if filters.saison_id and filters.saison_id not in season_ids:
            season_ids.append(filters.saison_id)

        if season_ids:
            stmt = stmt.where(MatchDB.saison_id.in_(season_ids))
        elif filters.saison_id:
            stmt = stmt.where(MatchDB.saison_id == filters.saison_id)
        if filters.date_from:
            stmt = stmt.where(MatchDB.date_match >= filters.date_from)
        if filters.date_to:
            stmt = stmt.where(MatchDB.date_match <= filters.date_to)
        if filters.genre or filters.categorie or filters.niveau_min or filters.niveau_max:
            # Joindre la compétition si on filtre dessus
            if not self._has_join(stmt, CompetitionDB):
                stmt = stmt.join(CompetitionDB, MatchDB.competition_id == CompetitionDB.id, isouter=True)
            if filters.genre:
                stmt = stmt.where(CompetitionDB.genre == filters.genre)
            if filters.categorie:
                stmt = stmt.where(CompetitionDB.categorie == filters.categorie)
        if filters.departement:
            # Filtrer par département des clubs impliqués
            dept_equipe_ids = list(self.session.scalars(
                select(EquipeDB.id)
                .join(ClubDB, EquipeDB.club_id == ClubDB.id)
                .where(ClubDB.departement == filters.departement)
            ))
            if dept_equipe_ids:
                stmt = stmt.where(
                    or_(
                        MatchDB.equipe_a_id.in_(dept_equipe_ids),
                        MatchDB.equipe_b_id.in_(dept_equipe_ids),
                    )
                )
            else:
                # Aucune équipe dans ce département → pas de résultats
                stmt = stmt.where(literal(False))
        # Filtrage niveau min/max
        if filters.niveau_min or filters.niveau_max:
            min_rank = _niveau_rank(filters.niveau_min)
            max_rank = _niveau_rank(filters.niveau_max)
            if min_rank is not None or max_rank is not None:
                # On filtre les niveaux des compétitions
                valid_niveaux = set()
                for label, rank in _NIVEAU_ORDER.items():
                    if min_rank is not None and rank < min_rank:
                        continue
                    if max_rank is not None and rank > max_rank:
                        continue
                    valid_niveaux.add(label)
                if valid_niveaux:
                    stmt = stmt.where(
                        func.upper(CompetitionDB.niveau).in_(valid_niveaux)
                    )
        return stmt

    @staticmethod
    def _has_join(stmt, table) -> bool:
        """Vérifie si un JOIN sur la table existe déjà (heuristique simple)."""
        try:
            froms = str(stmt)
            return table.__tablename__ in froms
        except Exception:
            return False

    def _filtered_match_ids(self, filters: StatsFilters) -> Optional[List[int]]:
        """Retourne les IDs de matchs correspondant aux filtres, ou None si pas de filtre.
        Résultat mis en cache pour éviter les requêtes répétées."""
        cache_key = (
            f"{filters.saison_id}:{filters.saison_ids}:{filters.date_from}:{filters.date_to}:"
            f"{filters.genre}:{filters.categorie}:{filters.niveau_min}:{filters.niveau_max}:{filters.departement}"
        )
        if cache_key in self._match_ids_cache:
            return self._match_ids_cache[cache_key]

        has_filter = any([
            filters.saison_id, filters.saison_ids, filters.date_from, filters.date_to,
            filters.genre, filters.categorie,
            filters.niveau_min, filters.niveau_max, filters.departement,
        ])
        if not has_filter:
            self._match_ids_cache[cache_key] = None
            return None

        stmt = select(MatchDB.id).where(MatchDB.match_joue == True)
        stmt = self._base_match_filter(stmt, filters)
        result = list(self.session.scalars(stmt))
        self._match_ids_cache[cache_key] = result
        return result

    def _current_cache_signature(
        self,
        filters: StatsFilters,
    ) -> tuple[int, Optional[datetime.datetime]]:
        """Retourne la signature courante du jeu de données filtré.

        La signature combine le nombre de matchs joués et le dernier
        ``updated_at`` des matchs concernés, ce qui évite les faux cache hits
        lorsque des données changent sans variation du volume.
        """
        stmt = (
            select(
                func.count(MatchDB.id).label("match_count"),
                func.max(MatchDB.updated_at).label("last_updated_at"),
            )
            .select_from(MatchDB)
            .where(MatchDB.match_joue == True)
        )
        stmt = self._base_match_filter(stmt, filters)
        row = self.session.execute(stmt).one()
        return int(row.match_count or 0), row.last_updated_at

    def current_cache_signature(
        self,
        filters: StatsFilters,
    ) -> tuple[int, Optional[datetime.datetime]]:
        """API publique de récupération de signature de cache."""
        return self._current_cache_signature(filters)

    # ─── Statistiques joueurs ──────────────────────────

    def top_joueurs_matchs(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Joueurs ayant joué le plus de matchs."""
        match_ids = self._filtered_match_ids(filters)

        stmt = (
            select(
                JoueurDB.id,
                JoueurDB.nom,
                JoueurDB.prenom,
                func.count(distinct(ParticipationMatchDB.match_id)).label("nb_matchs"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(MatchDB.match_joue == True)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = (
            stmt.group_by(JoueurDB.id, JoueurDB.nom, JoueurDB.prenom)
            .order_by(desc("nb_matchs"))
            .limit(limit)
        )
        rows = self.session.execute(stmt).all()
        return [
            {"id": r.id, "nom": r.nom, "prenom": r.prenom, "valeur": r.nb_matchs}
            for r in rows
        ]

    def top_joueurs_victoires(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Joueurs avec le plus de victoires."""
        match_ids = self._filtered_match_ids(filters)

        # On récupère les participations avec résultats
        stmt = (
            select(
                JoueurDB.id,
                JoueurDB.nom,
                JoueurDB.prenom,
                func.sum(
                    case(
                        (and_(
                            ParticipationMatchDB.equipe_id == MatchDB.equipe_a_id,
                            MatchDB.sets_equipe_a > MatchDB.sets_equipe_b,
                        ), 1),
                        (and_(
                            ParticipationMatchDB.equipe_id == MatchDB.equipe_b_id,
                            MatchDB.sets_equipe_b > MatchDB.sets_equipe_a,
                        ), 1),
                        else_=0,
                    )
                ).label("victoires"),
                func.count(distinct(ParticipationMatchDB.match_id)).label("nb_matchs"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(MatchDB.match_joue == True)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = (
            stmt.group_by(JoueurDB.id, JoueurDB.nom, JoueurDB.prenom)
            .order_by(desc("victoires"))
            .limit(limit)
        )
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": r.id, "nom": r.nom, "prenom": r.prenom,
                "valeur": int(r.victoires or 0),
                "matchs": r.nb_matchs,
                "taux": round(100 * (r.victoires or 0) / r.nb_matchs, 1) if r.nb_matchs else 0,
            }
            for r in rows
        ]

    def top_joueurs_defaites(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Joueurs avec le plus de défaites."""
        match_ids = self._filtered_match_ids(filters)

        stmt = (
            select(
                JoueurDB.id,
                JoueurDB.nom,
                JoueurDB.prenom,
                func.sum(
                    case(
                        (and_(
                            ParticipationMatchDB.equipe_id == MatchDB.equipe_a_id,
                            MatchDB.sets_equipe_a < MatchDB.sets_equipe_b,
                        ), 1),
                        (and_(
                            ParticipationMatchDB.equipe_id == MatchDB.equipe_b_id,
                            MatchDB.sets_equipe_b < MatchDB.sets_equipe_a,
                        ), 1),
                        else_=0,
                    )
                ).label("defaites"),
                func.count(distinct(ParticipationMatchDB.match_id)).label("nb_matchs"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(MatchDB.match_joue == True)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = (
            stmt.group_by(JoueurDB.id, JoueurDB.nom, JoueurDB.prenom)
            .order_by(desc("defaites"))
            .limit(limit)
        )
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": r.id, "nom": r.nom, "prenom": r.prenom,
                "valeur": int(r.defaites or 0),
                "matchs": r.nb_matchs,
            }
            for r in rows
        ]

    def top_joueurs_capitaine(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Joueurs ayant été le plus souvent capitaine."""
        match_ids = self._filtered_match_ids(filters)

        stmt = (
            select(
                JoueurDB.id,
                JoueurDB.nom,
                JoueurDB.prenom,
                func.count(ParticipationMatchDB.id).label("nb_capitainats"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(ParticipationMatchDB.est_capitaine == True)
            .where(MatchDB.match_joue == True)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = (
            stmt.group_by(JoueurDB.id, JoueurDB.nom, JoueurDB.prenom)
            .order_by(desc("nb_capitainats"))
            .limit(limit)
        )
        rows = self.session.execute(stmt).all()
        return [
            {"id": r.id, "nom": r.nom, "prenom": r.prenom, "valeur": r.nb_capitainats}
            for r in rows
        ]

    def top_joueurs_libero(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Joueurs ayant été le plus souvent libero."""
        match_ids = self._filtered_match_ids(filters)

        stmt = (
            select(
                JoueurDB.id,
                JoueurDB.nom,
                JoueurDB.prenom,
                func.count(ParticipationMatchDB.id).label("nb_liberos"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(ParticipationMatchDB.est_libero == True)
            .where(MatchDB.match_joue == True)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = (
            stmt.group_by(JoueurDB.id, JoueurDB.nom, JoueurDB.prenom)
            .order_by(desc("nb_liberos"))
            .limit(limit)
        )
        rows = self.session.execute(stmt).all()
        return [
            {"id": r.id, "nom": r.nom, "prenom": r.prenom, "valeur": r.nb_liberos}
            for r in rows
        ]

    def top_joueurs_fideles(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Joueurs les plus fidèles : le plus de matchs pour une même équipe."""
        match_ids = self._filtered_match_ids(filters)

        stmt = (
            select(
                JoueurDB.id,
                JoueurDB.nom,
                JoueurDB.prenom,
                EquipeDB.nom.label("equipe_nom"),
                EquipeDB.id.label("equipe_id"),
                func.count(distinct(ParticipationMatchDB.match_id)).label("nb_matchs"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .join(EquipeDB, ParticipationMatchDB.equipe_id == EquipeDB.id)
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(MatchDB.match_joue == True)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = (
            stmt.group_by(JoueurDB.id, JoueurDB.nom, JoueurDB.prenom, EquipeDB.nom, EquipeDB.id)
            .order_by(desc("nb_matchs"))
            .limit(limit)
        )
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": r.id, "nom": r.nom, "prenom": r.prenom,
                "valeur": r.nb_matchs,
                "equipe_nom": r.equipe_nom, "equipe_id": r.equipe_id,
            }
            for r in rows
        ]

    def top_joueurs_marqueurs(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Joueurs ayant marqué le plus grand nombre total de points."""
        match_ids = self._filtered_match_ids(filters)

        # Si pas de filtres personnalisés complexes, requêter d'abord JoueurSaisonStatsDB
        if match_ids is None and not (filters.genre or filters.categorie or filters.niveau_min or filters.niveau_max or filters.departement or filters.date_from or filters.date_to):
            from pyvolley.database.repositories import JoueurSaisonStatsRepository
            repo = JoueurSaisonStatsRepository(self.session)
            scorers = repo.get_top_scorers(saison_id=filters.saison_id, limit=limit)
            if scorers:
                return [
                    {
                        "id": s["joueur_id"],
                        "nom": s["nom"],
                        "prenom": s["prenom"],
                        "valeur": s["points"],
                        "matchs": s["matchs"],
                        "ppm": s["ppm"],
                        "equipe_nom": s.get("equipe"),
                    }
                    for s in scorers
                ]

        from pyvolley.database.models import JoueurMatchStatsDB
        stmt = (
            select(
                JoueurDB.id,
                JoueurDB.nom,
                JoueurDB.prenom,
                func.sum(JoueurMatchStatsDB.points_gagnes).label("total_points"),
                func.count(distinct(JoueurMatchStatsDB.match_id)).label("nb_matchs"),
            )
            .join(JoueurMatchStatsDB, JoueurMatchStatsDB.joueur_id == JoueurDB.id)
            .join(MatchDB, JoueurMatchStatsDB.match_id == MatchDB.id)
            .where(MatchDB.match_joue == True)
            .where(JoueurMatchStatsDB.points_gagnes > 0)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = (
            stmt.group_by(JoueurDB.id, JoueurDB.nom, JoueurDB.prenom)
            .order_by(desc("total_points"))
            .limit(limit)
        )
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": r.id,
                "nom": r.nom,
                "prenom": r.prenom,
                "valeur": int(r.total_points or 0),
                "matchs": r.nb_matchs,
                "ppm": round(float(r.total_points or 0) / max(1, r.nb_matchs or 1), 2),
            }
            for r in rows
        ]

    def top_joueurs_serveurs(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Joueurs ayant effectué le plus grand nombre de services."""
        match_ids = self._filtered_match_ids(filters)

        if match_ids is None and not (filters.genre or filters.categorie or filters.niveau_min or filters.niveau_max or filters.departement or filters.date_from or filters.date_to):
            from pyvolley.database.repositories import JoueurSaisonStatsRepository
            repo = JoueurSaisonStatsRepository(self.session)
            servers = repo.get_top_servers(saison_id=filters.saison_id, limit=limit)
            if servers:
                return [
                    {
                        "id": s["joueur_id"],
                        "nom": s["nom"],
                        "prenom": s["prenom"],
                        "valeur": s["services"],
                        "max_serie": s["max_serie"],
                        "matchs": s["matchs"],
                        "equipe_nom": s.get("equipe"),
                    }
                    for s in servers
                ]

        from pyvolley.database.models import JoueurMatchStatsDB
        stmt = (
            select(
                JoueurDB.id,
                JoueurDB.nom,
                JoueurDB.prenom,
                func.sum(JoueurMatchStatsDB.services).label("total_services"),
                func.max(JoueurMatchStatsDB.max_serie).label("record_serie"),
                func.count(distinct(JoueurMatchStatsDB.match_id)).label("nb_matchs"),
            )
            .join(JoueurMatchStatsDB, JoueurMatchStatsDB.joueur_id == JoueurDB.id)
            .join(MatchDB, JoueurMatchStatsDB.match_id == MatchDB.id)
            .where(MatchDB.match_joue == True)
            .where(JoueurMatchStatsDB.services > 0)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = (
            stmt.group_by(JoueurDB.id, JoueurDB.nom, JoueurDB.prenom)
            .order_by(desc("total_services"))
            .limit(limit)
        )
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": r.id,
                "nom": r.nom,
                "prenom": r.prenom,
                "valeur": int(r.total_services or 0),
                "max_serie": int(r.record_serie or 0),
                "matchs": r.nb_matchs,
            }
            for r in rows
        ]


    def meilleure_serie_victoires(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Meilleure série de victoires consécutives (actuelle et record) par joueur.

        Optimisé : charge toutes les données en une seule requête, puis traite en Python.
        Se limite aux 50 joueurs les plus actifs pour la performance.
        """
        match_ids = self._filtered_match_ids(filters)

        # Récupérer les joueurs les plus actifs (top 50)
        stmt_top = (
            select(JoueurDB.id, JoueurDB.nom, JoueurDB.prenom)
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(MatchDB.match_joue == True)
        )
        if match_ids is not None:
            stmt_top = stmt_top.where(MatchDB.id.in_(match_ids))
        stmt_top = (
            stmt_top.group_by(JoueurDB.id, JoueurDB.nom, JoueurDB.prenom)
            .order_by(desc(func.count(ParticipationMatchDB.id)))
            .limit(50)
        )
        top_joueurs = list(self.session.execute(stmt_top))

        if not top_joueurs:
            return []

        top_joueur_ids = [j.id for j in top_joueurs]
        joueur_info = {j.id: (j.nom, j.prenom) for j in top_joueurs}

        # Charger TOUS les matchs de ces joueurs en une seule requête
        stmt = (
            select(
                ParticipationMatchDB.joueur_id,
                MatchDB.id,
                MatchDB.date_match,
                MatchDB.equipe_a_id,
                MatchDB.equipe_b_id,
                MatchDB.sets_equipe_a,
                MatchDB.sets_equipe_b,
                ParticipationMatchDB.equipe_id,
            )
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(ParticipationMatchDB.joueur_id.in_(top_joueur_ids))
            .where(MatchDB.match_joue == True)
            .order_by(ParticipationMatchDB.joueur_id, MatchDB.date_match.asc(), MatchDB.id.asc())
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        all_rows = list(self.session.execute(stmt))

        # Regrouper par joueur
        joueur_matchs = defaultdict(list)
        for r in all_rows:
            joueur_matchs[r.joueur_id].append(r)

        results = []
        for joueur_id, matchs in joueur_matchs.items():
            current_streak = 0
            best_streak = 0
            for m in matchs:
                won = False
                if m.equipe_id == m.equipe_a_id and m.sets_equipe_a > m.sets_equipe_b:
                    won = True
                elif m.equipe_id == m.equipe_b_id and m.sets_equipe_b > m.sets_equipe_a:
                    won = True

                if won:
                    current_streak += 1
                    best_streak = max(best_streak, current_streak)
                else:
                    current_streak = 0

            if best_streak >= 3:
                nom, prenom = joueur_info.get(joueur_id, ("?", ""))
                results.append({
                    "id": joueur_id,
                    "nom": nom,
                    "prenom": prenom,
                    "serie_actuelle": current_streak,
                    "record": best_streak,
                    "matchs_total": len(matchs),
                })

        # Trier par record puis série actuelle
        results.sort(key=lambda x: (-x["record"], -x["serie_actuelle"]))
        return results[:limit]

    def meilleure_serie_victoires_actuelle(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Joueurs avec la meilleure série de victoires EN COURS."""
        all_series = self.meilleure_serie_victoires(filters, limit=50)
        # Trier par série actuelle
        all_series.sort(key=lambda x: (-x["serie_actuelle"], -x["record"]))
        return [s for s in all_series if s["serie_actuelle"] >= 2][:limit]

    # ─── Statistiques matchs ──────────────────────────

    def matchs_les_plus_serres(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Matchs avec le plus petit écart total de points entre les deux équipes."""
        match_ids = self._filtered_match_ids(filters)

        eq_a_alias = EquipeDB.__table__.alias("eq_a")
        eq_b_alias = EquipeDB.__table__.alias("eq_b")

        total_a = func.sum(SetDB.score_a).label("total_points_a")
        total_b = func.sum(SetDB.score_b).label("total_points_b")

        # Sous-requête pour agréger puis trier par écart en SQL
        sub = (
            select(
                MatchDB.id.label("match_id"),
                MatchDB.code_match,
                MatchDB.date_match,
                MatchDB.sets_equipe_a,
                MatchDB.sets_equipe_b,
                MatchDB.equipe_a_id,
                MatchDB.equipe_b_id,
                total_a,
                total_b,
            )
            .join(SetDB, SetDB.match_id == MatchDB.id)
            .where(MatchDB.match_joue == True)
            .where(SetDB.score_a.isnot(None))
            .where(SetDB.score_b.isnot(None))
        )
        if match_ids is not None:
            sub = sub.where(MatchDB.id.in_(match_ids))

        sub = sub.group_by(
            MatchDB.id, MatchDB.code_match, MatchDB.date_match,
            MatchDB.sets_equipe_a, MatchDB.sets_equipe_b,
            MatchDB.equipe_a_id, MatchDB.equipe_b_id,
        ).having(func.sum(SetDB.score_a) > 0).having(func.sum(SetDB.score_b) > 0)

        sub = sub.subquery()

        ecart_expr = func.abs(sub.c.total_points_a - sub.c.total_points_b)
        stmt = (
            select(
                sub.c.match_id,
                sub.c.code_match,
                sub.c.date_match,
                sub.c.sets_equipe_a,
                sub.c.sets_equipe_b,
                sub.c.total_points_a,
                sub.c.total_points_b,
                ecart_expr.label("ecart"),
                eq_a_alias.c.nom.label("equipe_a_nom"),
                eq_b_alias.c.nom.label("equipe_b_nom"),
            )
            .outerjoin(eq_a_alias, sub.c.equipe_a_id == eq_a_alias.c.id)
            .outerjoin(eq_b_alias, sub.c.equipe_b_id == eq_b_alias.c.id)
            .order_by(asc(ecart_expr))
            .limit(limit)
        )

        rows = list(self.session.execute(stmt))
        results = []
        for r in rows:
            results.append({
                "match_id": r.match_id,
                "code_match": r.code_match,
                "date": r.date_match,
                "equipe_a": r.equipe_a_nom or "?",
                "equipe_b": r.equipe_b_nom or "?",
                "score_sets": f"{r.sets_equipe_a}-{r.sets_equipe_b}",
                "total_a": int(r.total_points_a),
                "total_b": int(r.total_points_b),
                "ecart": r.ecart,
            })

        return results

    def sets_les_plus_serres(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Sets avec le plus petit écart de points."""
        match_ids = self._filtered_match_ids(filters)

        eq_a_alias = EquipeDB.__table__.alias("eq_a_set")
        eq_b_alias = EquipeDB.__table__.alias("eq_b_set")

        ecart_expr = func.abs(SetDB.score_a - SetDB.score_b)
        total_expr = SetDB.score_a + SetDB.score_b

        stmt = (
            select(
                SetDB.id,
                SetDB.numero,
                SetDB.score_a,
                SetDB.score_b,
                SetDB.duree_minutes,
                MatchDB.id.label("match_id"),
                MatchDB.code_match,
                MatchDB.date_match,
                eq_a_alias.c.nom.label("equipe_a_nom"),
                eq_b_alias.c.nom.label("equipe_b_nom"),
                ecart_expr.label("ecart"),
                total_expr.label("total_points"),
            )
            .join(MatchDB, SetDB.match_id == MatchDB.id)
            .outerjoin(eq_a_alias, MatchDB.equipe_a_id == eq_a_alias.c.id)
            .outerjoin(eq_b_alias, MatchDB.equipe_b_id == eq_b_alias.c.id)
            .where(SetDB.score_a.isnot(None))
            .where(SetDB.score_b.isnot(None))
            .where(MatchDB.match_joue == True)
            .where(or_(SetDB.score_a >= 25, SetDB.score_b >= 25,
                       and_(SetDB.numero == 5, or_(SetDB.score_a >= 15, SetDB.score_b >= 15))))
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        # Sort and limit in SQL
        stmt = stmt.order_by(asc(ecart_expr), desc(total_expr)).limit(limit)

        rows = list(self.session.execute(stmt))
        results = []
        for r in rows:
            results.append({
                "set_id": r.id,
                "numero": r.numero,
                "score_a": r.score_a,
                "score_b": r.score_b,
                "ecart": r.ecart,
                "total_points": r.total_points,
                "duree": r.duree_minutes,
                "match_id": r.match_id,
                "code_match": r.code_match,
                "date": r.date_match,
                "equipe_a": r.equipe_a_nom or "?",
                "equipe_b": r.equipe_b_nom or "?",
            })

        return results

    def plus_gros_ecart_set(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Sets avec le plus gros écart de points (domination)."""
        match_ids = self._filtered_match_ids(filters)

        eq_a_alias = EquipeDB.__table__.alias("eq_a_dom")
        eq_b_alias = EquipeDB.__table__.alias("eq_b_dom")

        # Utiliser une expression SQL pour l'écart et trier/limiter en SQL
        ecart_expr = func.abs(SetDB.score_a - SetDB.score_b)

        stmt = (
            select(
                SetDB.id,
                SetDB.numero,
                SetDB.score_a,
                SetDB.score_b,
                MatchDB.id.label("match_id"),
                MatchDB.code_match,
                MatchDB.date_match,
                eq_a_alias.c.nom.label("equipe_a_nom"),
                eq_b_alias.c.nom.label("equipe_b_nom"),
                ecart_expr.label("ecart"),
            )
            .join(MatchDB, SetDB.match_id == MatchDB.id)
            .outerjoin(eq_a_alias, MatchDB.equipe_a_id == eq_a_alias.c.id)
            .outerjoin(eq_b_alias, MatchDB.equipe_b_id == eq_b_alias.c.id)
            .where(SetDB.score_a.isnot(None))
            .where(SetDB.score_b.isnot(None))
            .where(MatchDB.match_joue == True)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = stmt.order_by(desc(ecart_expr)).limit(limit)

        rows = list(self.session.execute(stmt))
        results = []
        for r in rows:
            if r.score_a > r.score_b:
                dominateur = r.equipe_a_nom or "Équipe A"
            else:
                dominateur = r.equipe_b_nom or "Équipe B"
            results.append({
                "set_id": r.id,
                "numero": r.numero,
                "score_a": r.score_a,
                "score_b": r.score_b,
                "ecart": r.ecart,
                "dominateur": dominateur,
                "match_id": r.match_id,
                "code_match": r.code_match,
                "date": r.date_match,
                "equipe_a": r.equipe_a_nom or "?",
                "equipe_b": r.equipe_b_nom or "?",
            })

        return results

    def comebacks(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Matchs avec les plus grands comebacks (equipe qui remonte le plus de sets de retard)."""
        match_ids = self._filtered_match_ids(filters)

        eq_a_alias = EquipeDB.__table__.alias("eq_a_cb")
        eq_b_alias = EquipeDB.__table__.alias("eq_b_cb")

        # Ne charger que les matchs en 5 sets (seuls candidats pour un vrai comeback 0-2 → 3-2)
        # ou en 4 sets avec score 3-1 (comeback potentiel 0-1 → 3-1)
        stmt = (
            select(
                MatchDB.id,
                MatchDB.code_match,
                MatchDB.date_match,
                MatchDB.sets_equipe_a,
                MatchDB.sets_equipe_b,
                eq_a_alias.c.nom.label("equipe_a_nom"),
                eq_b_alias.c.nom.label("equipe_b_nom"),
            )
            .outerjoin(eq_a_alias, MatchDB.equipe_a_id == eq_a_alias.c.id)
            .outerjoin(eq_b_alias, MatchDB.equipe_b_id == eq_b_alias.c.id)
            .where(MatchDB.match_joue == True)
            .where(MatchDB.has_details == True)
            # Seulement matchs en 5 sets (les vrais comebacks 0-2 → 3-2)
            .where(
                (MatchDB.sets_equipe_a + MatchDB.sets_equipe_b) == 5
            )
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        match_rows = list(self.session.execute(stmt))

        if not match_rows:
            return []

        # Charger les sets de ces matchs en une seule requête
        match_id_list = [r.id for r in match_rows]
        sets_stmt = (
            select(SetDB.match_id, SetDB.numero, SetDB.score_a, SetDB.score_b)
            .where(SetDB.match_id.in_(match_id_list))
            .order_by(SetDB.match_id, SetDB.numero)
        )
        all_sets = list(self.session.execute(sets_stmt))

        # Regrouper les sets par match
        match_sets = defaultdict(list)
        for s in all_sets:
            match_sets[s.match_id].append(s)

        results = []
        for m in match_rows:
            sets_sorted = match_sets.get(m.id, [])
            if len(sets_sorted) < 3:
                continue

            score_a = 0
            score_b = 0
            max_deficit_a = 0
            max_deficit_b = 0

            for s in sets_sorted:
                if s.score_a is not None and s.score_b is not None:
                    if s.score_a > s.score_b:
                        score_a += 1
                    else:
                        score_b += 1
                    if score_b > score_a:
                        max_deficit_a = max(max_deficit_a, score_b - score_a)
                    if score_a > score_b:
                        max_deficit_b = max(max_deficit_b, score_a - score_b)

            winner_deficit = 0
            winner_name = ""
            loser_name = ""
            if m.sets_equipe_a > m.sets_equipe_b:
                winner_deficit = max_deficit_a
                winner_name = m.equipe_a_nom or "Équipe A"
                loser_name = m.equipe_b_nom or "Équipe B"
            elif m.sets_equipe_b > m.sets_equipe_a:
                winner_deficit = max_deficit_b
                winner_name = m.equipe_b_nom or "Équipe B"
                loser_name = m.equipe_a_nom or "Équipe A"

            if winner_deficit >= 1:
                set_scores = " / ".join(
                    f"{s.score_a}-{s.score_b}" for s in sets_sorted
                    if s.score_a is not None
                )
                results.append({
                    "match_id": m.id,
                    "code_match": m.code_match,
                    "date": m.date_match,
                    "equipe_a": m.equipe_a_nom or "?",
                    "equipe_b": m.equipe_b_nom or "?",
                    "score_sets": f"{m.sets_equipe_a}-{m.sets_equipe_b}",
                    "comeback_par": winner_name,
                    "adversaire": loser_name,
                    "deficit_remonte": winner_deficit,
                    "set_scores": set_scores,
                })

        results.sort(key=lambda x: (-x["deficit_remonte"], str(x["date"] or "")))
        return results[:limit]

    def matchs_les_plus_longs(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Matchs les plus longs (par durée totale ou nombre de sets)."""
        match_ids = self._filtered_match_ids(filters)

        eq_a_alias = EquipeDB.__table__.alias("eq_a_long")
        eq_b_alias = EquipeDB.__table__.alias("eq_b_long")

        stmt = (
            select(
                MatchDB.id,
                MatchDB.code_match,
                MatchDB.date_match,
                MatchDB.duree_totale,
                MatchDB.sets_equipe_a,
                MatchDB.sets_equipe_b,
                eq_a_alias.c.nom.label("equipe_a_nom"),
                eq_b_alias.c.nom.label("equipe_b_nom"),
                func.sum(SetDB.duree_minutes).label("duree_sets_total"),
                func.count(SetDB.id).label("nb_sets"),
                func.sum(func.coalesce(SetDB.score_a, 0) + func.coalesce(SetDB.score_b, 0)).label("total_points"),
            )
            .join(SetDB, SetDB.match_id == MatchDB.id)
            .outerjoin(eq_a_alias, MatchDB.equipe_a_id == eq_a_alias.c.id)
            .outerjoin(eq_b_alias, MatchDB.equipe_b_id == eq_b_alias.c.id)
            .where(MatchDB.match_joue == True)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = stmt.group_by(
            MatchDB.id, MatchDB.code_match, MatchDB.date_match,
            MatchDB.duree_totale, MatchDB.sets_equipe_a, MatchDB.sets_equipe_b,
            eq_a_alias.c.nom, eq_b_alias.c.nom,
        )

        # Sort by total points descending as proxy for longest matches, limit to top 100
        # (duree_totale is a string, so we sort by total_points in SQL, then re-sort in Python)
        stmt = stmt.order_by(desc(func.sum(func.coalesce(SetDB.score_a, 0) + func.coalesce(SetDB.score_b, 0)))).limit(100)

        rows = list(self.session.execute(stmt))
        results = []
        for r in rows:
            duree = None
            if r.duree_totale:
                try:
                    parts = r.duree_totale.replace("h", ":").replace("'", "").split(":")
                    if len(parts) == 2:
                        duree = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 1:
                        duree = int(parts[0])
                except (ValueError, IndexError):
                    pass
            if duree is None and r.duree_sets_total:
                duree = int(r.duree_sets_total)

            results.append({
                "match_id": r.id,
                "code_match": r.code_match,
                "date": r.date_match,
                "equipe_a": r.equipe_a_nom or "?",
                "equipe_b": r.equipe_b_nom or "?",
                "score_sets": f"{r.sets_equipe_a}-{r.sets_equipe_b}",
                "duree_minutes": duree,
                "nb_sets": r.nb_sets,
                "total_points": int(r.total_points) if r.total_points else 0,
            })

        results.sort(key=lambda x: (-(x["duree_minutes"] or 0), -(x["total_points"] or 0)))
        return results[:limit]

    def matchs_les_plus_de_points(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Matchs avec le plus grand nombre total de points."""
        match_ids = self._filtered_match_ids(filters)

        eq_a_alias = EquipeDB.__table__.alias("eq_a_pts")
        eq_b_alias = EquipeDB.__table__.alias("eq_b_pts")

        stmt = (
            select(
                MatchDB.id,
                MatchDB.code_match,
                MatchDB.date_match,
                MatchDB.sets_equipe_a,
                MatchDB.sets_equipe_b,
                eq_a_alias.c.nom.label("equipe_a_nom"),
                eq_b_alias.c.nom.label("equipe_b_nom"),
                func.sum(func.coalesce(SetDB.score_a, 0) + func.coalesce(SetDB.score_b, 0)).label("total_points"),
                func.count(SetDB.id).label("nb_sets"),
            )
            .join(SetDB, SetDB.match_id == MatchDB.id)
            .outerjoin(eq_a_alias, MatchDB.equipe_a_id == eq_a_alias.c.id)
            .outerjoin(eq_b_alias, MatchDB.equipe_b_id == eq_b_alias.c.id)
            .where(MatchDB.match_joue == True)
            .where(SetDB.score_a.isnot(None))
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = stmt.group_by(
            MatchDB.id, MatchDB.code_match, MatchDB.date_match,
            MatchDB.sets_equipe_a, MatchDB.sets_equipe_b,
            eq_a_alias.c.nom, eq_b_alias.c.nom,
        ).order_by(desc("total_points")).limit(limit)

        rows = list(self.session.execute(stmt))
        results = []
        for r in rows:
            results.append({
                "match_id": r.id,
                "code_match": r.code_match,
                "date": r.date_match,
                "equipe_a": r.equipe_a_nom or "?",
                "equipe_b": r.equipe_b_nom or "?",
                "score_sets": f"{r.sets_equipe_a}-{r.sets_equipe_b}",
                "total_points": int(r.total_points) if r.total_points else 0,
                "nb_sets": r.nb_sets,
            })
        return results

    # ─── Statistiques équipes ─────────────────────────

    def top_equipes_victoires(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Équipes avec le meilleur taux de victoire (min 5 matchs)."""
        match_ids = self._filtered_match_ids(filters)

        # Construire un CTE ou une requête avec CASE
        # Pour l'équipe A
        stmt_a = (
            select(
                MatchDB.equipe_a_id.label("equipe_id"),
                func.count(MatchDB.id).label("matchs"),
                func.sum(case((MatchDB.sets_equipe_a > MatchDB.sets_equipe_b, 1), else_=0)).label("victoires"),
            )
            .where(MatchDB.match_joue == True)
            .where(MatchDB.equipe_a_id.isnot(None))
        )
        if match_ids is not None:
            stmt_a = stmt_a.where(MatchDB.id.in_(match_ids))
        stmt_a = stmt_a.group_by(MatchDB.equipe_a_id)

        # Pour l'équipe B
        stmt_b = (
            select(
                MatchDB.equipe_b_id.label("equipe_id"),
                func.count(MatchDB.id).label("matchs"),
                func.sum(case((MatchDB.sets_equipe_b > MatchDB.sets_equipe_a, 1), else_=0)).label("victoires"),
            )
            .where(MatchDB.match_joue == True)
            .where(MatchDB.equipe_b_id.isnot(None))
        )
        if match_ids is not None:
            stmt_b = stmt_b.where(MatchDB.id.in_(match_ids))
        stmt_b = stmt_b.group_by(MatchDB.equipe_b_id)

        rows_a = list(self.session.execute(stmt_a))
        rows_b = list(self.session.execute(stmt_b))

        # Fusionner
        equipe_stats: Dict[int, Dict] = {}
        for r in rows_a:
            eid = r.equipe_id
            if eid not in equipe_stats:
                equipe_stats[eid] = {"matchs": 0, "victoires": 0}
            equipe_stats[eid]["matchs"] += r.matchs
            equipe_stats[eid]["victoires"] += int(r.victoires or 0)
        for r in rows_b:
            eid = r.equipe_id
            if eid not in equipe_stats:
                equipe_stats[eid] = {"matchs": 0, "victoires": 0}
            equipe_stats[eid]["matchs"] += r.matchs
            equipe_stats[eid]["victoires"] += int(r.victoires or 0)

        results = []
        # Batch-load equipe info for all qualifying IDs
        qualifying_ids = [
            eid
            for eid, st in equipe_stats.items()
            if st["matchs"] >= _MIN_MATCHES_FOR_TEAM_WINRATE
        ]
        if qualifying_ids:
            equipes = list(self.session.execute(
                select(EquipeDB.id, EquipeDB.nom, EquipeDB.niveau, EquipeDB.genre)
                .where(EquipeDB.id.in_(qualifying_ids))
            ))
            equipe_info = {e.id: e for e in equipes}
        else:
            equipe_info = {}

        for eid, st in equipe_stats.items():
            if st["matchs"] < _MIN_MATCHES_FOR_TEAM_WINRATE:
                continue
            equipe = equipe_info.get(eid)
            if not equipe:
                continue
            taux = round(100 * st["victoires"] / st["matchs"], 1)
            results.append({
                "id": eid,
                "nom": equipe.nom,
                "niveau": equipe.niveau,
                "genre": equipe.genre,
                "matchs": st["matchs"],
                "victoires": st["victoires"],
                "defaites": st["matchs"] - st["victoires"],
                "taux": taux,
            })

        results.sort(key=lambda x: (-x["taux"], -x["victoires"]))
        return results[:limit]

    # ─── Statistiques arbitres ────────────────────────

    def top_arbitres(self, filters: StatsFilters, limit: int = 10) -> List[Dict]:
        """Arbitres les plus actifs."""
        match_ids = self._filtered_match_ids(filters)

        stmt = (
            select(
                ArbitreDB.id,
                ArbitreDB.nom,
                ArbitreDB.prenom,
                ArbitreDB.ligue,
                func.count(distinct(ArbitreMatchDB.match_id)).label("nb_matchs"),
            )
            .join(ArbitreMatchDB, ArbitreMatchDB.arbitre_id == ArbitreDB.id)
            .join(MatchDB, ArbitreMatchDB.match_id == MatchDB.id)
            .where(MatchDB.match_joue == True)
        )
        if match_ids is not None:
            stmt = stmt.where(MatchDB.id.in_(match_ids))

        stmt = (
            stmt.group_by(ArbitreDB.id, ArbitreDB.nom, ArbitreDB.prenom, ArbitreDB.ligue)
            .order_by(desc("nb_matchs"))
            .limit(limit)
        )
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": r.id, "nom": r.nom, "prenom": r.prenom or "",
                "ligue": r.ligue or "", "valeur": r.nb_matchs,
            }
            for r in rows
        ]

    # ─── Agrégation principale ────────────────────────

    @staticmethod
    def _make_json_safe(obj: Any) -> Any:
        """Convertit récursivement les objets non-sérialisables en types JSON natifs.

        En particulier, ``datetime.date`` et ``datetime.datetime`` sont convertis
        en chaîne ISO 8601 (``"YYYY-MM-DD"`` / ``"YYYY-MM-DDTHH:MM:SS"``).
        """
        if isinstance(obj, dict):
            return {k: StatsAmusantesService._make_json_safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [StatsAmusantesService._make_json_safe(v) for v in obj]
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        return obj

    def get_all_stats(self, filters: StatsFilters) -> Dict[str, Any]:
        """Calcule toutes les statistiques amusantes avec les filtres donnés.

        Les valeurs retournées sont garanties JSON-sérialisables (les dates
        sont converties en chaînes ISO 8601).
        """
        # Calculer les séries une seule fois et réutiliser
        series_record = self.meilleure_serie_victoires(filters)
        series_actuelles = sorted(
            [s for s in series_record if s["serie_actuelle"] >= 2],
            key=lambda x: (-x["serie_actuelle"], -x["record"]),
        )[:10]

        result = {
            "top_matchs": self.top_joueurs_matchs(filters),
            "top_victoires": self.top_joueurs_victoires(filters),
            "top_defaites": self.top_joueurs_defaites(filters),
            "top_capitaines": self.top_joueurs_capitaine(filters),
            "top_liberos": self.top_joueurs_libero(filters),
            "top_fideles": self.top_joueurs_fideles(filters),
            "top_marqueurs": self.top_joueurs_marqueurs(filters),
            "top_serveurs": self.top_joueurs_serveurs(filters),
            "series_record": series_record,
            "series_actuelles": series_actuelles,
            "matchs_serres": self.matchs_les_plus_serres(filters),
            "sets_serres": self.sets_les_plus_serres(filters),
            "sets_domination": self.plus_gros_ecart_set(filters),
            "comebacks": self.comebacks(filters),
            "matchs_longs": self.matchs_les_plus_longs(filters),
            "matchs_points": self.matchs_les_plus_de_points(filters),
            "top_equipes": self.top_equipes_victoires(filters),
            "top_arbitres": self.top_arbitres(filters),
        }
        # Garantir la sérialisabilité JSON (dates → ISO strings)
        return self._make_json_safe(result)

    # ─── Données pour les filtres ────────────────────

    def get_filter_options(self) -> Dict[str, Any]:
        """Récupère les options disponibles pour les filtres."""
        saisons = list(self.session.execute(
            select(SaisonDB.id, SaisonDB.code).order_by(SaisonDB.code.desc())
        ))
        genres = list(self.session.scalars(
            select(distinct(CompetitionDB.genre))
            .where(CompetitionDB.genre.isnot(None))
            .order_by(CompetitionDB.genre)
        ))
        categories = list(self.session.scalars(
            select(distinct(CompetitionDB.categorie))
            .where(CompetitionDB.categorie.isnot(None))
            .order_by(CompetitionDB.categorie)
        ))
        departements = list(self.session.scalars(
            select(distinct(ClubDB.departement))
            .where(ClubDB.departement.isnot(None))
            .order_by(ClubDB.departement)
        ))
        niveaux_db = list(self.session.scalars(
            select(distinct(CompetitionDB.niveau))
            .where(CompetitionDB.niveau.isnot(None))
            .order_by(CompetitionDB.niveau)
        ))

        return {
            "saisons": [{"id": s.id, "code": s.code} for s in saisons],
            "genres": genres,
            "categories": categories,
            "departements": departements,
            "niveaux": niveaux_db,
            "niveaux_ordre": _NIVEAUX_LABELS,
        }

    # ─── Cache base de données ────────────────────────

    @staticmethod
    def build_filter_key(filters: StatsFilters) -> str:
        """Construit la clé canonique de cache pour une combinaison de filtres."""
        import json
        return json.dumps({
            "saison_id": filters.saison_id,
            "saison_ids": sorted(filters.saison_ids or []),
            "date_from": filters.date_from.isoformat() if filters.date_from else None,
            "date_to": filters.date_to.isoformat() if filters.date_to else None,
            "genre": filters.genre,
            "categorie": filters.categorie,
            "niveau_min": filters.niveau_min,
            "niveau_max": filters.niveau_max,
            "departement": filters.departement,
        }, sort_keys=True)

    def compute_and_store(self, filters: StatsFilters) -> Dict[str, Any]:
        """Calcule toutes les statistiques pour les filtres donnés et les stocke en base.

        Retourne le dictionnaire de statistiques (identique à ``get_all_stats``).
        """
        from pyvolley.database.repositories import StatsCacheRepository

        stats_data = self.get_all_stats(filters)
        filter_key = self.build_filter_key(filters)
        match_count, last_match_update = self._current_cache_signature(filters)

        repo = StatsCacheRepository(self.session)
        repo.upsert(
            filter_key,
            stats_data,
            match_count,
            last_match_update=last_match_update,
        )
        self.session.commit()
        return stats_data

    def get_cached_or_compute(self, filters: StatsFilters) -> tuple[Dict[str, Any], bool]:
        """Retourne les statistiques depuis le cache si disponible, sinon les calcule à la volée.

        Retourne ``(stats_data, from_cache)`` où ``from_cache`` indique si les données
        viennent du cache base de données.
        """
        from pyvolley.database.repositories import StatsCacheRepository

        filter_key = self.build_filter_key(filters)
        repo = StatsCacheRepository(self.session)
        current_match_count, last_match_update = self._current_cache_signature(filters)

        if not repo.is_stale(
            filter_key,
            current_match_count,
            current_last_match_update=last_match_update,
        ):
            entry = repo.get_by_filter_key(filter_key)
            if entry is not None:
                return entry.stats_data, True

        return self.get_all_stats(filters), False
