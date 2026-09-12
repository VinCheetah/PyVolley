"""Service de diffusion réseau itérative pour l'inférence fiable des rôles joueurs.

Ce service implémente un algorithme de propagation de croyances (Belief Propagation)
sur le graphe bipartite Joueurs - Matchs / Équipes :
1. Passe 0 : Résolution locale de chaque match (feuille de match, libéro, rotations, changements).
2. Agrégation des priors : Calcul de la distribution de rôle par joueur (saison et carrière).
3. Passes 1..N : Réinjection des priors et propagation des certitudes entre coéquipiers
   via les contraintes de rotation opposée et de composition réglementaire.
4. Détection de convergence, calcul des taux de confiance calibrés et persistance.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional, Sequence, Any

from sqlalchemy import select, and_
from sqlalchemy.orm import Session, selectinload

from pyvolley.analysis.models import RoleInference
from pyvolley.analysis.role_inference import infer_team_roles
from pyvolley.database.converters import match_db_to_core, _sanitize_joueur_licence
from pyvolley.database.models import (
    MatchDB,
    ParticipationMatchDB,
    JoueurDB,
    JoueurMatchStatsDB,
    SaisonDB,
)
from pyvolley.database.repositories import JoueurMatchStatsRepository
from pyvolley.database.rollup_service import RollupStatsService, _chunked

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IterationMetrics:
    """Métriques d'une passe de diffusion réseau."""

    iteration: int
    changed_roles_count: int = 0
    average_confidence: float = 0.0
    high_confidence_count: int = 0
    atypical_roles_count: int = 0
    roles_distribution: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class DiffusionReport:
    """Bilan complet de l'exécution de la diffusion réseau."""

    total_matches: int = 0
    total_players: int = 0
    total_player_matches: int = 0
    iterations_run: int = 0
    converged: bool = False
    iterations_history: list[IterationMetrics] = field(default_factory=list)
    final_role_distribution: dict[str, int] = field(default_factory=dict)
    average_final_confidence: float = 0.0
    atypical_match_roles: int = 0


class RoleDiffusionService:
    """Orchestrateur de diffusion réseau multi-passes pour l'évaluation des rôles."""

    def __init__(self, session: Session):
        self.session = session
        self.match_stats_repo = JoueurMatchStatsRepository(session)
        self.rollup_service = RollupStatsService(session)

    def run_diffusion(
        self,
        *,
        saison_ids: Optional[Sequence[int]] = None,
        competition_ids: Optional[Sequence[int]] = None,
        equipe_ids: Optional[Sequence[int]] = None,
        match_ids: Optional[Sequence[int]] = None,
        max_iterations: int = 3,
        commit: bool = True,
        progress_callback: Optional[Any] = None,
    ) -> DiffusionReport:
        """Exécute la diffusion réseau sur le sous-ensemble de matchs sélectionné."""
        report = DiffusionReport()

        # 1. Charger les matchs et participations
        stmt = (
            select(MatchDB)
            .options(
                selectinload(MatchDB.participations).selectinload(ParticipationMatchDB.joueur),
                selectinload(MatchDB.sets),
            )
            .where(MatchDB.has_details == True, MatchDB.match_joue == True)  # noqa: E712
        )
        if match_ids:
            stmt = stmt.where(MatchDB.id.in_(match_ids))
        if saison_ids:
            stmt = stmt.where(MatchDB.saison_id.in_(saison_ids))
        if competition_ids:
            stmt = stmt.where(MatchDB.competition_id.in_(competition_ids))

        matches = list(self.session.scalars(stmt).all())
        if not matches:
            return report

        # Préparer les données en mémoire
        # match_info: id -> {core_match, team_a_id, team_b_id, players_by_side: {side: {num: joueur_id}}}
        match_cache: dict[int, dict] = {}
        all_joueur_ids: set[int] = set()
        total_pm_count = 0

        for m_db in matches:
            participants = [p for p in (m_db.participations or []) if p.joueur and p.joueur.licence]
            if not participants:
                continue

            parts_a = [p for p in participants if p.equipe_id == m_db.equipe_a_id]
            parts_b = [p for p in participants if p.equipe_id == m_db.equipe_b_id]

            core_match = match_db_to_core(m_db, parts_a, parts_b)

            side_map: dict[str, dict[str, int]] = {"A": {}, "B": {}}
            for p in parts_a:
                num = str(p.numero_maillot or "").strip().lstrip("0") or "0"
                side_map["A"][num] = p.joueur_id
                all_joueur_ids.add(p.joueur_id)
                total_pm_count += 1
            for p in parts_b:
                num = str(p.numero_maillot or "").strip().lstrip("0") or "0"
                side_map["B"][num] = p.joueur_id
                all_joueur_ids.add(p.joueur_id)
                total_pm_count += 1

            match_cache[m_db.id] = {
                "db": m_db,
                "core": core_match,
                "saison_id": m_db.saison_id,
                "side_map": side_map,
            }

        report.total_matches = len(match_cache)
        report.total_players = len(all_joueur_ids)
        report.total_player_matches = total_pm_count

        # Structure de stockage des croyances actuelles
        # current_beliefs: (match_id, side, num) -> RoleInference
        current_beliefs: dict[tuple[int, str, str], RoleInference] = {}

        # ── PASSE 0 : Inférence locale sans priors ───────────────────────
        if progress_callback:
            progress_callback(0, max_iterations, "Passe 0 : Évidences locales...")

        for m_id, m_data in match_cache.items():
            core_match = m_data["core"]
            roles_a = infer_team_roles(core_match, "A", player_priors=None)
            roles_b = infer_team_roles(core_match, "B", player_priors=None)

            for num, role_inf in roles_a.items():
                current_beliefs[(m_id, "A", num)] = role_inf
            for num, role_inf in roles_b.items():
                current_beliefs[(m_id, "B", num)] = role_inf

        metrics_p0 = self._evaluate_metrics(0, current_beliefs, previous_beliefs=None)
        report.iterations_history.append(metrics_p0)

        # ── PASSES 1..N : Diffusion itérative avec priors et coéquipiers ──
        converged = False
        prev_beliefs = current_beliefs

        for iteration in range(1, max_iterations + 1):
            if progress_callback:
                progress_callback(
                    iteration,
                    max_iterations,
                    f"Passe {iteration} : Diffusion réseau ({metrics_p0.changed_roles_count} ajustements)...",
                )

            # 1. Calculer les priors joueurs (saison et carrière)
            player_season_priors, player_career_priors = self._aggregate_player_priors(
                match_cache, current_beliefs
            )

            # 2. Réévaluer les rôles de match en injectant les priors des coéquipiers
            new_beliefs: dict[tuple[int, str, str], RoleInference] = {}
            for m_id, m_data in match_cache.items():
                core_match = m_data["core"]
                s_id = m_data["saison_id"]

                # Préparer les priors par numéro pour l'équipe A
                priors_a: dict[str, dict[str, float]] = {}
                for num, j_id in m_data["side_map"]["A"].items():
                    prior_dist = (
                        player_season_priors.get(j_id, {}).get(s_id)
                        or player_career_priors.get(j_id)
                    )
                    if prior_dist:
                        priors_a[num] = prior_dist

                # Préparer les priors par numéro pour l'équipe B
                priors_b: dict[str, dict[str, float]] = {}
                for num, j_id in m_data["side_map"]["B"].items():
                    prior_dist = (
                        player_season_priors.get(j_id, {}).get(s_id)
                        or player_career_priors.get(j_id)
                    )
                    if prior_dist:
                        priors_b[num] = prior_dist

                roles_a = infer_team_roles(core_match, "A", player_priors=priors_a)
                roles_b = infer_team_roles(core_match, "B", player_priors=priors_b)

                for num, role_inf in roles_a.items():
                    new_beliefs[(m_id, "A", num)] = role_inf
                for num, role_inf in roles_b.items():
                    new_beliefs[(m_id, "B", num)] = role_inf

            # 3. Mesurer l'évolution et tester la convergence
            metrics = self._evaluate_metrics(iteration, new_beliefs, previous_beliefs=prev_beliefs)
            report.iterations_history.append(metrics)
            report.iterations_run = iteration

            if metrics.changed_roles_count == 0:
                converged = True
                break

            prev_beliefs = new_beliefs
            current_beliefs = new_beliefs

        report.converged = converged
        final_metrics = report.iterations_history[-1]
        report.final_role_distribution = final_metrics.roles_distribution
        report.average_final_confidence = final_metrics.average_confidence
        report.atypical_match_roles = final_metrics.atypical_roles_count

        # ── PERSISTANCE SI DEMANDÉE ──────────────────────────────────────
        if commit:
            self._persist_results(match_cache, current_beliefs)

        return report

    def _aggregate_player_priors(
        self,
        match_cache: dict[int, dict],
        beliefs: dict[tuple[int, str, str], RoleInference],
    ) -> tuple[dict[int, dict[int, dict[str, float]]], dict[int, dict[str, float]]]:
        """Agrège les croyances actuelles en distributions de rôles par joueur."""
        # player_season_counts: j_id -> s_id -> Counter
        player_season_counts: dict[int, dict[int, Counter[str]]] = defaultdict(
            lambda: defaultdict(Counter)
        )
        player_career_counts: dict[int, Counter[str]] = defaultdict(Counter)

        for (m_id, side, num), role_inf in beliefs.items():
            if not role_inf.role_principal:
                continue
            m_info = match_cache.get(m_id)
            if not m_info:
                continue
            j_id = m_info["side_map"][side].get(num)
            if not j_id:
                continue

            s_id = m_info["saison_id"]
            role = role_inf.role_principal
            # Pondérer par la confiance du match
            weight = max(0.5, role_inf.role_confiance)
            player_season_counts[j_id][s_id][role] += weight
            player_career_counts[j_id][role] += weight

        # Convertir en distributions normalisées
        season_priors: dict[int, dict[int, dict[str, float]]] = defaultdict(dict)
        for j_id, seasons in player_season_counts.items():
            for s_id, counts in seasons.items():
                tot = sum(counts.values())
                if tot > 0:
                    season_priors[j_id][s_id] = {
                        r: round(cnt / tot, 4) for r, cnt in counts.items()
                    }

        career_priors: dict[int, dict[str, float]] = {}
        for j_id, counts in player_career_counts.items():
            tot = sum(counts.values())
            if tot > 0:
                career_priors[j_id] = {
                    r: round(cnt / tot, 4) for r, cnt in counts.items()
                }

        return season_priors, career_priors

    def _evaluate_metrics(
        self,
        iteration: int,
        beliefs: dict[tuple[int, str, str], RoleInference],
        previous_beliefs: Optional[dict[tuple[int, str, str], RoleInference]],
    ) -> IterationMetrics:
        """Calcule les métriques de qualité et de convergence d'une passe."""
        changed = 0
        total_conf = 0.0
        high_conf = 0
        atypical = 0
        dist: Counter[str] = Counter()

        for key, inf in beliefs.items():
            r = inf.role_principal or "INCONNU"
            dist[r] += 1
            total_conf += inf.role_confiance
            if inf.role_confiance >= 0.70:
                high_conf += 1
            if inf.role_atypique:
                atypical += 1

            if previous_beliefs:
                prev_inf = previous_beliefs.get(key)
                if prev_inf and prev_inf.role_principal != inf.role_principal:
                    changed += 1

        avg_conf = (total_conf / len(beliefs)) if beliefs else 0.0

        return IterationMetrics(
            iteration=iteration,
            changed_roles_count=changed,
            average_confidence=round(avg_conf, 3),
            high_confidence_count=high_conf,
            atypical_roles_count=atypical,
            roles_distribution=dict(dist),
        )

    def _persist_results(
        self,
        match_cache: dict[int, dict],
        beliefs: dict[tuple[int, str, str], RoleInference],
    ) -> None:
        """Met à jour les tables SQL avec les nouveaux rôles et recalcule les rollups."""
        updated_joueurs: set[int] = set()
        updated_saisons: set[int] = set()

        # Pré-charger toutes les lignes joueur_match_stats concernées en batch
        # pour éviter des milliers de requêtes SELECT unitaires (anti-pattern N+1).
        all_match_ids = list(match_cache.keys())
        existing_entries: dict[tuple[int, int], JoueurMatchStatsDB] = {}
        for chunk in _chunked(all_match_ids, 500):
            stmt = select(JoueurMatchStatsDB).where(JoueurMatchStatsDB.match_id.in_(chunk))
            for jms in self.session.scalars(stmt):
                existing_entries[(jms.match_id, jms.joueur_id)] = jms

        for (m_id, side, num), role_inf in beliefs.items():
            m_info = match_cache.get(m_id)
            if not m_info:
                continue
            j_id = m_info["side_map"][side].get(num)
            if not j_id:
                continue

            updated_joueurs.add(j_id)
            if m_info["saison_id"]:
                updated_saisons.add(m_info["saison_id"])

            entry = existing_entries.get((m_id, j_id))
            if entry:
                entry.role_principal = role_inf.role_principal
                entry.role_confiance = role_inf.role_confiance
                entry.roles_possibles = role_inf.roles_possibles
                entry.role_scores = role_inf.role_scores
                entry.indices_roles = role_inf.indices

        self.session.flush()

        # Recalculer les rollups joueur-saison et carriere pour les joueurs mis à jour
        if updated_joueurs:
            j_ids_list = list(updated_joueurs)
            for s_id in updated_saisons:
                self.rollup_service.compute_player_season_stats(
                    saison_id=s_id, joueur_ids=j_ids_list
                )
            self.rollup_service.compute_player_career_stats(joueur_ids=j_ids_list)
            self.session.flush()
