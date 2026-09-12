"""
Service de présentation pour les vues Joueur (fiche détaillée, listes, métriques, carte).

Encapsule toute la logique de calcul de profil, d'estimation d'âge,
d'analyse des maillots et des rotations, et de préparation des contextes de templates.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date as dt_date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from pyvolley.analysis.joueur_stats import aggregate_joueur_stats
from pyvolley.core.constants import get_role_label
from pyvolley.database.models import JoueurDB, ParticipationMatchDB
from pyvolley.database.player_stats_service import JoueurMatchStatsService
from pyvolley.database.repositories import (
    JoueurCarriereStatsRepository,
    JoueurRepository,
    JoueurSaisonStatsRepository,
    MatchRepository,
)
from pyvolley.shared.helpers import pct
from pyvolley.web.helpers.club_branding import parse_club_colors
from pyvolley.web.helpers.common import role_label, season_end_year, season_sort_key
from pyvolley.web.helpers.niveau import (
    niveau_reference_labels,
    niveau_sort_key,
    niveau_sort_rank,
    resolve_niveau_badge,
)

YOUTH_CATEGORY_RE = re.compile(r"\b(?:M|U)\s*(1[0-9]|20|21)\b", re.IGNORECASE)

TEAM_NAME_STOPWORDS = {
    "LE", "LA", "LES", "DE", "DES", "DU", "D", "L", "ET",
    "VOLLEY", "BALL", "VOLLEYBALL", "VB", "CFC", "ASS", "ASSO", "ASSOCIATION",
}


class JoueurViewService:
    """Service d'agrégation et de préparation des données pour les vues Joueur."""

    @staticmethod
    def level_rank(level: Optional[str]) -> Optional[int]:
        if not level:
            return None
        rank = niveau_sort_rank(level)
        return rank if rank >= 0 else None

    @staticmethod
    def resolve_match_level_label(match: Any, equipe_joueur: Any, adversaire: Any) -> Optional[str]:
        competition = match.competition

        candidates = []
        if competition:
            candidates.append(
                (
                    competition.niveau,
                    competition.nom,
                    competition.categorie,
                    competition.division,
                )
            )

        if equipe_joueur:
            candidates.append(
                (
                    equipe_joueur.niveau,
                    equipe_joueur.nom,
                    equipe_joueur.categorie,
                    equipe_joueur.division,
                )
            )

        if adversaire:
            candidates.append(
                (
                    adversaire.niveau,
                    adversaire.nom,
                    adversaire.categorie,
                    adversaire.division,
                )
            )

        for niveau, nom, categorie, division in candidates:
            badge = resolve_niveau_badge(niveau, nom, categorie, division)
            if badge and badge.get("label"):
                return badge["label"]
            if niveau:
                return niveau
        return None

    @staticmethod
    def parse_date(value: Optional[str]) -> Optional[dt_date]:
        if not value:
            return None
        try:
            return dt_date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def season_end_year_from_row(row: dict) -> Optional[int]:
        saison = row.get("saison")
        season_code = getattr(saison, "code", None) if saison else None
        end_year = season_end_year(season_code)
        if end_year is not None:
            return end_year

        match = row.get("match")
        match_date = getattr(match, "date_match", None)
        if match_date is None:
            return None

        # Saison sportive: les matchs d'août à décembre se terminent l'année suivante.
        return match_date.year + 1 if match_date.month >= 8 else match_date.year

    @staticmethod
    def extract_youth_ages_from_text(value: Optional[str]) -> list[int]:
        if not value:
            return []
        ages: list[int] = []
        for match in YOUTH_CATEGORY_RE.finditer(value):
            try:
                ages.append(int(match.group(1)))
            except (TypeError, ValueError):
                continue
        return ages

    @staticmethod
    def compute_birth_date_bounds(age_limit: int, season_end_year: int) -> tuple[dt_date, dt_date]:
        return dt_date(season_end_year - age_limit, 1, 1), dt_date(season_end_year, 12, 31)

    @staticmethod
    def compute_full_years_since(birth_date: dt_date, reference_date: dt_date) -> int:
        years = reference_date.year - birth_date.year
        if (reference_date.month, reference_date.day) < (birth_date.month, birth_date.day):
            years -= 1
        return max(0, years)

    @classmethod
    def estimate_player_age(cls, candidates: list[dict], ref_date: dt_date) -> Optional[dict]:
        if not candidates:
            return None

        strongest = max(candidates, key=lambda item: item["birth_date_min"])
        strongest_birth_date = strongest["birth_date_min"]
        strongest_candidates = [
            item
            for item in candidates
            if item["birth_date_min"] == strongest_birth_date
        ]

        all_categories = sorted({f"M{item['age_limit']}" for item in candidates}, key=lambda label: int(label[1:]))
        best_categories = sorted(
            {f"M{item['age_limit']}" for item in strongest_candidates},
            key=lambda label: int(label[1:]),
        )
        best_seasons = sorted(
            {
                str(item["season_code"])
                for item in strongest_candidates
                if item.get("season_code")
            },
            key=season_sort_key,
            reverse=True,
        )

        return {
            "max_age_years": cls.compute_full_years_since(strongest_birth_date, ref_date),
            "birth_date_min": strongest_birth_date.isoformat(),
            "birth_date_min_display": strongest_birth_date.strftime("%d/%m/%Y"),
            "reference_date": ref_date.isoformat(),
            "all_category_labels": all_categories,
            "best_category_labels": best_categories,
            "best_season_labels": best_seasons,
            "source_match_count": len(
                {
                    item["match_id"]
                    for item in candidates
                    if item.get("match_id") is not None
                }
            ),
        }

    @staticmethod
    def normalize_team_name(value: Optional[str]) -> str:
        if not value:
            return ""
        normalized = unicodedata.normalize("NFKD", value)
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = normalized.upper()
        cleaned = []
        for ch in normalized:
            cleaned.append(ch if ch.isalnum() else " ")
        return " ".join("".join(cleaned).split())

    @classmethod
    def team_tokens(cls, value: Optional[str]) -> set[str]:
        normalized = cls.normalize_team_name(value)
        if not normalized:
            return set()
        return {
            token
            for token in normalized.split()
            if len(token) > 1 and not token.isdigit() and token not in TEAM_NAME_STOPWORDS
        }

    @classmethod
    def infer_side_from_participation(cls, match: Any, participation: Any) -> Optional[str]:
        if not participation:
            return None

        if getattr(participation, "side", None):
            return participation.side

        if match.equipe_a_id == participation.equipe_id:
            return "A"
        if match.equipe_b_id == participation.equipe_id:
            return "B"

        participation_equipe = participation.equipe
        if not participation_equipe:
            return None

        part_club_id = participation_equipe.club_id
        if part_club_id and match.equipe_a and match.equipe_a.club_id == part_club_id:
            return "A"
        if part_club_id and match.equipe_b and match.equipe_b.club_id == part_club_id:
            return "B"

        part_name = participation_equipe.nom
        a_name = match.equipe_a.nom if match.equipe_a else None
        b_name = match.equipe_b.nom if match.equipe_b else None

        part_norm = cls.normalize_team_name(part_name).replace(" ", "")
        a_norm = cls.normalize_team_name(a_name).replace(" ", "")
        b_norm = cls.normalize_team_name(b_name).replace(" ", "")

        if part_norm and a_norm and (part_norm in a_norm or a_norm in part_norm):
            return "A"
        if part_norm and b_norm and (part_norm in b_norm or b_norm in part_norm):
            return "B"

        part_tokens = cls.team_tokens(part_name)
        a_tokens = cls.team_tokens(a_name)
        b_tokens = cls.team_tokens(b_name)

        if not part_tokens:
            return None

        score_a = len(part_tokens & a_tokens) / len(part_tokens) if a_tokens else 0.0
        score_b = len(part_tokens & b_tokens) / len(part_tokens) if b_tokens else 0.0

        if score_a > score_b and score_a >= 0.5:
            return "A"
        if score_b > score_a and score_b >= 0.5:
            return "B"

        return None

    @classmethod
    def build_detail_context(
        cls,
        joueur_id: int | str,
        session: Session,
        tab: Optional[str] = "resume",
        saison_id: Optional[int] = None,
        saison_ids: Optional[list[int]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        equipe_ids: Optional[list[int]] = None,
        club_ids: Optional[list[int]] = None,
        competition_ids: Optional[list[int]] = None,
        niveaux: Optional[list[str]] = None,
        resultat: Optional[str] = None,
        domicile_exterieur: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Construit l'ensemble des données nécessaires pour la fiche joueur."""
        joueur_repo = JoueurRepository(session)
        joueur = joueur_repo.get_by_licence_or_id(joueur_id)
        if not joueur:
            return None

        # Toujours utiliser la clé primaire entière pour les requêtes de base de données
        joueur_id_int = joueur.id

        match_repo = MatchRepository(session)
        matchs_all = match_repo.get_by_joueur(joueur_id_int, limit=1200)
        participations = list(
            session.scalars(
                select(ParticipationMatchDB)
                .where(ParticipationMatchDB.joueur_id == joueur_id_int)
            )
        )
        participation_by_match_id = {p.match_id: p for p in participations}

        default_rows = []
        for match in matchs_all:
            participation = participation_by_match_id.get(match.id)
            if not participation:
                continue

            side = cls.infer_side_from_participation(match, participation)
            equipe_joueur = None
            adversaire = None
            if side == "A":
                equipe_joueur = match.equipe_a
                adversaire = match.equipe_b
            elif side == "B":
                equipe_joueur = match.equipe_b
                adversaire = match.equipe_a
            else:
                equipe_joueur = participation.equipe

            niveau_principal = cls.resolve_match_level_label(match, equipe_joueur, adversaire)

            victoire = None
            if match.match_joue and side in {"A", "B"}:
                victoire = (
                    (side == "A" and (match.sets_equipe_a or 0) > (match.sets_equipe_b or 0))
                    or (side == "B" and (match.sets_equipe_b or 0) > (match.sets_equipe_a or 0))
                )

            default_rows.append(
                {
                    "match": match,
                    "participation": participation,
                    "side": side,
                    "equipe_joueur": equipe_joueur,
                    "adversaire": adversaire,
                    "club": equipe_joueur.club if equipe_joueur else None,
                    "saison": match.saison,
                    "competition": match.competition,
                    "niveau": niveau_principal,
                    "victoire": victoire,
                }
            )

        rows_played = [row for row in default_rows if row["match"].match_joue]
        base_rows = rows_played if rows_played else default_rows

        selected_saison_ids = set(saison_ids or ([] if saison_id is None else [saison_id]))
        selected_equipe_ids = set(equipe_ids or [])
        selected_club_ids = set(club_ids or [])
        selected_competition_ids = set(competition_ids or [])
        selected_niveaux = set(niveaux or [])
        date_from_obj = cls.parse_date(date_from)
        date_to_obj = cls.parse_date(date_to)

        filtered_rows = []
        for row in base_rows:
            match = row["match"]
            equipe_joueur = row["equipe_joueur"]
            club = row["club"]
            competition = row["competition"]
            niveau = row["niveau"]
            if selected_saison_ids and match.saison_id not in selected_saison_ids:
                continue
            if date_from_obj and (not match.date_match or match.date_match < date_from_obj):
                continue
            if date_to_obj and (not match.date_match or match.date_match > date_to_obj):
                continue
            if selected_equipe_ids and (not equipe_joueur or equipe_joueur.id not in selected_equipe_ids):
                continue
            if selected_club_ids and (not club or club.id not in selected_club_ids):
                continue
            if selected_competition_ids and (not competition or competition.id not in selected_competition_ids):
                continue
            if selected_niveaux and (not niveau or niveau not in selected_niveaux):
                continue
            if resultat == "victoire" and not row["victoire"]:
                continue
            if resultat == "defaite" and row["victoire"] is not False:
                continue
            if domicile_exterieur == "domicile" and row["side"] != "A":
                continue
            if domicile_exterieur == "exterieur" and row["side"] != "B":
                continue
            filtered_rows.append(row)

        matchs = [row["match"] for row in filtered_rows][:400]
        filtered_rows = filtered_rows[:400]
        filtered_match_ids = {m.id for m in matchs}

        seasons_map: dict[int, str] = {}
        equipes_map: dict[int, str] = {}
        clubs_map: dict[int, str] = {}
        competitions_map: dict[int, str] = {}
        niveaux_set: set[str] = set()
        for row in base_rows:
            match = row["match"]
            equipe_joueur = row["equipe_joueur"]
            club = row["club"]
            competition = row["competition"]
            niveau = row["niveau"]
            if match.saison_id and row["saison"]:
                seasons_map[match.saison_id] = row["saison"].code
            if equipe_joueur:
                equipes_map[equipe_joueur.id] = equipe_joueur.nom
            if club:
                clubs_map[club.id] = club.nom
            if competition:
                competitions_map[competition.id] = competition.nom
            if niveau:
                niveaux_set.add(niveau)

        filter_options = {
            "saisons": sorted(
                [{"id": s_id, "label": s_code} for s_id, s_code in seasons_map.items()],
                key=lambda item: season_sort_key(item["label"]),
                reverse=True,
            ),
            "equipes": sorted(
                [{"id": e_id, "label": e_nom} for e_id, e_nom in equipes_map.items()],
                key=lambda item: item["label"].lower(),
            ),
            "clubs": sorted(
                [{"id": c_id, "label": c_nom} for c_id, c_nom in clubs_map.items()],
                key=lambda item: item["label"].lower(),
            ),
            "competitions": sorted(
                [{"id": c_id, "label": c_nom} for c_id, c_nom in competitions_map.items()],
                key=lambda item: item["label"].lower(),
            ),
            "niveaux": sorted(list(niveaux_set), key=niveau_sort_key),
        }

        hide_filters = {
            "saisons": len(filter_options["saisons"]) <= 1,
            "equipes": len(filter_options["equipes"]) <= 1,
            "clubs": len(filter_options["clubs"]) <= 1,
            "competitions": len(filter_options["competitions"]) <= 1,
            "niveaux": len(filter_options["niveaux"]) <= 1,
        }

        victoires = sum(1 for row in filtered_rows if row["victoire"] is True)
        defaites = sum(1 for row in filtered_rows if row["victoire"] is False)
        equipes_joueur = {row["equipe_joueur"].id for row in filtered_rows if row["equipe_joueur"]}
        matchs_joues_count = len(filtered_rows)
        taux_victoire = round((victoires / matchs_joues_count) * 100, 1) if matchs_joues_count else None

        stats = {
            "matchs_joues": matchs_joues_count,
            "victoires": victoires,
            "defaites": defaites,
            "taux_victoire": taux_victoire,
            "equipes_count": len(equipes_joueur),
        }

        # Estimation de l'âge
        ref_date = dt_date.today()
        age_candidates: list[dict] = []
        for row in base_rows:
            match = row["match"]
            competition = row["competition"]
            equipe_joueur = row["equipe_joueur"]
            season_end_yr = cls.season_end_year_from_row(row)
            if season_end_yr is None:
                continue

            texts_to_inspect = []
            if competition:
                texts_to_inspect.extend([competition.nom, competition.categorie, competition.division])
            if equipe_joueur:
                texts_to_inspect.extend([equipe_joueur.nom, equipe_joueur.categorie, equipe_joueur.division])

            detected_ages: set[int] = set()
            for text in texts_to_inspect:
                detected_ages.update(cls.extract_youth_ages_from_text(text))

            for age_limit in detected_ages:
                b_min, b_max = cls.compute_birth_date_bounds(age_limit, season_end_yr)
                age_candidates.append(
                    {
                        "age_limit": age_limit,
                        "season_code": row["saison"].code if row["saison"] else None,
                        "season_end_year": season_end_yr,
                        "match_id": match.id if match else None,
                        "birth_date_min": b_min,
                        "birth_date_max": b_max,
                    }
                )

        estimated_age = cls.estimate_player_age(age_candidates, ref_date)

        # Profil club & timeline
        profile_rows = sorted(
            [row for row in base_rows if row["match"].date_match],
            key=lambda row: row["match"].date_match,
        )
        latest_profile_row = profile_rows[-1] if profile_rows else (base_rows[-1] if base_rows else None)

        current_club_obj = latest_profile_row["club"] if latest_profile_row else None
        current_club_id = current_club_obj.id if current_club_obj else None

        # Numéros et maillots
        numero_counts: dict[str, int] = {}
        for participation in participations:
            numero = (participation.numero_maillot or "").strip()
            if not numero:
                continue
            numero_counts[numero] = numero_counts.get(numero, 0) + 1

        numero_total = sum(numero_counts.values())
        sorted_numeros = sorted(
            numero_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
        numero_stats = {
            "principal": sorted_numeros[0][0] if sorted_numeros else None,
            "distinct_count": len(sorted_numeros),
            "matches_with_number": numero_total,
            "distribution": [
                {
                    "numero": numero,
                    "count": count,
                    "pct": round((count / numero_total) * 100, 1) if numero_total > 0 else 0,
                }
                for numero, count in sorted_numeros
            ],
        }

        jersey_counts: dict[tuple[str, Optional[int], str], int] = {}
        jersey_meta: dict[tuple[str, Optional[int], str], dict] = {}

        def _club_from_participation(p: Any) -> Any:
            eq = p.equipe
            if eq and eq.club:
                return eq.club
            if latest_profile_row and latest_profile_row["club"]:
                return latest_profile_row["club"]
            return None

        for participation in participations:
            numero = (participation.numero_maillot or "").strip()
            if not numero:
                continue
            club = _club_from_participation(participation)
            club_id = club.id if club else None
            club_nom = club.nom if club else "Club inconnu"
            key = (numero, club_id, club_nom)
            jersey_counts[key] = jersey_counts.get(key, 0) + 1
            if key not in jersey_meta:
                palette = parse_club_colors(club.couleurs if club else None)
                jersey_meta[key] = {
                    "numero": numero,
                    "club_id": club_id,
                    "club_nom": club_nom,
                    "primary": palette["primary"],
                    "secondary": palette["secondary"],
                    "text_on_primary": palette["text_on_primary"],
                }

        jersey_total = sum(jersey_counts.values())
        jersey_cards = []
        joueur_nom_complet = f"{(joueur.prenom or '').strip()} {(joueur.nom or '').strip()}".strip()
        for key, count in sorted(
            jersey_counts.items(),
            key=lambda item: (
                item[0][1] == current_club_id,
                item[1],
                item[0][0],
            ),
            reverse=True,
        ):
            meta = jersey_meta[key]
            card_pct = round((count / jersey_total) * 100, 1) if jersey_total else 0.0
            jersey_scale = 0.98 + min(0.26, (card_pct / 100) * 0.38)
            jersey_cards.append(
                {
                    **meta,
                    "nom": joueur_nom_complet,
                    "count": count,
                    "pct": card_pct,
                    "scale": round(jersey_scale, 2),
                    "is_current_club": meta["club_id"] == current_club_id,
                }
            )

        if not jersey_cards:
            fallback_club = latest_profile_row["club"] if latest_profile_row and latest_profile_row["club"] else None
            fallback_palette = parse_club_colors(fallback_club.couleurs if fallback_club else None)
            jersey_cards.append(
                {
                    "numero": "?",
                    "club_id": fallback_club.id if fallback_club else None,
                    "club_nom": fallback_club.nom if fallback_club else "Club non identifié",
                    "primary": fallback_palette["primary"],
                    "secondary": fallback_palette["secondary"],
                    "text_on_primary": fallback_palette["text_on_primary"],
                    "nom": joueur_nom_complet or "Joueur",
                    "count": 0,
                    "pct": 0.0,
                    "scale": 1.0,
                    "is_current_club": bool(fallback_club),
                    "is_placeholder": True,
                }
            )

        top_numero = numero_stats["distribution"][0] if numero_stats["distribution"] else None
        principal_pct = float(top_numero["pct"]) if top_numero else 0.0
        if principal_pct >= 70:
            consistency_label = "Très stable"
        elif principal_pct >= 55:
            consistency_label = "Stable"
        elif principal_pct >= 35:
            consistency_label = "Alternance modérée"
        else:
            consistency_label = "Très variable"

        current_club_jersey_count = sum(
            int(card.get("count", 0))
            for card in jersey_cards
            if card.get("is_current_club")
        )
        current_club_jersey_pct = (
            round((current_club_jersey_count / jersey_total) * 100, 1)
            if jersey_total
            else 0.0
        )
        jersey_profile = {
            "principal_numero": numero_stats["principal"],
            "principal_pct": principal_pct,
            "consistency_label": consistency_label,
            "distinct_numeros": numero_stats["distinct_count"],
            "matches_with_number": numero_stats["matches_with_number"],
            "variants_count": len(jersey_cards),
            "current_club_pct": current_club_jersey_pct,
            "has_placeholder": any(card.get("is_placeholder") for card in jersey_cards),
        }

        # Timeline des niveaux
        level_timeline = []
        for index, row in enumerate(
            sorted(
                [r for r in filtered_rows if r["match"].date_match],
                key=lambda r: r["match"].date_match,
            ),
            start=1,
        ):
            match = row["match"]
            level_label = row["niveau"] or "Niveau inconnu"
            level_timeline.append(
                {
                    "index": index,
                    "match_id": match.id,
                    "date": match.date_match.isoformat() if match.date_match else None,
                    "niveau": level_label,
                    "level_rank": cls.level_rank(level_label),
                    "victoire": row["victoire"],
                    "adversaire": row["adversaire"].nom if row["adversaire"] else None,
                    "domicile_exterieur": (
                        "domicile"
                        if row["side"] == "A"
                        else ("exterieur" if row["side"] == "B" else "inconnu")
                    ),
                }
            )

        level_rank_labels = niveau_reference_labels()
        level_reference_order_text = " < ".join(str(item["label"]) for item in level_rank_labels)

        known_level_points = [point for point in level_timeline if point["level_rank"] is not None]
        level_timeline_summary = {
            "total_count": len(level_timeline),
            "known_count": len(known_level_points),
            "coverage_pct": round((len(known_level_points) / len(level_timeline)) * 100, 1) if level_timeline else 0.0,
            "current_label": None,
            "peak_label": None,
        }
        if known_level_points:
            peak_point = max(known_level_points, key=lambda point: (point["level_rank"], point["index"]))
            current_point = known_level_points[-1]
            level_timeline_summary.update(
                {
                    "current_label": current_point["niveau"],
                    "peak_label": peak_point["niveau"],
                }
            )

        # Statistiques détaillées de match & Rôles
        stats_service = JoueurMatchStatsService(session)
        stats_rows = stats_service.repo.get_for_joueur(joueur_id, limit=1200)

        aggregated_stats = None
        per_match_stats = []
        match_evolution_stats = []
        role_overview = {
            "available": False,
            "principal_code": None,
            "principal_label": "Non déterminé",
            "plausibility_pct": 0.0,
            "consistency_pct": 0.0,
            "average_confidence_pct": 0.0,
            "coverage_pct": 0.0,
            "match_count": 0,
            "roles": [],
            "sources": [],
            "evidence": [],
        }

        if stats_rows:
            filtered_stats_rows = [row for row in stats_rows if row.match_id in filtered_match_ids]
            detailed_models = [row.to_detailed_stats() for row in filtered_stats_rows]
            aggregated = aggregate_joueur_stats(detailed_models)
            if aggregated is not None:
                aggregated_stats = aggregated.model_dump(mode="json")

            role_distribution_matchs = (
                (aggregated_stats or {}).get("role_distribution_matchs")
                if aggregated_stats
                else {}
            ) or {}
            role_principal_global = (
                (aggregated_stats or {}).get("role_principal_global")
                if aggregated_stats
                else None
            )

            role_counts_local: dict[str, int] = defaultdict(int)
            role_confidences: list[float] = []
            source_counts: dict[str, int] = defaultdict(int)
            evidence_items: list[str] = []
            role_known_count = 0

            matchs_by_id = {m.id: m for m in matchs}
            for row in filtered_stats_rows:
                match = matchs_by_id.get(row.match_id)
                role_code = row.role_principal
                if role_code:
                    role_counts_local[role_code] += 1
                    role_known_count += 1
                if row.role_confiance is not None:
                    role_confidences.append(float(row.role_confiance))

                # Traçabilité des indices
                hints = getattr(row, "indices_roles", None) or []
                for hint in hints:
                    text_hint = str(hint)
                    evidence_items.append(text_hint)
                    if "passe-pointe" in text_hint.lower():
                        source_counts["Inversion passe-pointe"] += 1
                    elif "libero" in text_hint.lower():
                        source_counts["Remplacements libero"] += 1
                    elif "rotation" in text_hint.lower() or "formation" in text_hint.lower():
                        source_counts["Ordre rotation / formation"] += 1
                    else:
                        source_counts["Patterns de changements"] += 1

                pts_joues = row.points_joues or 0
                pts_gagnes = row.points_gagnes or 0
                pts_perdus = row.points_perdus or 0
                pts_gagnes_srv = row.points_gagnes_service or 0
                pts_so = (
                    row.points_gagnes_sideout
                    if row.points_gagnes_sideout is not None
                    else max(0, pts_gagnes - pts_gagnes_srv)
                )
                ratio_points = round(pct(pts_gagnes, pts_joues), 1) if pts_joues else 0.0
                break_ratio = round(pct(pts_gagnes_srv, row.services or 0), 1) if (row.services or 0) > 0 else 0.0
                sideout_contrib = round(pct(pts_so, pts_gagnes), 1) if pts_gagnes > 0 else 0.0

                pms_entry = {
                    "match_id": row.match_id,
                    "date": match.date_match.strftime("%d/%m/%Y") if match and match.date_match else None,
                    "points_joues": pts_joues,
                    "points_gagnes": pts_gagnes,
                    "points_perdus": pts_perdus,
                    "points_gagnes_service": pts_gagnes_srv,
                    "points_gagnes_sideout": pts_so,
                    "services": row.services or 0,
                    "max_serie": row.max_serie or 0,
                    "victoire": row.victoire,
                    "role_principal": row.role_principal,
                    "role_confiance": row.role_confiance,
                }

                part_match = participation_by_match_id.get(row.match_id)
                num_maillot = part_match.numero_maillot if part_match else None
                row_base = next((rb for rb in base_rows if rb["match"].id == row.match_id), None)
                adv = row_base["adversaire"] if row_base else None
                comp = row_base["competition"] if row_base else None

                per_match_stats.append(
                    {
                        "date": match.date_match if match and match.date_match else None,
                        "adversaire": adv.nom if adv else "Adversaire",
                        "adversaire_id": adv.id if adv else None,
                        "match_id": row.match_id,
                        "competition_id": comp.id if comp else None,
                        "numero": num_maillot,
                        "niveau_principal": row_base["niveau"] if row_base else None,
                        "role_code": row.role_principal,
                        "role_label": get_role_label(row.role_principal) if row.role_principal else "—",
                        "role_plausibility_pct": round(float(row.role_confiance or 0.0) * 100, 1),
                        "role_sources": list(source_counts.keys())[:3],
                        "role_atypique": False,
                        "points_gagnes_sideout": pts_so,
                        "ratio_points_pct": ratio_points,
                        "break_point_ratio_pct": break_ratio,
                        "sideout_contribution_pct": sideout_contrib,
                        "stats": pms_entry,
                    }
                )

            if not role_principal_global and role_counts_local:
                role_principal_global = max(role_counts_local.items(), key=lambda item: item[1])[0]

            total_role_samples = sum(role_counts_local.values())
            role_summary_rows = []
            for r_c, r_count in sorted(role_counts_local.items(), key=lambda item: -item[1]):
                role_summary_rows.append(
                    {
                        "code": r_c,
                        "label": get_role_label(r_c),
                        "match_count": r_count,
                        "matches": r_count,
                        "pct": round((r_count / total_role_samples) * 100, 1) if total_role_samples else 0.0,
                        "score_pct": round((r_count / total_role_samples) * 100, 1) if total_role_samples else 0.0,
                    }
                )

            avg_conf = (sum(role_confidences) / len(role_confidences)) if role_confidences else 0.0
            consistency = (
                (role_counts_local.get(role_principal_global, 0) / total_role_samples)
                if total_role_samples and role_principal_global
                else 0.0
            )

            role_overview = {
                "available": bool(role_principal_global or role_summary_rows),
                "principal_code": role_principal_global,
                "principal_label": get_role_label(role_principal_global),
                "plausibility_pct": round(avg_conf * 100, 1),
                "consistency_pct": round(consistency * 100, 1),
                "average_confidence_pct": round(avg_conf * 100, 1),
                "coverage_pct": round((role_known_count / len(filtered_stats_rows)) * 100, 1) if filtered_stats_rows else 0.0,
                "match_count": total_role_samples,
                "roles": role_summary_rows,
                "sources": [{"label": k, "count": v} for k, v in sorted(source_counts.items(), key=lambda i: -i[1])],
                "evidence": evidence_items[:15],
            }

        recent_matchs = []
        for row in filtered_rows[:10]:
            match = row["match"]
            equipe_joueur = row["equipe_joueur"]
            adversaire = row["adversaire"]
            side = row["side"]
            score = f"{match.sets_equipe_a or 0}-{match.sets_equipe_b or 0}" if match.match_joue else "—"
            dom_ext = "Domicile" if side == "A" else ("Extérieur" if side == "B" else "Inconnu")
            recent_matchs.append(
                {
                    "match_id": match.id,
                    "date": match.date_match,
                    "competition_id": row["competition"].id if row["competition"] else None,
                    "equipe_nom": equipe_joueur.nom if equipe_joueur else "?",
                    "equipe_id": equipe_joueur.id if equipe_joueur else None,
                    "adversaire_nom": adversaire.nom if adversaire else "?",
                    "adversaire_id": adversaire.id if adversaire else None,
                    "club_id": row["club"].id if row["club"] else None,
                    "club_nom": row["club"].nom if row["club"] else None,
                    "score": score,
                    "victoire": row["victoire"],
                    "niveau": row["niveau"],
                    "domicile_exterieur": dom_ext,
                }
            )

        match_rows = []
        for row in filtered_rows:
            match = row["match"]
            side = row["side"]
            competition = row["competition"]
            score = f"{match.sets_equipe_a or 0}-{match.sets_equipe_b or 0}" if match.match_joue else "—"
            dom_ext = "Domicile" if side == "A" else ("Extérieur" if side == "B" else "Inconnu")
            match_rows.append(
                {
                    "match_id": match.id,
                    "date": match.date_match,
                    "saison": row["saison"].code if row["saison"] else None,
                    "competition": competition.nom if competition else None,
                    "competition_id": competition.id if competition else None,
                    "equipe_id": row["equipe_joueur"].id if row["equipe_joueur"] else None,
                    "equipe_nom": row["equipe_joueur"].nom if row["equipe_joueur"] else "?",
                    "adversaire_id": row["adversaire"].id if row["adversaire"] else None,
                    "adversaire_nom": row["adversaire"].nom if row["adversaire"] else "?",
                    "niveau": row["niveau"],
                    "score": score,
                    "victoire": row["victoire"],
                    "domicile_exterieur": dom_ext,
                }
            )

        # Points géographiques pour la carte Leaflet
        map_markers = []
        for row in filtered_rows:
            match = row["match"]
            home_team = match.equipe_a
            if not home_team or not home_team.club:
                continue
            club = home_team.club
            lat = club.latitude
            lng = club.longitude
            if lat is None or lng is None:
                for salle in club.salles:
                    if salle.latitude is not None and salle.longitude is not None:
                        lat = salle.latitude
                        lng = salle.longitude
                        break
            if lat is None or lng is None:
                continue

            color = "#22c55e" if row["victoire"] is True else ("#ef4444" if row["victoire"] is False else "#3b82f6")
            map_markers.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "label": f"{row['equipe_joueur'].nom if row['equipe_joueur'] else '?'} vs {row['adversaire'].nom if row['adversaire'] else '?'}",
                    "color": color,
                    "popup_html": (
                        f"<strong><a href='/matchs/{match.code_match or match.id}'>"
                        f"{row['equipe_joueur'].nom if row['equipe_joueur'] else '?'} vs {row['adversaire'].nom if row['adversaire'] else '?'}"
                        f"</a></strong><br>"
                        f"{match.date_match.strftime('%d/%m/%Y') if match.date_match else 'Date inconnue'}"
                        f"<br>{'Domicile' if row['side'] == 'A' else ('Extérieur' if row['side'] == 'B' else 'Inconnu')}"
                    ),
                }
            )

        active_filter_count = sum(
            1
            for cond in [
                selected_saison_ids,
                date_from_obj or date_to_obj,
                selected_equipe_ids,
                selected_club_ids,
                selected_competition_ids,
                selected_niveaux,
                resultat,
                domicile_exterieur,
            ]
            if cond
        )

        allowed_tabs = {"resume", "stats", "matchs", "carte"}
        initial_tab = tab if tab in allowed_tabs else "resume"

        carriere_stats_obj = JoueurCarriereStatsRepository(session).get_for_joueur(joueur_id)
        saison_stats_rows = JoueurSaisonStatsRepository(session).get_for_joueur(joueur_id)

        level_counts: dict[str, int] = defaultdict(int)
        for r in filtered_rows:
            lvl = r.get("niveau") or "Niveau inconnu"
            level_counts[lvl] += 1

        level_distribution = [
            {
                "label": lvl,
                "count": cnt,
                "pct": round((cnt / len(filtered_rows)) * 100, 1) if filtered_rows else 0.0,
            }
            for lvl, cnt in sorted(level_counts.items(), key=lambda x: -x[1])
        ]
        level_distribution_total = sum(level_counts.values())

        clubs_timeline: dict[int, dict] = {}
        for r in base_rows:
            c = r.get("club")
            if not c:
                continue
            if c.id not in clubs_timeline:
                clubs_timeline[c.id] = {
                    "id": c.id,
                    "nom": c.nom,
                    "match_count": 0,
                    "saisons": set(),
                }
            clubs_timeline[c.id]["match_count"] += 1
            if r.get("saison") and r["saison"].code:
                clubs_timeline[c.id]["saisons"].add(r["saison"].code)

        for c_data in clubs_timeline.values():
            c_data["saisons"] = sorted(list(c_data["saisons"]), key=season_sort_key, reverse=True)

        current_club = clubs_timeline.get(current_club_id) if current_club_id else None
        former_clubs = [
            c_data
            for cid, c_data in clubs_timeline.items()
            if cid != current_club_id
        ]

        player_profile = {
            "current_saison_id": None,
            "current_saison_label": None,
            "current_club": current_club,
            "former_clubs": former_clubs,
            "best_level_current": None,
            "best_level_previous": None,
            "level_distribution": level_distribution,
            "level_distribution_total": level_distribution_total,
        }

        return {
            "joueur": joueur,
            "matchs": matchs,
            "stats": stats,
            "carriere_stats": carriere_stats_obj,
            "saison_stats": saison_stats_rows,
            "recent_matchs": recent_matchs,
            "match_rows": match_rows,
            "player_profile": player_profile,
            "estimated_age": estimated_age,
            "numero_stats": numero_stats,
            "jersey_cards": jersey_cards,
            "jersey_profile": jersey_profile,
            "level_timeline": level_timeline,
            "level_rank_labels": level_rank_labels,
            "level_reference_order_text": level_reference_order_text,
            "level_timeline_summary": level_timeline_summary,
            "aggregated_stats": aggregated_stats,
            "role_overview": role_overview,
            "per_match_stats": per_match_stats,
            "match_evolution_stats": match_evolution_stats,
            "initial_tab": initial_tab,
            "filter_options": filter_options,
            "hide_filters": hide_filters,
            "filter_state": {
                "saison_ids": sorted(selected_saison_ids),
                "date_from": date_from_obj.isoformat() if date_from_obj else "",
                "date_to": date_to_obj.isoformat() if date_to_obj else "",
                "equipe_ids": sorted(selected_equipe_ids),
                "club_ids": sorted(selected_club_ids),
                "competition_ids": sorted(selected_competition_ids),
                "niveaux": sorted(selected_niveaux),
                "resultat": resultat or "",
                "domicile_exterieur": domicile_exterieur or "",
            },
            "active_filter_count": active_filter_count,
            "base_match_count": len(base_rows),
            "map_markers": map_markers,
        }
