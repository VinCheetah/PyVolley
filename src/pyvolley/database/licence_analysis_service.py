"""
Service d'analyse du cycle de vie des licences et de la démographie des joueurs.

Permet de suivre :
- Les nouvelles licences (première apparition connue en compétition)
- Les reprises de licence (après une ou plusieurs saisons d'arrêt)
- Les renouvellements continus
- La pyramide des âges et la ventilation par genre et niveau
- Le taux de rétention d'une saison à l'autre
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import select, func, distinct, and_, or_, desc, asc
from sqlalchemy.orm import Session

from pyvolley.database.models import (
    JoueurDB, MatchDB, ParticipationMatchDB, CompetitionDB,
    SaisonDB, JoueurLicenceHistoryDB,
)
from pyvolley.database.repositories import JoueurLicenceHistoryRepository


@dataclass
class LicenceReport:
    saison_id: int
    saison_code: str
    total_joueurs_actifs: int = 0
    nouvelles_licences: int = 0
    reprises: int = 0
    continues: int = 0
    taux_renouvellement: float = 0.0
    pct_nouvelles: float = 0.0
    pct_reprises: float = 0.0
    pct_continues: float = 0.0
    par_genre: Dict[str, Dict[str, int]] = field(default_factory=dict)
    par_categorie: Dict[str, Dict[str, int]] = field(default_factory=dict)


@dataclass
class RetentionReport:
    from_saison_code: str
    to_saison_code: str
    joueurs_initiaux: int = 0
    joueurs_conserves: int = 0
    joueurs_perdus: int = 0
    taux_retention: float = 0.0


class LicenceAnalysisService:
    """Service d'analyse du statut des licences."""

    def __init__(self, session: Session):
        self.session = session
        self.repo = JoueurLicenceHistoryRepository(session)

    def compute_all_seasons_licence_history(self) -> int:
        """Calcule l'historique des licences pour toutes les saisons chronologiquement."""
        saisons = list(
            self.session.scalars(select(SaisonDB).order_by(SaisonDB.date_debut.asc().nulls_last(), SaisonDB.id.asc()))
        )
        total = 0
        for s in saisons:
            total += self.compute_licence_history(s.id)
        return total

    def compute_licence_history(self, saison_id: int) -> int:
        """Calcule le statut de licence (nouvelle, reprise, continue) pour une saison donnée."""
        target_saison = self.session.get(SaisonDB, saison_id)
        if not target_saison:
            return 0

        # Liste chronologique de toutes les saisons
        all_saisons = list(
            self.session.scalars(
                select(SaisonDB).order_by(SaisonDB.date_debut.asc().nulls_last(), SaisonDB.id.asc())
            )
        )
        saison_order = {s.id: idx for idx, s in enumerate(all_saisons)}
        current_idx = saison_order.get(saison_id, 0)

        # Récupérer pour chaque joueur actif de la saison ses participations passées
        active_players_subquery = (
            select(distinct(ParticipationMatchDB.joueur_id))
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(MatchDB.saison_id == saison_id, ParticipationMatchDB.joueur_id.is_not(None))
        )

        # Récupérer pour ces joueurs toutes les saisons où ils ont joué
        history_stmt = (
            select(
                ParticipationMatchDB.joueur_id,
                MatchDB.saison_id,
            )
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(ParticipationMatchDB.joueur_id.in_(active_players_subquery), MatchDB.saison_id.is_not(None))
            .group_by(ParticipationMatchDB.joueur_id, MatchDB.saison_id)
        )

        player_seasons_map: Dict[int, set[int]] = {}
        for j_id, s_id in self.session.execute(history_stmt):
            player_seasons_map.setdefault(j_id, set()).add(s_id)

        if not player_seasons_map:
            return 0

        # Récupérer les métadonnées de compétition (genre, catégorie, niveau) pour cette saison
        meta_stmt = (
            select(
                ParticipationMatchDB.joueur_id,
                CompetitionDB.genre,
                CompetitionDB.categorie,
                CompetitionDB.niveau,
            )
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .join(CompetitionDB, MatchDB.competition_id == CompetitionDB.id, isouter=True)
            .where(MatchDB.saison_id == saison_id, ParticipationMatchDB.joueur_id.is_not(None))
        )
        player_meta: Dict[int, Dict[str, Any]] = {}
        for j_id, genre, cat, niv in self.session.execute(meta_stmt):
            if j_id not in player_meta:
                player_meta[j_id] = {
                    "genre": genre,
                    "categorie": cat,
                    "niveau": niv,
                }

        count = 0
        now = datetime.now()

        for j_id, played_seasons in player_seasons_map.items():
            # Saisons jouées antérieures à la saison courante
            past_indices = [
                saison_order[sid]
                for sid in played_seasons
                if sid in saison_order and saison_order[sid] < current_idx
            ]

            if not past_indices:
                # Première saison connue dans la base
                type_licence = "nouvelle"
                premiere_saison_id = saison_id
                nb_absence = 0
            else:
                # Le joueur a déjà joué dans le passé
                min_idx = min(past_indices)
                premiere_saison_id = all_saisons[min_idx].id
                last_past_idx = max(past_indices)

                # Distance par rapport à la dernière saison jouée
                gap = current_idx - last_past_idx - 1
                if gap == 0:
                    type_licence = "continue"
                    nb_absence = 0
                else:
                    type_licence = "reprise"
                    nb_absence = gap

            meta = player_meta.get(j_id, {})
            payload = {
                "joueur_id": j_id,
                "saison_id": saison_id,
                "type_licence": type_licence,
                "premiere_saison_id": premiere_saison_id,
                "nb_saisons_absence": nb_absence,
                "genre_pratique": meta.get("genre"),
                "categorie_pratique": meta.get("categorie"),
                "niveau_max_saison": meta.get("niveau"),
                "computed_at": now,
            }
            self.repo.upsert(payload)
            count += 1
            if count % 1000 == 0:
                self.session.flush()

        self.session.commit()
        return count

    def get_licence_report(self, saison_id: int) -> LicenceReport:
        """Génère le rapport d'analyse des licences pour une saison."""
        saison = self.session.get(SaisonDB, saison_id)
        saison_code = saison.code if saison else f"Saison #{saison_id}"

        # Vérifier si les données existent déjà
        summary = self.repo.get_summary_by_saison(saison_id)
        if not summary:
            self.compute_licence_history(saison_id)
            summary = self.repo.get_summary_by_saison(saison_id)

        nouvelles = summary.get("nouvelle", 0)
        reprises = summary.get("reprise", 0)
        continues = summary.get("continue", 0)
        total = nouvelles + reprises + continues

        taux_renouv = round((continues / total) * 100, 1) if total > 0 else 0.0

        # Ventilation par genre
        genre_stmt = (
            select(
                func.coalesce(JoueurLicenceHistoryDB.genre_pratique, "Non spécifié").label("genre"),
                JoueurLicenceHistoryDB.type_licence,
                func.count().label("count"),
            )
            .where(JoueurLicenceHistoryDB.saison_id == saison_id)
            .group_by(JoueurLicenceHistoryDB.genre_pratique, JoueurLicenceHistoryDB.type_licence)
        )
        par_genre: Dict[str, Dict[str, int]] = {}
        for g, t, c in self.session.execute(genre_stmt):
            par_genre.setdefault(g, {})[t] = c

        # Ventilation par catégorie
        cat_stmt = (
            select(
                func.coalesce(JoueurLicenceHistoryDB.categorie_pratique, "Non spécifiée").label("cat"),
                JoueurLicenceHistoryDB.type_licence,
                func.count().label("count"),
            )
            .where(JoueurLicenceHistoryDB.saison_id == saison_id)
            .group_by(JoueurLicenceHistoryDB.categorie_pratique, JoueurLicenceHistoryDB.type_licence)
            .order_by(desc("count"))
            .limit(10)
        )
        par_cat: Dict[str, Dict[str, int]] = {}
        for cat, t, c in self.session.execute(cat_stmt):
            par_cat.setdefault(cat, {})[t] = c

        pct_nouv = round((nouvelles / total) * 100, 1) if total > 0 else 0.0
        pct_rep = round((reprises / total) * 100, 1) if total > 0 else 0.0
        pct_cont = round((continues / total) * 100, 1) if total > 0 else 0.0

        return LicenceReport(
            saison_id=saison_id,
            saison_code=saison_code,
            total_joueurs_actifs=total,
            nouvelles_licences=nouvelles,
            reprises=reprises,
            continues=continues,
            taux_renouvellement=taux_renouv,
            pct_nouvelles=pct_nouv,
            pct_reprises=pct_rep,
            pct_continues=pct_cont,
            par_genre=par_genre,
            par_categorie=par_cat,
        )

    def get_retention_flow(self, from_saison_id: int, to_saison_id: int) -> RetentionReport:
        """Calcule le taux de fidélisation/rétention entre deux saisons consécutives."""
        s1 = self.session.get(SaisonDB, from_saison_id)
        s2 = self.session.get(SaisonDB, to_saison_id)
        s1_code = s1.code if s1 else str(from_saison_id)
        s2_code = s2.code if s2 else str(to_saison_id)

        # Joueurs actifs en S1
        p1 = set(
            self.session.scalars(
                select(distinct(ParticipationMatchDB.joueur_id))
                .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
                .where(MatchDB.saison_id == from_saison_id, ParticipationMatchDB.joueur_id.is_not(None))
            )
        )

        # Joueurs actifs en S2
        p2 = set(
            self.session.scalars(
                select(distinct(ParticipationMatchDB.joueur_id))
                .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
                .where(MatchDB.saison_id == to_saison_id, ParticipationMatchDB.joueur_id.is_not(None))
            )
        )

        n_init = len(p1)
        conserves = len(p1.intersection(p2))
        perdus = n_init - conserves
        taux = round((conserves / n_init) * 100, 1) if n_init > 0 else 0.0

        return RetentionReport(
            from_saison_code=s1_code,
            to_saison_code=s2_code,
            joueurs_initiaux=n_init,
            joueurs_conserves=conserves,
            joueurs_perdus=perdus,
            taux_retention=taux,
        )
