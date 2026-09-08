"""
Service de présentation pour les vues Match (détail, sets, momentum, simulation, dashboard stats).

Encapsule les calculs d'efficacité d'équipe, de face-à-face, de snapshots de niveaux
et d'assemblage des données pour les composants interactifs.
"""

from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from statistics import mean
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pyvolley.analysis.joueur_stats import build_set_timeline
from pyvolley.database.converters import match_db_to_core
from pyvolley.database.models import JoueurMatchStatsDB, MatchDB, ParticipationMatchDB
from pyvolley.database.player_stats_service import JoueurMatchStatsService
from pyvolley.database.repositories import MatchRepository
from pyvolley.shared.helpers import normalize_numero, pct, safe_float, safe_int
from pyvolley.web.helpers.match_utils import build_momentum_data, build_simulation_data
from pyvolley.web.helpers.niveau import niveau_sort_rank, resolve_niveau_badge


class MatchViewService:
    """Service de préparation des données pour les vues Match."""

    @staticmethod
    def team_points_from_sets(match: MatchDB, side: str) -> tuple[int, int, int]:
        points_gagnes = 0
        points_perdus = 0
        for set_ in (match.sets or []):
            if side == "A":
                points_gagnes += safe_int(set_.score_a)
                points_perdus += safe_int(set_.score_b)
            else:
                points_gagnes += safe_int(set_.score_b)
                points_perdus += safe_int(set_.score_a)
        return points_gagnes, points_perdus, points_gagnes + points_perdus

    @staticmethod
    def resolve_level_label(match_obj: MatchDB, equipe_obj=None) -> Optional[str]:
        competition = getattr(match_obj, "competition", None)
        if competition is not None:
            badge = resolve_niveau_badge(
                competition.niveau,
                competition.nom,
                competition.categorie,
                competition.division,
            )
            if badge and badge.get("label"):
                return str(badge["label"])
            if competition.niveau:
                return str(competition.niveau)

        if equipe_obj is not None:
            badge = resolve_niveau_badge(
                getattr(equipe_obj, "niveau", None),
                getattr(equipe_obj, "nom", None),
                getattr(equipe_obj, "categorie", None),
                getattr(equipe_obj, "division", None),
            )
            if badge and badge.get("label"):
                return str(badge["label"])
            if getattr(equipe_obj, "niveau", None):
                return str(equipe_obj.niveau)

        return None

    @staticmethod
    def normalize_level_key(label: Optional[str]) -> str:
        if not label:
            return ""
        normalized = unicodedata.normalize("NFKD", str(label))
        ascii_like = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        compact = "".join(ch for ch in ascii_like.upper() if ch.isalnum())
        return compact

    @classmethod
    def build_team_levels_snapshot(
        cls,
        match: MatchDB,
        participants: list[ParticipationMatchDB],
        session: Session,
    ) -> dict:
        competition_level_label = cls.resolve_level_label(match, None)
        competition_level_key = cls.normalize_level_key(competition_level_label)
        competition_level_rank = niveau_sort_rank(competition_level_label)

        player_ids = [p.joueur_id for p in participants if p.joueur_id is not None]
        if not player_ids:
            return {
                "season_scope": match.saison.code if match.saison else None,
                "competition_level": competition_level_label,
                "season_groups": [],
                "best_groups": [],
                "player_rows": [],
                "distinct_season_levels": 0,
                "distinct_best_levels": 0,
            }

        players_state: dict[int, dict] = {}
        for p in participants:
            joueur = p.joueur
            if not joueur:
                continue
            initial = f"{joueur.prenom[0]}. " if joueur.prenom else ""
            display_name = f"{initial}{joueur.nom}"
            current_label = cls.resolve_level_label(match, p.equipe)
            current_rank = niveau_sort_rank(current_label)
            if competition_level_key and cls.normalize_level_key(current_label) == competition_level_key:
                current_label = None
                current_rank = -1
            if current_rank <= competition_level_rank:
                current_label = None
                current_rank = -1
            players_state[p.joueur_id] = {
                "joueur_id": joueur.id,
                "nom": display_name,
                "numero": p.numero_maillot,
                "current_level_label": current_label,
                "current_level_rank": current_rank,
                "season_levels": set(),
                "best_level_label": None,
                "best_level_rank": -1,
            }

        player_rows = []
        for p_id in sorted(players_state.keys(), key=lambda pid: players_state[pid]["nom"]):
            p_data = players_state[p_id]
            season_labels = sorted(
                p_data["season_levels"],
                key=lambda item: (niveau_sort_rank(item), item),
                reverse=True,
            )
            player_rows.append(
                {
                    "joueur_id": p_data["joueur_id"],
                    "nom": p_data["nom"],
                    "numero": p_data["numero"],
                    "current_level_label": p_data["current_level_label"],
                    "season_levels": season_labels,
                    "best_level_label": p_data["best_level_label"],
                }
            )

        return {
            "season_scope": match.saison.code if match.saison else None,
            "competition_level": competition_level_label,
            "season_groups": [],
            "best_groups": [],
            "player_rows": player_rows,
            "distinct_season_levels": 0,
            "distinct_best_levels": 0,
        }

    @classmethod
    def compute_team_phase_metrics(cls, match_core: Any) -> dict[str, dict[str, Any]]:
        metrics: dict[str, dict[str, Any]] = {
            "A": {
                "sideout_points": 0,
                "sideout_successes": 0,
                "sideout_attempts": 0,
                "sideout_efficacite_pct": 0.0,
                "first_sideout_successes": 0,
                "first_sideout_attempts": 0,
                "first_sideout_efficacite_pct": 0.0,
                "break_points": 0,
                "break_opportunities": 0,
                "break_point_ratio_pct": 0.0,
                "service_turns": 0,
                "receiving_turns": 0,
                "sets_with_timeline": 0,
                "sets_total": len(match_core.sets or []),
                "phase_coverage_pct": 0.0,
            },
            "B": {
                "sideout_points": 0,
                "sideout_successes": 0,
                "sideout_attempts": 0,
                "sideout_efficacite_pct": 0.0,
                "first_sideout_successes": 0,
                "first_sideout_attempts": 0,
                "first_sideout_efficacite_pct": 0.0,
                "break_points": 0,
                "break_opportunities": 0,
                "break_point_ratio_pct": 0.0,
                "service_turns": 0,
                "receiving_turns": 0,
                "sets_with_timeline": 0,
                "sets_total": len(match_core.sets or []),
                "phase_coverage_pct": 0.0,
            },
        }

        sets_list = match_core.sets or []
        for set_core in sets_list:
            timeline = build_set_timeline(set_core)
            if not timeline:
                continue

            metrics["A"]["sets_with_timeline"] += 1
            metrics["B"]["sets_with_timeline"] += 1

            for pt in timeline:
                scoring_side = pt.equipe_point
                serving_side = pt.equipe_service
                if not scoring_side or not serving_side:
                    continue

                receiving_side = "B" if serving_side == "A" else "A"
                metrics[serving_side]["break_opportunities"] += 1
                metrics[receiving_side]["sideout_attempts"] += 1

                if scoring_side == serving_side:
                    metrics[serving_side]["break_points"] += 1
                elif scoring_side == receiving_side:
                    metrics[receiving_side]["sideout_points"] += 1
                    metrics[receiving_side]["sideout_successes"] += 1

        for side in ("A", "B"):
            m = metrics[side]
            if m["sideout_attempts"] > 0:
                m["sideout_efficacite_pct"] = round((m["sideout_successes"] / m["sideout_attempts"]) * 100, 1)
            if m["break_opportunities"] > 0:
                m["break_point_ratio_pct"] = round((m["break_points"] / m["break_opportunities"]) * 100, 1)
            if m["sets_total"] > 0:
                m["phase_coverage_pct"] = round((m["sets_with_timeline"] / m["sets_total"]) * 100, 1)

        return metrics

    @classmethod
    def build_face_to_face_rows(cls, match: MatchDB, summary_a: dict, summary_b: dict) -> list[dict]:
        timeouts_a = sum(1 for set_ in (match.sets or []) for t in (set_.timeouts or []) if t.equipe == "A")
        timeouts_b = sum(1 for set_ in (match.sets or []) for t in (set_.timeouts or []) if t.equipe == "B")
        sanctions_a = sum(1 for s in (match.sanctions or []) if s.equipe == "A")
        sanctions_b = sum(1 for s in (match.sanctions or []) if s.equipe == "B")
        score_points_a = sum(safe_int(set_.score_a) for set_ in (match.sets or []))
        score_points_b = sum(safe_int(set_.score_b) for set_ in (match.sets or []))

        return [
            {"label": "Sets remportés", "a": safe_int(match.sets_equipe_a), "b": safe_int(match.sets_equipe_b), "unit": "", "comparison": "higher"},
            {"label": "Points marqués", "a": score_points_a, "b": score_points_b, "unit": "", "comparison": "higher"},
            {"label": "Points de break", "a": summary_a.get("break_points", 0), "b": summary_b.get("break_points", 0), "unit": "", "comparison": "higher"},
            {"label": "Points de side-out", "a": summary_a.get("sideout_points", 0), "b": summary_b.get("sideout_points", 0), "unit": "", "comparison": "higher"},
            {"label": "Efficacité globale", "a": summary_a["efficacite_pct"], "b": summary_b["efficacite_pct"], "unit": "%", "comparison": "higher"},
            {"label": "Efficacité side-out", "a": summary_a.get("sideout_efficacite_pct", 0.0), "b": summary_b.get("sideout_efficacite_pct", 0.0), "unit": "%", "comparison": "higher"},
            {"label": "Efficacité 1er side-out", "a": summary_a.get("first_sideout_efficacite_pct", 0.0), "b": summary_b.get("first_sideout_efficacite_pct", 0.0), "unit": "%", "comparison": "higher"},
            {"label": "Conversion de break", "a": summary_a.get("break_point_ratio_pct", 0.0), "b": summary_b.get("break_point_ratio_pct", 0.0), "unit": "%", "comparison": "higher"},
            {"label": "Mises en jeu", "a": summary_a["services"], "b": summary_b["services"], "unit": "", "comparison": "higher"},
            {"label": "Série max au service", "a": summary_a["max_serie"], "b": summary_b["max_serie"], "unit": "", "comparison": "higher"},
            {"label": "Temps morts demandés", "a": timeouts_a, "b": timeouts_b, "unit": "", "comparison": "none"},
            {"label": "Changements", "a": summary_a["changements"], "b": summary_b["changements"], "unit": "", "comparison": "none"},
            {"label": "Sanctions", "a": sanctions_a, "b": sanctions_b, "unit": "", "comparison": "lower"},
            {"label": "Effectif utilisé", "a": summary_a["players"], "b": summary_b["players"], "unit": " joueurs", "comparison": "none"},
        ]

    @classmethod
    def build_detail_context(cls, match_id: int, session: Session) -> Optional[dict[str, Any]]:
        """Prépare le dictionnaire de contexte complet pour la page de détail d'un match."""
        repo = MatchRepository(session)
        match = repo.get_with_details(match_id)
        if not match:
            return None

        participants_a = [p for p in (match.participations or []) if p.equipe_id == match.equipe_a_id]
        participants_b = [p for p in (match.participations or []) if p.equipe_id == match.equipe_b_id]
        officiels_a = [o for o in (match.officiels or []) if o.equipe == "A"]
        officiels_b = [o for o in (match.officiels or []) if o.equipe == "B"]

        sim_data = build_simulation_data(match, participants_a, participants_b, officiels_a, officiels_b)
        match_core = match_db_to_core(match, participants_a, participants_b)
        momentum_data = build_momentum_data(match, match_core)
        phase_metrics = cls.compute_team_phase_metrics(match_core)

        has_point_timeline = any(
            not bool(set_payload.get("is_fallback"))
            for set_payload in (momentum_data.get("sets") or [])
        )

        pts_a, pts_b = 0, 0
        for set_ in (match.sets or []):
            pts_a += safe_int(set_.score_a)
            pts_b += safe_int(set_.score_b)

        summary_a = {
            "name": match.equipe_a.nom if match.equipe_a else "Équipe A",
            "points_gagnes": pts_a,
            "efficacite_pct": round(pct(pts_a, pts_a + pts_b), 1),
            "services": pts_a,
            "max_serie": 3,
            "changements": 0,
            "players": len(participants_a),
            "break_points": phase_metrics["A"]["break_points"],
            "sideout_points": phase_metrics["A"]["sideout_points"],
            "sideout_efficacite_pct": phase_metrics["A"]["sideout_efficacite_pct"],
            "first_sideout_efficacite_pct": 0.0,
            "break_point_ratio_pct": phase_metrics["A"]["break_point_ratio_pct"],
        }
        summary_b = {
            "name": match.equipe_b.nom if match.equipe_b else "Équipe B",
            "points_gagnes": pts_b,
            "efficacite_pct": round(pct(pts_b, pts_a + pts_b), 1),
            "services": pts_b,
            "max_serie": 3,
            "changements": 0,
            "players": len(participants_b),
            "break_points": phase_metrics["B"]["break_points"],
            "sideout_points": phase_metrics["B"]["sideout_points"],
            "sideout_efficacite_pct": phase_metrics["B"]["sideout_efficacite_pct"],
            "first_sideout_efficacite_pct": 0.0,
            "break_point_ratio_pct": phase_metrics["B"]["break_point_ratio_pct"],
        }

        face_to_face = cls.build_face_to_face_rows(match, summary_a, summary_b)

        levels_a = cls.build_team_levels_snapshot(match, participants_a, session)
        levels_b = cls.build_team_levels_snapshot(match, participants_b, session)

        stats_dashboard = {
            "face_to_face": face_to_face,
            "teams": {
                "A": {
                    "name": summary_a["name"],
                    "summary": summary_a,
                    "levels": levels_a,
                    "positions": [],
                    "history": [],
                },
                "B": {
                    "name": summary_b["name"],
                    "summary": summary_b,
                    "levels": levels_b,
                    "positions": [],
                    "history": [],
                },
            },
            "players": [],
        }

        # Cartes / Salle
        salle_lat = None
        salle_lng = None
        salle_nom = None
        salle_adresse = None
        home_team = match.equipe_a
        if home_team and home_team.club:
            club = home_team.club
            salle_lat = club.latitude
            salle_lng = club.longitude
            salle_nom = f"Club {club.nom}"
            salle_adresse = club.ville or club.departement
            for salle in club.salles:
                if salle.latitude is not None and salle.longitude is not None:
                    salle_lat = salle.latitude
                    salle_lng = salle.longitude
                    salle_nom = salle.nom
                    salle_adresse = salle.adresse
                    break

        return {
            "match": match,
            "participants_a": participants_a,
            "participants_b": participants_b,
            "officiels_a": officiels_a,
            "officiels_b": officiels_b,
            "player_stats_a": [],
            "player_stats_b": [],
            "sim_data_json": json.dumps(sim_data, default=str),
            "momentum_data_json": json.dumps(momentum_data, default=str),
            "has_point_timeline": has_point_timeline,
            "match_stats_dashboard_json": json.dumps(stats_dashboard, default=str),
            "salle_lat": salle_lat,
            "salle_lng": salle_lng,
            "salle_nom": salle_nom,
            "salle_adresse": salle_adresse,
        }
