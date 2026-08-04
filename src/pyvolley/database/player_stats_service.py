"""Service de persistance des statistiques détaillées joueur par match."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from pyvolley.analysis.joueur_stats import analyze_joueur_match, build_set_timeline
from pyvolley.analysis.role_inference import infer_team_roles
from pyvolley.analysis.models import JoueurMatchDetailedStats
from pyvolley.database.converters import match_db_to_core, _sanitize_joueur_licence
from pyvolley.database.models import MatchDB
from pyvolley.database.repositories import JoueurMatchStatsRepository

logger = logging.getLogger(__name__)


class JoueurMatchStatsService:
    """Calcule et persiste les statistiques détaillées des joueurs d'un match."""

    def __init__(self, session: Session):
        self.session = session
        self.repo = JoueurMatchStatsRepository(session)

    def compute_and_store_for_match(self, match_db: MatchDB, *, force: bool = False) -> int:
        """Calcule et stocke les stats détaillées de tous les joueurs d'un match.

        Returns:
            Nombre de lignes persistées.
        """
        if not match_db.has_details:
            return 0

        participants = list(match_db.participations or [])
        if not participants:
            self.repo.replace_for_match(
                match_db.id,
                [],
                match_updated_at=match_db.updated_at,
            )
            return 0

        valid_participants = [
            p
            for p in participants
            if p.joueur and p.joueur.licence
        ]
        if not valid_participants:
            self.repo.replace_for_match(
                match_db.id,
                [],
                match_updated_at=match_db.updated_at,
            )
            return 0

        expected_ids = [p.joueur_id for p in valid_participants]
        if not force and not self.repo.is_match_stale(
            match_db.id,
            expected_joueur_ids=expected_ids,
            match_updated_at=match_db.updated_at,
        ):
            return len(expected_ids)

        participants_a = [p for p in valid_participants if p.equipe_id == match_db.equipe_a_id]
        participants_b = [p for p in valid_participants if p.equipe_id == match_db.equipe_b_id]
        match_core = match_db_to_core(match_db, participants_a, participants_b)

        # Pré-calculer les rôles d'équipe et les timelines de set une seule fois par match
        precomputed_roles_a = infer_team_roles(match_core, "A")
        precomputed_roles_b = infer_team_roles(match_core, "B")
        precomputed_timelines = {s.numero: build_set_timeline(s) for s in match_core.sets}

        rows: list[dict] = []
        for participation in valid_participants:
            try:
                licence_key = _sanitize_joueur_licence(participation.joueur.licence)
                is_side_a = (participation.equipe_id == match_db.equipe_a_id)
                precomputed_roles = precomputed_roles_a if is_side_a else precomputed_roles_b

                stats = analyze_joueur_match(
                    match_core,
                    licence_key,
                    precomputed_roles=precomputed_roles,
                    precomputed_timelines=precomputed_timelines,
                )
                if not stats:
                    continue
                rows.append(
                    {
                        "joueur_id": participation.joueur_id,
                        "equipe_id": participation.equipe_id,
                        "stats_data": stats.model_dump(mode="json"),
                    }
                )
            except Exception as exc:
                logger.warning(
                    "Erreur lors du calcul des stats du joueur %s (match %s): %s",
                    participation.joueur_id, match_db.id, exc,
                )

        self.repo.replace_for_match(
            match_db.id,
            rows,
            match_updated_at=match_db.updated_at,
        )
        return len(rows)

    def get_match_stats_grouped(self, match_id: int) -> tuple[list[dict], list[dict]]:
        """Retourne les stats d'un match groupées par équipe A/B."""
        match_db = self.session.get(MatchDB, match_id)
        if not match_db:
            return [], []

        entries = self.repo.get_for_match(match_id)
        stats_a: list[dict] = []
        stats_b: list[dict] = []

        for entry in entries:
            side = entry.stats_data.get("side")
            if side not in {"A", "B"}:
                if entry.equipe_id is not None and entry.equipe_id == match_db.equipe_a_id:
                    side = "A"
                elif entry.equipe_id is not None and entry.equipe_id == match_db.equipe_b_id:
                    side = "B"
            payload = {"joueur_id": entry.joueur_id, "stats": entry.stats_data}
            if side == "A":
                stats_a.append(payload)
            elif side == "B":
                stats_b.append(payload)

        return stats_a, stats_b

    def get_joueur_match_stats(self, joueur_id: int, match_id: int) -> JoueurMatchDetailedStats | None:
        """Retourne les stats détaillées persistées d'un joueur pour un match."""
        entry = self.repo.get_for_match_joueur(match_id, joueur_id)
        if not entry:
            return None
        return JoueurMatchDetailedStats.model_validate(entry.stats_data)

    def get_joueur_all_stats(self, joueur_id: int, limit: int = 500) -> list[JoueurMatchDetailedStats]:
        """Retourne toutes les stats détaillées persistées d'un joueur."""
        rows = self.repo.get_for_joueur(joueur_id, limit=limit)
        return [JoueurMatchDetailedStats.model_validate(r.stats_data) for r in rows]
