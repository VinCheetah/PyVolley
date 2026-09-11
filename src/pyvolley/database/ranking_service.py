"""
Service de classements universels et multidimensionnels pour PyVolley.

Permet de classer n'importe quelle entité (joueurs, équipes, clubs) selon :
- Une métrique sportive au choix (points, victoires, ratios, aces, etc.)
- Une temporalité (saison spécifique ou carrière / historique global)
- Un périmètre géographique (national, ligue/région, département, club)
- Un périmètre sportif (genre, catégorie d'âge, niveau/échelon)
- Un rôle/poste (pour les joueurs : passeur, attaquant, libéro, etc.)
"""

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import select, func, desc, asc, and_, or_, case
from sqlalchemy.orm import Session, joinedload

from pyvolley.database.models import (
    JoueurDB, ClubDB, EquipeDB, CompetitionDB, MatchDB,
    JoueurSaisonStatsDB, JoueurCarriereStatsDB, EquipeSaisonStatsDB,
    ClubStatsDB, StatsCacheDB,
)


@dataclass
class RankingFilters:
    """Filtres pour le calcul et l'affichage des classements."""
    entity_type: str = "joueurs"  # "joueurs", "equipes", "clubs"
    metric: str = "total_points_gagnes"
    saison_id: Optional[int] = None  # None = Carrière / Global
    
    # Périmètre territorial
    departement: Optional[str] = None
    ligue: Optional[str] = None
    club_id: Optional[int] = None

    # Périmètre sportif
    genre: Optional[str] = None  # "M", "F", "Mixte"
    categorie: Optional[str] = None  # "Sénior", "M18", etc.
    niveau_echelon: Optional[str] = None  # "NATIONAL", "REGIONAL", "DEPARTEMENTAL"
    niveau: Optional[str] = None  # Nom du niveau ou code
    role_principal: Optional[str] = None  # Passeur, Libero, etc.

    # Seuils de représentativité & pagination
    min_matchs: int = 1
    page: int = 1
    per_page: int = 25
    order_direction: str = "desc"  # "desc" ou "asc"

    def cache_key(self) -> str:
        """Génère une clé unique et stable pour le cache."""
        raw = f"rank:{self.entity_type}:{self.metric}:{self.saison_id}:{self.departement}:" \
              f"{self.ligue}:{self.club_id}:{self.genre}:{self.categorie}:{self.niveau_echelon}:" \
              f"{self.niveau}:{self.role_principal}:{self.min_matchs}:{self.page}:{self.per_page}:{self.order_direction}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class RankingItem:
    """Ligne de résultat d'un classement."""
    rank: int
    entity_id: int
    nom: str
    nom_secondaire: Optional[str] = None
    metrique_valeur: Any = 0
    metrique_label: str = ""
    stats_complementaires: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RankingResult:
    """Résultat complet paginé d'un classement."""
    items: List[RankingItem]
    total_count: int
    page: int
    per_page: int
    total_pages: int
    filters: RankingFilters
    available_metrics: List[Dict[str, str]]


METRICS_CONFIG = {
    "joueurs": [
        {"id": "total_points_gagnes", "label": "Points marqués", "default": True, "format": "{:d} pts"},
        {"id": "total_matchs", "label": "Matchs joués", "format": "{:d} m"},
        {"id": "total_victoires", "label": "Victoires", "format": "{:d} V"},
        {"id": "ratio_victoires", "label": "Taux de victoire", "format": "{:.1%}", "min_matchs": 5},
        {"id": "total_aces", "label": "Aces / Services directs", "format": "{:d} aces"},
        {"id": "max_points_match", "label": "Record de points sur 1 match", "format": "{:d} pts"},
        {"id": "total_sets_joues", "label": "Sets disputés", "format": "{:d} sets"},
    ],
    "equipes": [
        {"id": "victoires", "label": "Victoires", "default": True, "format": "{:d} V"},
        {"id": "points_ffvb", "label": "Points au championnat", "format": "{:d} pts"},
        {"id": "ratio_victoires", "label": "Taux de victoire", "format": "{:.1%}", "min_matchs": 3},
        {"id": "ratio_sets", "label": "Ratio sets (Pour / Contre)", "format": "{:.2f}"},
        {"id": "ratio_points", "label": "Ratio points (Pour / Contre)", "format": "{:.3f}"},
        {"id": "matchs_joues", "label": "Matchs joués", "format": "{:d} m"},
        {"id": "serie_victoires_max", "label": "Plus longue série de victoires", "format": "{:d} consécutives"},
    ],
    "clubs": [
        {"id": "nb_victoires", "label": "Victoires cumulées", "default": True, "format": "{:d} V"},
        {"id": "ratio_victoires", "label": "Taux de victoires global", "format": "{:.1%}"},
        {"id": "nb_equipes_engagees", "label": "Nombre d'équipes engagées", "format": "{:d} éq."},
        {"id": "nb_matchs_joues", "label": "Volume de matchs joués", "format": "{:d} m"},
        {"id": "nb_joueurs_distincts", "label": "Joueurs actifs", "format": "{:d} joueurs"},
    ],
}


class RankingService:
    """Moteur de requêtes et de précalculs pour les classements."""

    def __init__(self, session: Session):
        self.session = session

    @classmethod
    def get_metrics_for_entity(cls, entity_type: str) -> List[Dict[str, str]]:
        """Renvoie les métriques disponibles pour une entité donnée."""
        return METRICS_CONFIG.get(entity_type, [])

    def get_ranking(self, filters: RankingFilters, use_cache: bool = True) -> RankingResult:
        """Calcule et retourne le classement demandé avec pagination et rangs exacts."""
        # 1. Vérification du cache
        cache_key = filters.cache_key()
        if use_cache:
            cached = self.session.scalar(
                select(StatsCacheDB).where(StatsCacheDB.filter_key == cache_key)
            )
            if cached and cached.stats_data:
                data = cached.stats_data
                items = [
                    RankingItem(
                        rank=it["rank"],
                        entity_id=it["entity_id"],
                        nom=it["nom"],
                        nom_secondaire=it.get("nom_secondaire"),
                        metrique_valeur=it["metrique_valeur"],
                        metrique_label=it.get("metrique_label", ""),
                        stats_complementaires=it.get("stats_complementaires", {}),
                        metadata=it.get("metadata", {}),
                    )
                    for it in data.get("items", [])
                ]
                return RankingResult(
                    items=items,
                    total_count=data.get("total_count", 0),
                    page=filters.page,
                    per_page=filters.per_page,
                    total_pages=data.get("total_pages", 1),
                    filters=filters,
                    available_metrics=self.get_metrics_for_entity(filters.entity_type),
                )

        # 2. Construction de la requête selon l'entité
        if filters.entity_type == "joueurs":
            items, total_count = self._rank_joueurs(filters)
        elif filters.entity_type == "equipes":
            items, total_count = self._rank_equipes(filters)
        elif filters.entity_type == "clubs":
            items, total_count = self._rank_clubs(filters)
        else:
            items, total_count = [], 0

        total_pages = max(1, (total_count + filters.per_page - 1) // filters.per_page)
        res = RankingResult(
            items=items,
            total_count=total_count,
            page=filters.page,
            per_page=filters.per_page,
            total_pages=total_pages,
            filters=filters,
            available_metrics=self.get_metrics_for_entity(filters.entity_type),
        )

        # 3. Sauvegarde en cache
        if use_cache and total_count > 0:
            try:
                cache_dict = {
                    "items": [
                        {
                            "rank": it.rank,
                            "entity_id": it.entity_id,
                            "nom": it.nom,
                            "nom_secondaire": it.nom_secondaire,
                            "metrique_valeur": it.metrique_valeur,
                            "metrique_label": it.metrique_label,
                            "stats_complementaires": it.stats_complementaires,
                            "metadata": it.metadata,
                        }
                        for it in items
                    ],
                    "total_count": total_count,
                    "total_pages": total_pages,
                }
                existing_cache = self.session.scalar(
                    select(StatsCacheDB).where(StatsCacheDB.filter_key == cache_key)
                )
                if existing_cache:
                    existing_cache.stats_data = cache_dict
                    existing_cache.computed_at = datetime.now()
                else:
                    self.session.add(
                        StatsCacheDB(filter_key=cache_key, stats_data=cache_dict, computed_at=datetime.now())
                    )
                self.session.flush()
            except Exception:
                pass  # Ne pas bloquer si le cache échoue

        return res

    def _rank_joueurs(self, filters: RankingFilters) -> Tuple[List[RankingItem], int]:
        """Classement des joueurs (sur saison ou carrière)."""
        is_carriere = filters.saison_id is None
        table = JoueurCarriereStatsDB if is_carriere else JoueurSaisonStatsDB

        if is_carriere:
            col_map = {
                "total_points_gagnes": "total_points_gagnes",
                "total_matchs": "total_matchs",
                "total_victoires": "total_victoires",
                "ratio_victoires": "total_victoires",
                "total_aces": "total_services",
                "total_sets_joues": "total_sets",
                "max_points_match": "max_points_match",
            }
            matchs_col = JoueurCarriereStatsDB.total_matchs
            attr_name = col_map.get(filters.metric, "total_points_gagnes")
            metric_col = getattr(JoueurCarriereStatsDB, attr_name, JoueurCarriereStatsDB.total_points_gagnes)
        else:
            col_map = {
                "total_points_gagnes": "points_gagnes",
                "total_matchs": "matchs_joues",
                "total_victoires": "victoires",
                "ratio_victoires": "victoires",
                "total_aces": "points_service",
                "total_sets_joues": "sets_joues",
                "max_points_match": "points_gagnes",
            }
            matchs_col = JoueurSaisonStatsDB.matchs_joues
            attr_name = col_map.get(filters.metric, "points_gagnes")
            metric_col = getattr(JoueurSaisonStatsDB, attr_name, JoueurSaisonStatsDB.points_gagnes)

        # Base query
        stmt = select(table).join(JoueurDB, table.joueur_id == JoueurDB.id)

        if not is_carriere:
            stmt = stmt.where(table.saison_id == filters.saison_id)

        # Filtre sur le volume minimum de matchs
        min_m = max(filters.min_matchs, 1)
        stmt = stmt.where(matchs_col >= min_m)

        # Filtre rôle
        if filters.role_principal:
            stmt = stmt.where(table.role_principal == filters.role_principal)

        # Filtres géographique ou club
        if filters.club_id or filters.departement or filters.ligue:
            if not is_carriere:
                stmt = stmt.join(EquipeDB, table.equipe_id == EquipeDB.id, isouter=True)
                stmt = stmt.join(ClubDB, EquipeDB.club_id == ClubDB.id, isouter=True)
                if filters.club_id:
                    stmt = stmt.where(EquipeDB.club_id == filters.club_id)
                if filters.departement:
                    stmt = stmt.where(ClubDB.departement == filters.departement)
                if filters.ligue:
                    stmt = stmt.where(ClubDB.ligue == filters.ligue)

        # Filtres sportifs (genre, niveau)
        if filters.genre or filters.niveau or filters.niveau_echelon or filters.categorie:
            if not is_carriere:
                stmt = stmt.join(CompetitionDB, table.competition_id == CompetitionDB.id, isouter=True)
                if filters.genre:
                    g = filters.genre.upper().strip()
                    stmt = stmt.where(or_(func.upper(CompetitionDB.genre) == g, CompetitionDB.genre.ilike(f"{g}%")))
                if filters.categorie:
                    stmt = stmt.where(CompetitionDB.categorie.ilike(f"%{filters.categorie}%"))
                if filters.niveau:
                    stmt = stmt.where(CompetitionDB.niveau.ilike(f"%{filters.niveau}%"))
            else:
                if filters.categorie:
                    stmt = stmt.where(table.best_category_label.ilike(f"%{filters.categorie}%"))
                if filters.niveau:
                    stmt = stmt.where(table.max_niveau_label.ilike(f"%{filters.niveau}%"))

        # Compte total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_count = self.session.scalar(count_stmt) or 0

        # Tri et pagination
        order = desc(metric_col) if filters.order_direction == "desc" else asc(metric_col)
        if is_carriere:
            stmt = stmt.options(joinedload(table.joueur)).order_by(order, desc(matchs_col))
        else:
            stmt = stmt.options(
                joinedload(table.joueur),
                joinedload(table.equipe).joinedload(EquipeDB.club),
            ).order_by(order, desc(matchs_col))

        offset = (filters.page - 1) * filters.per_page
        stmt = stmt.offset(offset).limit(filters.per_page)

        records = list(self.session.scalars(stmt).unique())

        items = []
        for idx, rec in enumerate(records):
            rank = offset + idx + 1
            joueur = rec.joueur
            nom_complet = joueur.nom_complet if joueur else f"Joueur #{rec.joueur_id}"
            if is_carriere:
                club_nom = f"{rec.clubs_frequentes_count} club(s)" if rec.clubs_frequentes_count else ""
            else:
                club_nom = rec.equipe.club.nom if (rec.equipe and rec.equipe.club) else ""

            val = getattr(rec, attr_name, 0)
            if filters.metric == "ratio_victoires":
                m_tot = rec.total_matchs if is_carriere else rec.matchs_joues
                v_tot = rec.total_victoires if is_carriere else rec.victoires
                ratio = (v_tot / max(1, m_tot)) if m_tot > 0 else 0.0
                val_formatted = f"{ratio * 100:.1f} %"
            else:
                val_formatted = str(val)

            m_count = rec.total_matchs if is_carriere else rec.matchs_joues
            v_count = rec.total_victoires if is_carriere else rec.victoires
            p_count = rec.total_points_gagnes if is_carriere else rec.points_gagnes
            a_count = rec.total_services if is_carriere else rec.points_service

            items.append(
                RankingItem(
                    rank=rank,
                    entity_id=rec.joueur_id,
                    nom=nom_complet,
                    nom_secondaire=club_nom,
                    metrique_valeur=val,
                    metrique_label=val_formatted,
                    stats_complementaires={
                        "Matchs": m_count,
                        "Victoires": v_count,
                        "Points": p_count,
                        "Aces": a_count,
                        "Poste": rec.role_principal or "Non déterminé",
                    },
                    metadata={
                        "licence": joueur.licence if joueur else None,
                        "club_id": joueur.club_id if joueur else None,
                    },
                )
            )

        return items, total_count

    def _rank_equipes(self, filters: RankingFilters) -> Tuple[List[RankingItem], int]:
        """Classement des équipes par saison."""
        saison_id = filters.saison_id
        if not saison_id:
            latest_season = self.session.scalar(select(EquipeSaisonStatsDB.saison_id).order_by(EquipeSaisonStatsDB.saison_id.desc()).limit(1))
            saison_id = latest_season or 1

        metric_name = filters.metric or "victoires"
        if not hasattr(EquipeSaisonStatsDB, metric_name):
            metric_name = "victoires"
        metric_col = getattr(EquipeSaisonStatsDB, metric_name)

        stmt = (
            select(EquipeSaisonStatsDB)
            .join(EquipeDB, EquipeSaisonStatsDB.equipe_id == EquipeDB.id)
            .join(ClubDB, EquipeDB.club_id == ClubDB.id, isouter=True)
            .where(EquipeSaisonStatsDB.saison_id == saison_id)
        )

        min_m = max(filters.min_matchs, 1)
        stmt = stmt.where(EquipeSaisonStatsDB.matchs_joues >= min_m)

        if filters.club_id:
            stmt = stmt.where(EquipeDB.club_id == filters.club_id)
        if filters.departement:
            stmt = stmt.where(ClubDB.departement == filters.departement)
        if filters.ligue:
            stmt = stmt.where(ClubDB.ligue == filters.ligue)

        if filters.genre or filters.categorie or filters.niveau or filters.niveau_echelon:
            stmt = stmt.join(CompetitionDB, EquipeSaisonStatsDB.competition_id == CompetitionDB.id, isouter=True)
            if filters.genre:
                g = filters.genre.upper().strip()
                stmt = stmt.where(or_(func.upper(CompetitionDB.genre) == g, CompetitionDB.genre.ilike(f"{g}%")))
            if filters.categorie:
                stmt = stmt.where(CompetitionDB.categorie.ilike(f"%{filters.categorie}%"))
            if filters.niveau:
                stmt = stmt.where(CompetitionDB.niveau.ilike(f"%{filters.niveau}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_count = self.session.scalar(count_stmt) or 0

        order = desc(metric_col) if filters.order_direction == "desc" else asc(metric_col)
        stmt = stmt.options(
            joinedload(EquipeSaisonStatsDB.equipe).joinedload(EquipeDB.club),
            joinedload(EquipeSaisonStatsDB.competition),
        ).order_by(order, desc(EquipeSaisonStatsDB.ratio_sets), desc(EquipeSaisonStatsDB.ratio_points))

        offset = (filters.page - 1) * filters.per_page
        stmt = stmt.offset(offset).limit(filters.per_page)

        records = list(self.session.scalars(stmt).unique())

        items = []
        for idx, rec in enumerate(records):
            rank = offset + idx + 1
            equipe = rec.equipe
            club = equipe.club if equipe else None
            nom = equipe.nom if equipe else f"Équipe #{rec.equipe_id}"
            club_nom = club.nom if club else "Club indéterminé"

            val = getattr(rec, metric_name, 0)
            if metric_name == "ratio_victoires" and isinstance(val, (int, float)):
                val_formatted = f"{val * 100:.1f} %"
            elif "ratio" in metric_name and isinstance(val, (int, float)):
                val_formatted = f"{val:.2f}"
            else:
                val_formatted = str(val)

            items.append(
                RankingItem(
                    rank=rank,
                    entity_id=rec.equipe_id,
                    nom=nom,
                    nom_secondaire=club_nom,
                    metrique_valeur=val,
                    metrique_label=val_formatted,
                    stats_complementaires={
                        "Victoires": rec.victoires,
                        "Défaites": rec.defaites,
                        "Points FFVB": rec.points_ffvb,
                        "Ratio Sets": f"{rec.ratio_sets:.2f}",
                        "Matchs": rec.matchs_joues,
                    },
                    metadata={
                        "club_id": club.id if club else None,
                        "competition": rec.competition.nom if rec.competition else None,
                    },
                )
            )

        return items, total_count

    def _rank_clubs(self, filters: RankingFilters) -> Tuple[List[RankingItem], int]:
        """Classement des clubs (par saison ou global)."""
        metric_name = filters.metric or "nb_victoires"
        if not hasattr(ClubStatsDB, metric_name):
            metric_name = "nb_victoires"
        metric_col = getattr(ClubStatsDB, metric_name)

        stmt = select(ClubStatsDB).join(ClubDB, ClubStatsDB.club_id == ClubDB.id)

        if filters.saison_id is not None:
            stmt = stmt.where(ClubStatsDB.saison_id == filters.saison_id)
        else:
            stmt = stmt.where(ClubStatsDB.saison_id.is_(None))

        if filters.departement:
            stmt = stmt.where(ClubDB.departement == filters.departement)
        if filters.ligue:
            stmt = stmt.where(ClubDB.ligue == filters.ligue)
        if filters.club_id:
            stmt = stmt.where(ClubStatsDB.club_id == filters.club_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_count = self.session.scalar(count_stmt) or 0

        order = desc(metric_col) if filters.order_direction == "desc" else asc(metric_col)
        stmt = stmt.options(joinedload(ClubStatsDB.club)).order_by(order, desc(ClubStatsDB.nb_matchs_joues))

        offset = (filters.page - 1) * filters.per_page
        stmt = stmt.offset(offset).limit(filters.per_page)

        records = list(self.session.scalars(stmt).unique())

        items = []
        for idx, rec in enumerate(records):
            rank = offset + idx + 1
            club = rec.club
            nom = club.nom if club else f"Club #{rec.club_id}"
            geo_label = f"{club.ville or ''} ({club.departement or ''})".strip() if club else ""

            val = getattr(rec, metric_name, 0)
            if metric_name == "ratio_victoires" and isinstance(val, (int, float)):
                val_formatted = f"{val * 100:.1f} %"
            else:
                val_formatted = str(val)

            items.append(
                RankingItem(
                    rank=rank,
                    entity_id=rec.club_id,
                    nom=nom,
                    nom_secondaire=geo_label or club.ligue,
                    metrique_valeur=val,
                    metrique_label=val_formatted,
                    stats_complementaires={
                        "Victoires": rec.nb_victoires,
                        "Défaites": rec.nb_defaites,
                        "Équipes": rec.nb_equipes_engagees,
                        "Matchs": rec.nb_matchs_joues,
                        "Joueurs": rec.nb_joueurs_distincts,
                    },
                    metadata={
                        "code_ffvb": club.code_ffvb if club else None,
                        "departement": club.departement if club else None,
                        "ligue": club.ligue if club else None,
                    },
                )
            )

        return items, total_count
