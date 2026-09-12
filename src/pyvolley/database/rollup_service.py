"""
Service de calcul et d'actualisation des statistiques agglomérées (Rollups).

Ce service gère la génération des tables dimensionnelles d'agrégation :
- stats_joueur_saison (Stats par joueur, saison, compétition, équipe)
- stats_joueur_carriere (Synthèse de carrière par joueur)
- stats_equipe_saison (Bilan, ratios et classements par équipe et par saison)

Il supporte à la fois le calcul par batch (pour tout ou partie de la base)
et les mises à jour incrémentales ultra-rapides après l'import d'un match.
"""

from __future__ import annotations

import logging
from collections import defaultdict, Counter
from datetime import datetime, date as dt_date
from typing import Optional, Sequence

from sqlalchemy import select, func, or_, and_, desc, asc, distinct
from sqlalchemy.orm import Session

from pyvolley.database.models import (
    MatchDB, SetDB, EquipeDB, JoueurDB, ParticipationMatchDB,
    JoueurMatchStatsDB, JoueurSaisonStatsDB, JoueurCarriereStatsDB,
    EquipeSaisonStatsDB, SaisonDB, CompetitionDB, PouleDB,
    ClubDB, ClubStatsDB,
)
from pyvolley.database.repositories import (
    JoueurSaisonStatsRepository,
    JoueurCarriereStatsRepository,
    EquipeSaisonStatsRepository,
    ClubStatsRepository,
)
from pyvolley.shared.categorisation import (
    normalize_categorie,
    is_youth_category,
    category_age_limit,
)

logger = logging.getLogger(__name__)

ROLLUP_CHUNK_SIZE = 2000


def _chunked(seq: Sequence, size: int = ROLLUP_CHUNK_SIZE):
    """Découpe une séquence en sous-séquences de taille maximale `size`."""
    seq_list = list(seq) if not isinstance(seq, (list, tuple)) else seq
    for i in range(0, len(seq_list), size):
        yield seq_list[i:i + size]


class RollupStatsService:
    """Service de calcul et gestion des statistiques agglomérées."""

    def __init__(self, session: Session):
        self.session = session
        self.joueur_saison_repo = JoueurSaisonStatsRepository(session)
        self.joueur_carriere_repo = JoueurCarriereStatsRepository(session)
        self.equipe_saison_repo = EquipeSaisonStatsRepository(session)
        self.club_stats_repo = ClubStatsRepository(session)

    # =================================================================
    # 0. Statistiques Joueur par Match (JMS)
    # =================================================================

    def compute_all_player_match_stats(self, saison_id: Optional[int] = None, force: bool = True) -> int:
        """Calcule et persiste joueur_match_stats pour les matchs avec détails."""
        from pyvolley.database.player_stats_service import JoueurMatchStatsService
        service = JoueurMatchStatsService(self.session)

        stmt = select(MatchDB).where(MatchDB.has_details.is_(True))
        if saison_id:
            stmt = stmt.where(MatchDB.saison_id == saison_id)

        matches = list(self.session.scalars(stmt))
        count = 0
        for m in matches:
            count += service.compute_and_store_for_match(m, force=force)
        self.session.flush()
        return count

    # =================================================================
    # 1. Statistiques Joueur par Saison
    # =================================================================

    def compute_player_season_stats(
        self,
        saison_id: Optional[int] = None,
        joueur_ids: Optional[Sequence[int]] = None,
        batch_size: int = 500,
    ) -> int:
        """Calcule et met à jour les stats par saison pour les joueurs ciblés.

        Returns:
            Nombre d'enregistrements créés ou mis à jour.
        """
        # Récupérer les participations et les stats détaillées
        stmt = (
            select(
                ParticipationMatchDB.joueur_id,
                MatchDB.saison_id,
                MatchDB.competition_id,
                ParticipationMatchDB.equipe_id,
                MatchDB.id.label("match_id"),
                MatchDB.date_match,
                MatchDB.vainqueur,
                MatchDB.equipe_a_id,
                MatchDB.equipe_b_id,
                MatchDB.sets_equipe_a,
                MatchDB.sets_equipe_b,
                JoueurMatchStatsDB.points_gagnes,
                JoueurMatchStatsDB.points_perdus,
                JoueurMatchStatsDB.points_joues,
                JoueurMatchStatsDB.points_gagnes_service,
                JoueurMatchStatsDB.points_gagnes_sideout,
                JoueurMatchStatsDB.services,
                JoueurMatchStatsDB.series,
                JoueurMatchStatsDB.max_serie,
                JoueurMatchStatsDB.sets_joues,
                JoueurMatchStatsDB.sets_titulaire,
                JoueurMatchStatsDB.role_principal,
                JoueurMatchStatsDB.role_confiance,
                JoueurMatchStatsDB.role_scores,
            )
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .outerjoin(
                JoueurMatchStatsDB,
                and_(
                    JoueurMatchStatsDB.match_id == ParticipationMatchDB.match_id,
                    JoueurMatchStatsDB.joueur_id == ParticipationMatchDB.joueur_id,
                ),
            )
            .where(MatchDB.match_joue.is_(True))
        )

        if saison_id:
            stmt = stmt.where(MatchDB.saison_id == saison_id)

        rows = []
        if joueur_ids:
            clean_jids = list(set(joueur_ids))
            for j_chunk in _chunked(clean_jids):
                c_stmt = stmt.where(ParticipationMatchDB.joueur_id.in_(j_chunk))
                rows.extend(self.session.execute(c_stmt).all())
        else:
            rows = self.session.execute(stmt).all()

        if not rows:
            return 0

        # Regrouper par clé (joueur_id, saison_id, competition_id, equipe_id)
        grouped = defaultdict(list)
        for r in rows:
            key = (r.joueur_id, r.saison_id, r.competition_id, r.equipe_id)
            grouped[key].append(r)

        count = 0
        now = datetime.now()
        all_payloads: list[dict] = []

        for (j_id, s_id, comp_id, eq_id), match_list in grouped.items():
            if not s_id:
                continue

            matchs_joues = len(match_list)
            matchs_titulaire = 0
            victoires = 0
            defaites = 0
            sets_joues = 0
            sets_titulaire = 0
            pts_gagnes = 0
            pts_perdus = 0
            pts_joues = 0
            pts_service = 0
            pts_sideout = 0
            total_services = 0
            total_series = 0
            max_serie = 0
            roles_freq = defaultdict(int)

            for m in match_list:
                # Victoire / Défaite
                sets_a = m.sets_equipe_a or 0
                sets_b = m.sets_equipe_b or 0
                is_team_a = (eq_id == m.equipe_a_id)
                won = (is_team_a and sets_a > sets_b) or (not is_team_a and sets_b > sets_a)
                if won:
                    victoires += 1
                else:
                    defaites += 1

                if m.role_principal:
                    roles_freq[m.role_principal] += 1

                if m.sets_joues is not None and m.sets_joues > 0:
                    sets_joues += m.sets_joues
                    sets_titulaire += (m.sets_titulaire or 0)
                    if m.sets_titulaire and m.sets_titulaire > 0:
                        matchs_titulaire += 1
                else:
                    sets_match = (m.sets_equipe_a or 0) + (m.sets_equipe_b or 0)
                    sets_joues += max(1, sets_match)

                pts_gagnes += (m.points_gagnes or 0)
                pts_perdus += (m.points_perdus or 0)
                pts_joues += (m.points_joues or 0)
                pts_service += (m.points_gagnes_service or 0)
                pts_sideout += (m.points_gagnes_sideout or 0)

                srv = m.services or 0
                ser = m.series or 0
                m_ser = m.max_serie or 0

                total_services += srv
                total_series += ser
                if m_ser > max_serie:
                    max_serie = m_ser


            moyenne_services_par_serie = round(
                total_services / max(1, total_series), 2
            ) if total_series > 0 else 0.0

            ratio_points_gagnes = round(
                pts_gagnes / max(1, pts_joues), 3
            ) if pts_joues > 0 else 0.0

            total_role_matches = sum(roles_freq.values())
            if roles_freq and total_role_matches > 0:
                role_principal = max(roles_freq.items(), key=lambda x: x[1])[0]
                role_distribution = {
                    r: round(c / total_role_matches, 3) for r, c in roles_freq.items()
                }
                confidences = [
                    float(m.role_confiance) for m in match_list if m.role_confiance is not None and m.role_confiance > 0
                ]
                avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.50
                consistency = roles_freq[role_principal] / total_role_matches
                vol_factor = min(1.0, total_role_matches / 6.0)
                role_confiance = round(0.40 * avg_conf + 0.40 * consistency + 0.20 * vol_factor, 3)
            else:
                role_principal = None
                role_confiance = 0.0
                role_distribution = None

            payload = {
                "joueur_id": j_id,
                "saison_id": s_id,
                "competition_id": comp_id,
                "equipe_id": eq_id,
                "matchs_joues": matchs_joues,
                "matchs_titulaire": matchs_titulaire,
                "victoires": victoires,
                "defaites": defaites,
                "sets_joues": sets_joues,
                "sets_titulaire": sets_titulaire,
                "points_gagnes": pts_gagnes,
                "points_perdus": pts_perdus,
                "points_joues": pts_joues,
                "points_service": pts_service,
                "points_sideout": pts_sideout,
                "services": total_services,
                "series": total_series,
                "max_serie": max_serie,
                "moyenne_services_par_serie": moyenne_services_par_serie,
                "ratio_points_gagnes": ratio_points_gagnes,
                "role_principal": role_principal,
                "role_confiance": role_confiance,
                "roles_frequence": dict(roles_freq) if roles_freq else None,
                "role_distribution": role_distribution,
                "updated_at": now,
            }
            all_payloads.append(payload)

        if all_payloads:
            self.joueur_saison_repo.bulk_upsert(all_payloads, batch_size=batch_size)
            self.session.flush()

        return len(all_payloads)

    # =================================================================
    # 2. Statistiques Joueur Carrière
    # =================================================================

    def compute_player_career_stats(
        self,
        joueur_ids: Optional[Sequence[int]] = None,
        batch_size: int = 500,
    ) -> int:
        """Calcule et met à jour les synthèses de carrière des joueurs."""
        # Calcul basé sur stats_joueur_saison et participations
        stmt = (
            select(
                JoueurSaisonStatsDB.joueur_id,
                func.sum(JoueurSaisonStatsDB.matchs_joues).label("total_matchs"),
                func.sum(JoueurSaisonStatsDB.victoires).label("total_victoires"),
                func.sum(JoueurSaisonStatsDB.defaites).label("total_defaites"),
                func.sum(JoueurSaisonStatsDB.sets_joues).label("total_sets"),
                func.sum(JoueurSaisonStatsDB.points_gagnes).label("total_points_gagnes"),
                func.sum(JoueurSaisonStatsDB.points_joues).label("total_points_joues"),
                func.sum(JoueurSaisonStatsDB.services).label("total_services"),
                func.sum(JoueurSaisonStatsDB.series).label("total_series"),
                func.max(JoueurSaisonStatsDB.max_serie).label("max_serie_carriere"),
                func.count(func.distinct(JoueurSaisonStatsDB.saison_id)).label("saisons_count"),
                func.count(func.distinct(JoueurSaisonStatsDB.equipe_id)).label("clubs_frequentes_count"),
            )
            .group_by(JoueurSaisonStatsDB.joueur_id)
        )

        clean_jids = list(set(joueur_ids)) if joueur_ids else None

        rows = []
        if clean_jids:
            for j_chunk in _chunked(clean_jids):
                c_stmt = stmt.where(JoueurSaisonStatsDB.joueur_id.in_(j_chunk))
                rows.extend(self.session.execute(c_stmt).all())
        else:
            rows = self.session.execute(stmt).all()

        if not rows:
            return 0

        # Trouver également les dates premier/dernier match et max points en 1 match
        dates_stmt = (
            select(
                ParticipationMatchDB.joueur_id,
                func.min(MatchDB.date_match).label("premier_match"),
                func.max(MatchDB.date_match).label("dernier_match"),
            )
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(MatchDB.match_joue.is_(True))
            .group_by(ParticipationMatchDB.joueur_id)
        )
        dates_map = {}
        if clean_jids:
            for j_chunk in _chunked(clean_jids):
                c_dates_stmt = dates_stmt.where(ParticipationMatchDB.joueur_id.in_(j_chunk))
                for r in self.session.execute(c_dates_stmt).all():
                    dates_map[r.joueur_id] = (r.premier_match, r.dernier_match)
        else:
            for r in self.session.execute(dates_stmt).all():
                dates_map[r.joueur_id] = (r.premier_match, r.dernier_match)

        # Max points sur un seul match
        max_pts_stmt = (
            select(
                JoueurMatchStatsDB.joueur_id,
                func.max(JoueurMatchStatsDB.points_gagnes).label("max_pts"),
            )
            .group_by(JoueurMatchStatsDB.joueur_id)
        )
        max_pts_map = {}
        if clean_jids:
            for j_chunk in _chunked(clean_jids):
                c_max_pts_stmt = max_pts_stmt.where(JoueurMatchStatsDB.joueur_id.in_(j_chunk))
                for r in self.session.execute(c_max_pts_stmt).all():
                    max_pts_map[r.joueur_id] = (r.max_pts or 0)
        else:
            for r in self.session.execute(max_pts_stmt).all():
                max_pts_map[r.joueur_id] = (r.max_pts or 0)

        # Analyse des catégories et niveaux pour chaque joueur
        cats_stmt = (
            select(
                ParticipationMatchDB.joueur_id,
                MatchDB.categorie,
                MatchDB.niveau_badge,
                MatchDB.niveau_rank,
                MatchDB.date_match,
                SaisonDB.date_fin,
            )
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .outerjoin(SaisonDB, MatchDB.saison_id == SaisonDB.id)
            .where(MatchDB.match_joue.is_(True))
        )
        cat_rows = []
        if clean_jids:
            for j_chunk in _chunked(clean_jids):
                c_cats_stmt = cats_stmt.where(ParticipationMatchDB.joueur_id.in_(j_chunk))
                cat_rows.extend(self.session.execute(c_cats_stmt).all())
        else:
            cat_rows = self.session.execute(cats_stmt).all()

        player_meta: dict[int, dict] = defaultdict(lambda: {
            "birth_year_min": None,
            "best_cat": None,
            "max_rank": -1,
            "max_label": None,
        })
        for crow in cat_rows:
            jid = crow.joueur_id
            pm = player_meta[jid]
            # Niveau max
            rank = crow.niveau_rank if crow.niveau_rank is not None else -1
            if rank > pm["max_rank"]:
                pm["max_rank"] = rank
                pm["max_label"] = crow.niveau_badge

            # Catégorie & Âge
            cat = crow.categorie
            if cat:
                cat_norm = normalize_categorie(cat)
                if is_youth_category(cat_norm):
                    limit = category_age_limit(cat_norm)
                    if limit:
                        ref_y = crow.date_match.year if crow.date_match else (crow.date_fin.year if crow.date_fin else None)
                        if ref_y:
                            b_min = ref_y - limit
                            if pm["birth_year_min"] is None or b_min > pm["birth_year_min"]:
                                pm["birth_year_min"] = b_min
                                pm["best_cat"] = cat_norm

        # Rôles agrégés sur la carrière
        career_roles_stmt = select(
            JoueurSaisonStatsDB.joueur_id,
            JoueurSaisonStatsDB.roles_frequence,
            JoueurSaisonStatsDB.role_confiance,
            JoueurSaisonStatsDB.matchs_joues,
        )
        career_role_rows = []
        if clean_jids:
            for j_chunk in _chunked(clean_jids):
                c_cr_stmt = career_roles_stmt.where(JoueurSaisonStatsDB.joueur_id.in_(j_chunk))
                career_role_rows.extend(self.session.execute(c_cr_stmt).all())
        else:
            career_role_rows = self.session.execute(career_roles_stmt).all()

        career_roles_map: dict[int, dict] = defaultdict(lambda: {"freq": Counter(), "conf_sum": 0.0, "weight_sum": 0})
        for srow in career_role_rows:
            j_entry = career_roles_map[srow.joueur_id]
            if srow.roles_frequence:
                for r_name, r_cnt in srow.roles_frequence.items():
                    j_entry["freq"][r_name] += r_cnt
            m_cnt = srow.matchs_joues or 0
            if srow.role_confiance and m_cnt > 0:
                j_entry["conf_sum"] += float(srow.role_confiance) * m_cnt
                j_entry["weight_sum"] += m_cnt

        count = 0
        now = datetime.now()
        all_payloads: list[dict] = []

        for r in rows:
            premier_date, dernier_date = dates_map.get(r.joueur_id, (None, None))
            max_pts = max_pts_map.get(r.joueur_id, 0)
            pm = player_meta.get(r.joueur_id, {})
            b_year = pm.get("birth_year_min")
            est_age = (now.year - b_year) if b_year else None

            c_role_data = career_roles_map.get(r.joueur_id)
            if c_role_data and c_role_data["freq"]:
                c_freq = dict(c_role_data["freq"])
                c_total = sum(c_freq.values())
                c_principal = max(c_freq.items(), key=lambda x: x[1])[0]
                c_dist = {r_k: round(r_v / c_total, 3) for r_k, r_v in c_freq.items()}
                c_consistency = c_freq[c_principal] / max(1, c_total)
                avg_s_conf = (c_role_data["conf_sum"] / c_role_data["weight_sum"]) if c_role_data["weight_sum"] > 0 else 0.50
                c_vol_factor = min(1.0, c_total / 12.0)
                c_confiance = round(0.40 * avg_s_conf + 0.40 * c_consistency + 0.20 * c_vol_factor, 3)
            else:
                c_principal = None
                c_confiance = 0.0
                c_freq = None
                c_dist = None

            payload = {
                "joueur_id": r.joueur_id,
                "total_matchs": int(r.total_matchs or 0),
                "total_victoires": int(r.total_victoires or 0),
                "total_defaites": int(r.total_defaites or 0),
                "total_sets": int(r.total_sets or 0),
                "total_points_gagnes": int(r.total_points_gagnes or 0),
                "total_points_joues": int(r.total_points_joues or 0),
                "total_services": int(r.total_services or 0),
                "total_series": int(r.total_series or 0),
                "max_serie_carriere": int(r.max_serie_carriere or 0),
                "max_points_match": int(max_pts or 0),
                "clubs_frequentes_count": int(r.clubs_frequentes_count or 0),
                "saisons_count": int(r.saisons_count or 0),
                "premier_match_date": premier_date,
                "dernier_match_date": dernier_date,
                "estimated_birth_year_min": b_year,
                "estimated_max_age": est_age,
                "best_category_label": pm.get("best_cat"),
                "max_niveau_label": pm.get("max_label"),
                "max_niveau_rank": pm.get("max_rank", -1),
                "role_principal": c_principal,
                "role_confiance": c_confiance,
                "roles_frequence": c_freq,
                "role_distribution": c_dist,
                "updated_at": now,
            }
            all_payloads.append(payload)

        if all_payloads:
            self.joueur_carriere_repo.bulk_upsert(all_payloads, batch_size=batch_size)
            self.session.flush()

        return len(all_payloads)

    # =================================================================
    # 3. Statistiques Équipe par Saison
    # =================================================================

    def compute_team_season_stats(
        self,
        saison_id: Optional[int] = None,
        competition_id: Optional[int] = None,
        equipe_ids: Optional[Sequence[int]] = None,
        batch_size: int = 500,
    ) -> int:
        """Calcule et met à jour les bilans d'équipe par saison/compétition."""
        stmt = (
            select(MatchDB)
            .where(MatchDB.match_joue.is_(True))
            .order_by(MatchDB.date_match.asc(), MatchDB.id.asc())
        )

        if saison_id:
            stmt = stmt.where(MatchDB.saison_id == saison_id)
        if competition_id:
            stmt = stmt.where(MatchDB.competition_id == competition_id)
        matches = []
        if equipe_ids:
            clean_eq_ids = list(set(equipe_ids))
            for eq_chunk in _chunked(clean_eq_ids):
                c_stmt = stmt.where(
                    or_(
                        MatchDB.equipe_a_id.in_(eq_chunk),
                        MatchDB.equipe_b_id.in_(eq_chunk),
                    )
                )
                matches.extend(self.session.scalars(c_stmt).all())
            # Déduplication si un match implique deux équipes du même filtre
            seen_ids = set()
            dedup_matches = []
            for m in matches:
                if m.id not in seen_ids:
                    seen_ids.add(m.id)
                    dedup_matches.append(m)
            matches = dedup_matches
        else:
            matches = list(self.session.scalars(stmt).all())

        if not matches:
            return 0

        # Regrouper les matchs par (equipe_id, saison_id, competition_id)
        team_matches = defaultdict(list)
        for m in matches:
            if m.equipe_a_id:
                team_matches[(m.equipe_a_id, m.saison_id, m.competition_id)].append((m, "A"))
            if m.equipe_b_id:
                team_matches[(m.equipe_b_id, m.saison_id, m.competition_id)].append((m, "B"))

        count = 0
        now = datetime.now()
        all_payloads: list[dict] = []

        for (eq_id, s_id, comp_id), m_list in team_matches.items():
            if not eq_id or not s_id:
                continue

            matchs_joues = len(m_list)
            victoires = 0
            defaites = 0
            victoires_dom = 0
            victoires_ext = 0
            v_3_0 = 0
            v_3_1 = 0
            v_3_2 = 0
            d_2_3 = 0
            d_1_3 = 0
            d_0_3 = 0
            forfaits = 0
            sets_pour = 0
            sets_contre = 0
            points_pour = 0
            points_contre = 0
            points_ffvb = 0

            current_streak = 0
            max_streak = 0
            poule_id = None

            for m, side in m_list:
                if m.poule_id:
                    poule_id = m.poule_id

                if m.forfait:
                    is_double = getattr(m, "is_double_forfait", False)
                    is_my_forfait = is_double or (
                        getattr(m, "is_forfait_a", False) if side == "A" else getattr(m, "is_forfait_b", False)
                    )
                    is_opp_forfait = is_double or (
                        getattr(m, "is_forfait_b", False) if side == "A" else getattr(m, "is_forfait_a", False)
                    )

                    if is_double:
                        # Double forfait : les deux équipes ont forfait
                        forfaits += 1
                        defaites += 1
                        d_0_3 += 1
                        sets_contre += 3
                        points_ffvb -= 1
                        current_streak = current_streak - 1 if current_streak < 0 else -1
                        continue
                    elif is_my_forfait:
                        # Mon équipe a déclaré forfait
                        forfaits += 1
                        defaites += 1
                        d_0_3 += 1
                        sets_contre += 3
                        points_ffvb -= 1
                        current_streak = current_streak - 1 if current_streak < 0 else -1
                        continue
                    elif is_opp_forfait:
                        # Victoire par forfait de l'adversaire (3-0, +3 pts)
                        victoires += 1
                        if side == "A":
                            victoires_dom += 1
                        else:
                            victoires_ext += 1
                        v_3_0 += 1
                        sets_pour += 3
                        points_ffvb += 3
                        current_streak = current_streak + 1 if current_streak > 0 else 1
                        if current_streak > max_streak:
                            max_streak = current_streak
                        continue

                sets_my = (m.sets_equipe_a or 0) if side == "A" else (m.sets_equipe_b or 0)
                sets_opp = (m.sets_equipe_b or 0) if side == "A" else (m.sets_equipe_a or 0)

                sets_pour += sets_my
                sets_contre += sets_opp

                # Points FFVB
                if sets_my == 3 and sets_opp in (0, 1):
                    points_ffvb += 3
                elif sets_my == 3 and sets_opp == 2:
                    points_ffvb += 2
                elif sets_my == 2 and sets_opp == 3:
                    points_ffvb += 1

                # Somme des points réels marqués dans chaque set
                if m.sets:
                    for s in m.sets:
                        sc_a = s.score_a or 0
                        sc_b = s.score_b or 0
                        points_pour += sc_a if side == "A" else sc_b
                        points_contre += sc_b if side == "A" else sc_a

                won = sets_my > sets_opp
                if won:
                    victoires += 1
                    if side == "A":
                        victoires_dom += 1
                    else:
                        victoires_ext += 1

                    if sets_opp == 0:
                        v_3_0 += 1
                    elif sets_opp == 1:
                        v_3_1 += 1
                    else:
                        v_3_2 += 1

                    current_streak = current_streak + 1 if current_streak > 0 else 1
                    if current_streak > max_streak:
                        max_streak = current_streak
                else:
                    defaites += 1
                    if sets_my == 2:
                        d_2_3 += 1
                    elif sets_my == 1:
                        d_1_3 += 1
                    else:
                        d_0_3 += 1

                    current_streak = current_streak - 1 if current_streak < 0 else -1

            ratio_sets = round(sets_pour / max(1, sets_contre), 3) if sets_contre > 0 else float(sets_pour)
            ratio_points = round(points_pour / max(1, points_contre), 3) if points_contre > 0 else 0.0

            payload = {
                "equipe_id": eq_id,
                "saison_id": s_id,
                "competition_id": comp_id,
                "poule_id": poule_id,
                "matchs_joues": matchs_joues,
                "victoires": victoires,
                "defaites": defaites,
                "victoires_domicile": victoires_dom,
                "victoires_exterieur": victoires_ext,
                "victoires_3_0": v_3_0,
                "victoires_3_1": v_3_1,
                "victoires_3_2": v_3_2,
                "defaites_2_3": d_2_3,
                "defaites_1_3": d_1_3,
                "defaites_0_3": d_0_3,
                "forfaits": forfaits,
                "points_ffvb": points_ffvb,
                "sets_pour": sets_pour,
                "sets_contre": sets_contre,
                "ratio_sets": ratio_sets,
                "points_pour": points_pour,
                "points_contre": points_contre,
                "ratio_points": ratio_points,
                "serie_victoires_max": max_streak,
                "serie_en_cours": current_streak,
                "rang": None,
                "updated_at": now,
            }
            all_payloads.append(payload)

        # Calculer les rangs par poule / compétition
        grouped_by_poule = defaultdict(list)
        for p in all_payloads:
            grp_key = (p["saison_id"], p["competition_id"], p["poule_id"])
            grouped_by_poule[grp_key].append(p)

        for grp_key, grp_items in grouped_by_poule.items():
            grp_items.sort(
                key=lambda item: (
                    item["points_ffvb"],
                    item["ratio_sets"],
                    item["ratio_points"],
                    item["victoires"],
                    item["sets_pour"],
                    item["points_pour"],
                ),
                reverse=True,
            )
            for rank_num, p in enumerate(grp_items, start=1):
                p["rang"] = rank_num

        if all_payloads:
            self.equipe_saison_repo.bulk_upsert(all_payloads, batch_size=batch_size)
            self.session.flush()

        count = len(all_payloads)

        # Rafraîchir les caches de poule
        poule_ids = {p["poule_id"] for p in all_payloads if p.get("poule_id")}
        for pid in poule_ids:
            try:
                from pyvolley.analysis.classement import calculer_classement_complet
                poule_obj = self.session.get(PouleDB, pid)
                if poule_obj and poule_obj.competition_id:
                    cc = calculer_classement_complet(
                        self.session,
                        competition_id=poule_obj.competition_id,
                        poule_id=pid,
                    )
                    poule_obj.classement_cache = cc.model_dump(mode="json")
                    poule_obj.classement_updated_at = now
            except Exception as exc:
                logger.debug("Erreur cache poule %s: %s", pid, exc)

        self.session.flush()
        return count

    # =================================================================
    # 3b. Statistiques Club par Saison et Carrière
    # =================================================================

    def compute_club_stats(
        self,
        saison_id: Optional[int] = None,
        club_ids: Optional[Sequence[int]] = None,
        batch_size: int = 500,
    ) -> int:
        """Calcule et met à jour les stats agrégées par club (pour une saison ou au global)."""
        clean_cids = list(set(club_ids)) if club_ids else None

        # 1. Requête des stats équipes regroupées par club
        stmt = (
            select(
                EquipeDB.club_id,
                func.count(distinct(EquipeSaisonStatsDB.equipe_id)).label("nb_equipes"),
                func.sum(EquipeSaisonStatsDB.matchs_joues).label("matchs_joues"),
                func.sum(EquipeSaisonStatsDB.victoires).label("victoires"),
                func.sum(EquipeSaisonStatsDB.defaites).label("defaites"),
                func.sum(EquipeSaisonStatsDB.sets_pour).label("sets_pour"),
                func.sum(EquipeSaisonStatsDB.sets_contre).label("sets_contre"),
                func.sum(EquipeSaisonStatsDB.points_pour).label("points_pour"),
                func.sum(EquipeSaisonStatsDB.points_contre).label("points_contre"),
            )
            .join(EquipeDB, EquipeSaisonStatsDB.equipe_id == EquipeDB.id)
            .where(EquipeDB.club_id.is_not(None))
        )

        if saison_id:
            stmt = stmt.where(EquipeSaisonStatsDB.saison_id == saison_id)

        if clean_cids:
            stmt = stmt.where(EquipeDB.club_id.in_(clean_cids))

        stmt = stmt.group_by(EquipeDB.club_id)
        team_stats_rows = self.session.execute(stmt).all()

        # 2. Joueurs distincts par club
        joueurs_stmt = (
            select(
                EquipeDB.club_id,
                func.count(distinct(JoueurSaisonStatsDB.joueur_id)).label("nb_joueurs"),
            )
            .join(EquipeDB, JoueurSaisonStatsDB.equipe_id == EquipeDB.id)
            .where(EquipeDB.club_id.is_not(None))
        )
        if saison_id:
            joueurs_stmt = joueurs_stmt.where(JoueurSaisonStatsDB.saison_id == saison_id)
        if clean_cids:
            joueurs_stmt = joueurs_stmt.where(EquipeDB.club_id.in_(clean_cids))

        joueurs_stmt = joueurs_stmt.group_by(EquipeDB.club_id)
        nb_joueurs_map = {row.club_id: row.nb_joueurs for row in self.session.execute(joueurs_stmt)}

        count = 0
        now = datetime.now()
        all_payloads: list[dict] = []

        for r in team_stats_rows:
            cid = r.club_id
            m_joues = int(r.matchs_joues or 0)
            vic = int(r.victoires or 0)
            defa = int(r.defaites or 0)
            sp = int(r.sets_pour or 0)
            sc = int(r.sets_contre or 0)
            pp = int(r.points_pour or 0)
            pc = int(r.points_contre or 0)

            ratio_v = round(vic / max(1, m_joues), 4) if m_joues > 0 else 0.0
            ratio_s = round(sp / max(1, sc), 3) if sc > 0 else float(sp)
            ratio_p = round(pp / max(1, pc), 3) if pc > 0 else float(pp)

            payload = {
                "club_id": cid,
                "saison_id": saison_id,
                "nb_equipes_engagees": int(r.nb_equipes or 0),
                "nb_matchs_joues": m_joues,
                "nb_victoires": vic,
                "nb_defaites": defa,
                "ratio_victoires": ratio_v,
                "sets_pour": sp,
                "sets_contre": sc,
                "ratio_sets": ratio_s,
                "points_pour": pp,
                "points_contre": pc,
                "ratio_points": ratio_p,
                "nb_joueurs_distincts": nb_joueurs_map.get(cid, 0),
                "updated_at": now,
            }
            all_payloads.append(payload)

        if all_payloads:
            self.club_stats_repo.bulk_upsert(all_payloads, batch_size=batch_size)
            self.session.flush()

        return len(all_payloads)

    # =================================================================
    # 4. Actualisation Incrémentale Delta Match
    # =================================================================

    def apply_match_delta(self, match_id: int) -> dict:
        """Met à jour les statistiques agglomérées de manière incrémentale suite à l'import d'un match.

        Returns:
            Résumé des entités recalculées.
        """
        match = self.session.get(MatchDB, match_id)
        if not match or not match.saison_id:
            return {"status": "skipped", "reason": "match_or_season_not_found"}

        # Récupérer les joueurs ayant participé
        stmt_players = select(ParticipationMatchDB.joueur_id).where(ParticipationMatchDB.match_id == match_id)
        joueur_ids = list(self.session.scalars(stmt_players).all())

        # Recalculer les stats saison des joueurs du match
        n_player_seasons = 0
        n_player_careers = 0
        if joueur_ids:
            n_player_seasons = self.compute_player_season_stats(
                saison_id=match.saison_id,
                joueur_ids=joueur_ids,
            )
            n_player_careers = self.compute_player_career_stats(
                joueur_ids=joueur_ids,
            )

        # Recalculer les stats saison des 2 équipes
        n_teams = 0
        n_clubs = 0
        team_ids = [tid for tid in (match.equipe_a_id, match.equipe_b_id) if tid is not None]
        if team_ids:
            n_teams = self.compute_team_season_stats(
                saison_id=match.saison_id,
                competition_id=match.competition_id,
                equipe_ids=team_ids,
            )
            # Récupérer les clubs des équipes pour actualiser leurs stats
            club_ids = list(self.session.scalars(
                select(distinct(EquipeDB.club_id)).where(EquipeDB.id.in_(team_ids), EquipeDB.club_id.is_not(None))
            ))
            if club_ids:
                n_clubs = self.compute_club_stats(saison_id=match.saison_id, club_ids=club_ids)
                self.compute_club_stats(saison_id=None, club_ids=club_ids)

        # Rafraîchir le cache poule du match
        if match.poule_id and match.competition_id:
            try:
                from pyvolley.analysis.classement import calculer_classement_complet
                poule_obj = self.session.get(PouleDB, match.poule_id)
                if poule_obj:
                    cc = calculer_classement_complet(
                        self.session,
                        competition_id=match.competition_id,
                        poule_id=match.poule_id,
                    )
                    poule_obj.classement_cache = cc.model_dump(mode="json")
                    poule_obj.classement_updated_at = datetime.now()
                    self.session.flush()
            except Exception as exc:
                logger.debug("Erreur rafraîchissement cache poule %s: %s", match.poule_id, exc)

        return {
            "status": "updated",
            "match_id": match_id,
            "player_seasons_updated": n_player_seasons,
            "player_careers_updated": n_player_careers,
            "teams_updated": n_teams,
            "clubs_updated": n_clubs,
        }

    def apply_batch_deltas(self, match_ids: Sequence[int]) -> dict:
        """Met à jour les statistiques agglomérées en une seule passe consolidée pour un lot de matchs.

        Regroupe les saisons, poules, équipes et joueurs uniques affectés par l'ensemble des matchs,
        puis exécute les calculs de rollups sans aucune redondance.

        Returns:
            Résumé des entités recalculées.
        """
        clean_ids = [int(mid) for mid in set(match_ids) if mid is not None]
        if not clean_ids:
            return {"status": "skipped", "matches_count": 0}

        # Récupérer les métadonnées de tous les matchs par blocs sécurisés
        matches = []
        for chunk in _chunked(clean_ids):
            stmt = select(MatchDB).where(MatchDB.id.in_(chunk))
            matches.extend(self.session.scalars(stmt).all())

        if not matches:
            return {"status": "skipped", "matches_count": 0}

        saison_player_map: dict[int, set[int]] = defaultdict(set)
        all_joueur_ids: set[int] = set()
        saison_comp_teams_map: dict[tuple[int, int], set[int]] = defaultdict(set)
        poule_comp_map: set[tuple[int, int]] = set()

        # Map rapide match_id -> saison_id pour les joueurs
        match_saison_map = {m.id: m.saison_id for m in matches if m.saison_id}

        # Récupérer toutes les participations pour ces matchs en une seule passe par blocs
        for chunk in _chunked(clean_ids):
            stmt_parts = (
                select(ParticipationMatchDB.match_id, ParticipationMatchDB.joueur_id)
                .where(ParticipationMatchDB.match_id.in_(chunk))
            )
            for m_id, j_id in self.session.execute(stmt_parts):
                if j_id:
                    all_joueur_ids.add(j_id)
                    s_id = match_saison_map.get(m_id)
                    if s_id:
                        saison_player_map[s_id].add(j_id)

        for m in matches:
            if not m.saison_id:
                continue

            t_ids = [tid for tid in (m.equipe_a_id, m.equipe_b_id) if tid is not None]
            if t_ids and m.competition_id:
                saison_comp_teams_map[(m.saison_id, m.competition_id)].update(t_ids)

            if m.poule_id and m.competition_id:
                poule_comp_map.add((m.competition_id, m.poule_id))

        total_player_seasons = 0
        for s_id, j_ids in saison_player_map.items():
            total_player_seasons += self.compute_player_season_stats(
                saison_id=s_id,
                joueur_ids=list(j_ids),
            )

        total_player_careers = 0
        if all_joueur_ids:
            total_player_careers = self.compute_player_career_stats(
                joueur_ids=list(all_joueur_ids),
            )

        total_teams = 0
        for (s_id, comp_id), t_ids in saison_comp_teams_map.items():
            total_teams += self.compute_team_season_stats(
                saison_id=s_id,
                competition_id=comp_id,
                equipe_ids=list(t_ids),
            )

        total_poules = 0
        now = datetime.now()
        for comp_id, poule_id in poule_comp_map:
            try:
                from pyvolley.analysis.classement import calculer_classement_complet
                poule_obj = self.session.get(PouleDB, poule_id)
                if poule_obj:
                    cc = calculer_classement_complet(
                        self.session,
                        competition_id=comp_id,
                        poule_id=poule_id,
                    )
                    poule_obj.classement_cache = cc.model_dump(mode="json")
                    poule_obj.classement_updated_at = now
                    total_poules += 1
            except Exception as exc:
                logger.debug("Erreur rafraîchissement cache poule %s: %s", poule_id, exc)

        total_clubs = 0
        all_team_ids = set()
        for t_ids in saison_comp_teams_map.values():
            all_team_ids.update(t_ids)
        if all_team_ids:
            affected_club_ids = list(self.session.scalars(
                select(distinct(EquipeDB.club_id)).where(EquipeDB.id.in_(list(all_team_ids)), EquipeDB.club_id.is_not(None))
            ))
            if affected_club_ids:
                for s_id in saison_player_map.keys():
                    total_clubs += self.compute_club_stats(saison_id=s_id, club_ids=affected_club_ids)
                self.compute_club_stats(saison_id=None, club_ids=affected_club_ids)

        self.session.flush()

        return {
            "status": "updated",
            "matches_count": len(matches),
            "player_seasons_updated": total_player_seasons,
            "player_careers_updated": total_player_careers,
            "teams_updated": total_teams,
            "clubs_updated": total_clubs,
            "poules_updated": total_poules,
        }
