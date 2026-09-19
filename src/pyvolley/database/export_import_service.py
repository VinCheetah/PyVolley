"""
Service d'import Phase 1 : importation des données depuis l'export CSV FFVB.

Ce service prend des ``ExportMatchInfo`` (extraits de l'export CSV) et crée
ou met à jour les enregistrements correspondants en base de données :
- Saisons, Entités, Compétitions, Poules
- Clubs (identifiés par code FFVB — matching déterministe)
- Équipes, Matchs, Arbitres

Le matching des clubs est basé sur le ``code_ffvb`` (7 chiffres) fourni par
l'export CSV, avec fallback sur le matching par nom normalisé.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import select

from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo, ArbitreInfo
from pyvolley.scrapers.ffvb.adressier_scraper import AdressierClubInfo, SalleInfo
from pyvolley.shared.categorisation import normalize_genre, normalize_categorie
from pyvolley.shared.match_status import (
    compute_match_played,
    normalize_score_sets,
    sets_indicate_played,
)
from pyvolley.shared.match_scores import resolve_match_score, score_sets_to_pair
from pyvolley.database.club_matching import normalize_club_name
from pyvolley.database.models import (
    SaisonDB, EntiteFFVBDB, CompetitionDB, PouleDB,
    ClubDB, ClubAliasDB, EquipeDB, MatchDB,
    ArbitreDB, ArbitreMatchDB, ImportLogDB, SetDB,
    SalleClubDB,
)

from pyvolley.shared.niveau import classify_level
from pyvolley.core.geo_data import DEPT_TO_LIGUE, department_from_club_code
from pyvolley.core.geocoding import (
    geocode_address,
    geocode_addresses_batch,
    get_geocoding_cache,
)

logger = logging.getLogger(__name__)


_TEAM_SUFFIX_RE = re.compile(
    r"\s+(?:M|F|MASCULIN(?:E)?|FEMININ(?:E)?|LOISIR|SENIOR(?:E)?|U\d{1,2}|\d+)$",
    re.IGNORECASE,
)


def _split_postal_city(raw_value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not raw_value:
        return None, None
    cleaned = raw_value.strip()
    if not cleaned:
        return None, None

    # 1. 5 chiffres en tête : "75001 PARIS"
    m = re.match(r"^\s*(\d{5})\s+(.+?)\s*$", cleaned)
    if m:
        return m.group(1), m.group(2).strip() or None

    # 2. 4 chiffres en tête (zéro tronqué dans exports FFVB/Excel) : "0621 MANDELIEU", "6279 LEFOREST", "5900 LILLE"
    m = re.match(r"^\s*(\d{4})\s+(.+?)\s*$", cleaned)
    if m:
        digits = m.group(1)
        city = m.group(2).strip() or None
        normalized_cp = digits + "0"
        return normalized_cp, city

    # 3. Code postal en fin de chaîne : "MONS 30340", "PARIS 75015"
    m = re.match(r"^\s*(.+?)\s+(\d{5})\s*$", cleaned)
    if m:
        return m.group(2), m.group(1).strip() or None

    # 4. Code DROM à 3 chiffres : "976 KANI-KÉLI"
    m = re.match(r"^\s*(97\d)\s+(.+?)\s*$", cleaned)
    if m:
        return m.group(1), m.group(2).strip() or None

    return None, cleaned


def _department_from_postal(postal_code: Optional[str]) -> Optional[str]:
    if not postal_code:
        return None
    code = postal_code.strip()
    if code.startswith(("97", "98")) and len(code) >= 3:
        return code[:3]
    if code.startswith("20") and len(code) >= 3:
        return "2A" if code[2] in {"0", "1"} else "2B"
    if code.startswith("2A") or code.startswith("02A"):
        return "2A"
    if code.startswith("2B") or code.startswith("02B"):
        return "2B"
    if len(code) >= 2 and code[:2].isdigit():
        return code[:2]
    return None


def _infer_nom_court_from_teams(team_names: list[str], fallback_name: str) -> Optional[str]:
    if not team_names:
        return None

    cleaned_names: list[str] = []
    for name in team_names:
        if not name:
            continue
        normalized = _TEAM_SUFFIX_RE.sub("", name).strip(" -")
        if normalized:
            cleaned_names.append(normalized)

    if not cleaned_names:
        return None

    frequencies: dict[str, int] = {}
    for name in cleaned_names:
        frequencies[name] = frequencies.get(name, 0) + 1

    fallback_norm = normalize_club_name(fallback_name)
    best_name = max(
        frequencies.items(),
        key=lambda item: (item[1], item[0] == fallback_name, len(item[0])),
    )[0]

    if normalize_club_name(best_name) == fallback_norm:
        return None
    return best_name


class ExportImportService:
    """Service d'import basé sur l'export CSV FFVB (Phase 1).

    Usage typique::

        with get_session() as session:
            service = ExportImportService(session)
            stats = service.import_matches(matches, entite_code, saison)
            session.commit()
    """

    def __init__(self, session: Session):
        self.session = session
        # Caches pour éviter les requêtes répétitives
        self._saison_cache: dict[str, SaisonDB] = {}
        self._entite_cache: dict[str, EntiteFFVBDB] = {}
        self._competition_cache: dict[tuple, CompetitionDB] = {}
        self._poule_cache: dict[tuple, PouleDB] = {}
        self._club_cache: dict[str, ClubDB] = {}  # code_ffvb → ClubDB
        self._club_name_cache: dict[str, ClubDB] = {}  # normalized_name → ClubDB
        self._all_clubs_normalized_cache: Optional[dict[str, ClubDB]] = None
        self._equipe_cache: dict[tuple, EquipeDB] = {}
        self._arbitre_cache: dict[str, ArbitreDB] = {}  # licence → ArbitreDB

    @staticmethod
    def _has_adressier_data(club: ClubDB) -> bool:
        """Retourne True si le club semble déjà enrichi via l'adressier."""
        scalar_fields = (
            club.ligue,
            club.couleurs,
            club.president,
            club.entraineur,
            club.entraineur_adjoint,
            club.correspondant_nom,
            club.correspondant_adresse,
            club.correspondant_ville,
            club.correspondant_telephone,
            club.correspondant_portable,
            club.correspondant_email,
        )
        if any(value and str(value).strip() for value in scalar_fields):
            return True

        return bool(club.salles)

    def clear_caches(self) -> None:
        """Vide tous les caches internes."""
        for cache in (
            self._saison_cache, self._entite_cache, self._competition_cache,
            self._poule_cache, self._club_cache, self._club_name_cache,
            self._equipe_cache, self._arbitre_cache,
        ):
            cache.clear()
        self._all_clubs_normalized_cache = None

    # =================================================================
    # Import principal
    # =================================================================

    def import_matches(
        self,
        matches: list[ExportMatchInfo],
        entite_code: str,
        saison_code: str,
    ) -> dict:
        """Importe une liste de matchs depuis l'export CSV.

        Args:
            matches: Liste d'ExportMatchInfo.
            entite_code: Code de l'entité source.
            saison_code: Saison au format ``YYYY/YYYY``.

        Returns:
            Dict avec les statistiques d'import :
            ``{"imported": N, "updated": N, "duplicates": N, "errors": N}``
        """
        stats = {"imported": 0, "updated": 0, "duplicates": 0, "errors": 0}

        # Normaliser la saison (YYYY/YYYY → YYYY-YYYY pour le stockage)
        saison_db_code = saison_code.replace("/", "-")

        # Créer l'entrée d'audit
        log_entry = ImportLogDB(
            operation="scrape",
            source=f"export_csv:{entite_code}:{saison_code}",
            total_attempted=len(matches),
        )
        self.session.add(log_entry)
        self.session.flush()

        # Résoudre les entités parentes
        saison = self._get_or_create_saison(saison_db_code)

        # Détecter le nom/type d'entité depuis les métadonnées enrichies
        entite_nom = None
        if matches:
            first = matches[0]
            entite_nom = getattr(first, 'entite_nom', None)
        entite = self._get_or_create_entite(entite_code, nom=entite_nom)

        # ── Pré-chargement en BLOC des entités pour éliminer les N+1 SELECT et autoflushes ──
        all_club_codes = {
            m.club_a_code_ffvb for m in matches if m.club_a_code_ffvb
        } | {
            m.club_b_code_ffvb for m in matches if m.club_b_code_ffvb
        }
        if all_club_codes:
            for i in range(0, len(all_club_codes), 900):
                chunk = list(all_club_codes)[i : i + 900]
                for c in self.session.scalars(select(ClubDB).where(ClubDB.code_ffvb.in_(chunk))).all():
                    if c.code_ffvb:
                        self._club_cache[c.code_ffvb] = c

        all_licences = {
            a.licence for m in matches for a in m.arbitres if a.licence
        }
        if all_licences:
            for i in range(0, len(all_licences), 900):
                chunk = list(all_licences)[i : i + 900]
                for a in self.session.scalars(select(ArbitreDB).where(ArbitreDB.licence.in_(chunk))).all():
                    if a.licence:
                        self._arbitre_cache[a.licence] = a

        if saison and saison.id:
            for comp in self.session.scalars(select(CompetitionDB).where(CompetitionDB.saison_id == saison.id)).all():
                key = (comp.nom, comp.saison_id, comp.genre, comp.categorie, comp.entite_id)
                self._competition_cache[key] = comp

            for p in self.session.scalars(
                select(PouleDB).join(CompetitionDB).where(CompetitionDB.saison_id == saison.id)
            ).all():
                self._poule_cache[(p.code, p.competition_id)] = p

            for eq in self.session.scalars(select(EquipeDB).where(EquipeDB.saison_id == saison.id)).all():
                self._equipe_cache[(eq.nom, eq.saison_id, eq.competition_id)] = eq

        # Pré-charger les matchs existants par clé composite (code_match, competition_id)
        existing_matches_map: dict[tuple[str, int], MatchDB] = {}
        all_codes = [m.code_match for m in matches if m.code_match]
        if all_codes and saison and saison.id:
            for i in range(0, len(all_codes), 900):
                chunk = all_codes[i : i + 900]
                for m_db in self.session.scalars(
                    select(MatchDB).where(
                        MatchDB.saison_id == saison.id,
                        MatchDB.code_match.in_(chunk),
                    )
                ).all():
                    if m_db.competition_id:
                        existing_matches_map[(m_db.code_match, m_db.competition_id)] = m_db

        batch_size = 200
        with self.session.no_autoflush:
            for idx, match_info in enumerate(matches, 1):
                try:
                    result = self._import_single_match(
                        match_info, saison, entite,
                        existing_matches_map=existing_matches_map,
                    )
                    stats[result] += 1
                    if idx % batch_size == 0:
                        self.session.flush()
                except Exception as e:
                    logger.error(
                        "Erreur import match %s: %s",
                        match_info.code_match, e,
                    )
                    try:
                        self.session.rollback()
                    except Exception:
                        pass
                    self.clear_caches()
                    saison = self._get_or_create_saison(saison_db_code)
                    entite = self._get_or_create_entite(entite_code, nom=entite_nom)
                    stats["errors"] += 1

        self.session.flush()

        # Finaliser l'audit
        log_entry.finished_at = datetime.now()
        log_entry.imported = stats["imported"]
        log_entry.updated = stats["updated"]
        log_entry.duplicates = stats["duplicates"]
        log_entry.errors = stats["errors"]
        plausibility_stats = self._collect_plausibility_stats(matches)
        matches_with_issues = plausibility_stats.get("matches_with_issues")
        if isinstance(matches_with_issues, (int, float)) and matches_with_issues > 0:
            log_entry.summary = json.dumps(
                {"scrape_plausibility": plausibility_stats},
                ensure_ascii=False,
            )
        log_entry.status = "success" if stats["errors"] == 0 else "partial"

        logger.info(
            "Import %s: %d importés, %d mis à jour, %d doublons, %d erreurs",
            entite_code,
            stats["imported"], stats["updated"],
            stats["duplicates"], stats["errors"],
        )

        return stats

    def _collect_plausibility_stats(
        self,
        matches: list[ExportMatchInfo],
    ) -> dict[str, object]:
        by_action: dict[str, int] = {}
        by_rule: dict[str, int] = {}
        total_issues = 0
        matches_with_issues = 0

        for match in matches:
            summary = getattr(match, "plausibility_summary", None)
            if not summary:
                continue
            matches_with_issues += 1
            total_issues += int(summary.get("total", 0) or 0)

            for action, count in (summary.get("by_action") or {}).items():
                by_action[action] = by_action.get(action, 0) + int(count)
            for rule_id, count in (summary.get("by_rule") or {}).items():
                by_rule[rule_id] = by_rule.get(rule_id, 0) + int(count)

        return {
            "matches_with_issues": matches_with_issues,
            "total_issues": total_issues,
            "by_action": by_action,
            "by_rule": by_rule,
        }

    # =================================================================
    # Import d'un match individuel
    # =================================================================

    def _import_single_match(
        self,
        match_info: ExportMatchInfo,
        saison: SaisonDB,
        entite: EntiteFFVBDB,
        existing_match: Optional[MatchDB] = None,
        existing_matches_map: Optional[dict[tuple[str, int], MatchDB]] = None,
    ) -> str:
        """Importe un seul match. Retourne le type de résultat."""

        # 1. Résoudre d'abord la compétition pour avoir la clé composite d'unicité
        competition = self._get_or_create_competition(
            match_info, saison, entite
        )

        # 2. Vérifier si le match existe déjà dans cette compétition
        existing = existing_match
        if existing is None and existing_matches_map is not None and competition and competition.id:
            existing = existing_matches_map.get((match_info.code_match, competition.id))

        if existing is None and competition and competition.id:
            existing = self.session.execute(
                select(MatchDB).where(
                    MatchDB.code_match == match_info.code_match,
                    MatchDB.saison_id == saison.id,
                    MatchDB.competition_id == competition.id,
                )
            ).scalar_one_or_none()

        if existing:
            # Garde-fou de cohérence sportive : refuser l'écrasement si les clubs sont différents
            if (
                existing.club_a_code_ffvb
                and match_info.club_a_code_ffvb
                and existing.club_a_code_ffvb != match_info.club_a_code_ffvb
            ):
                logger.warning(
                    "Collision détectée sur le match %s (competition %s) : clubs différents (%s vs %s). Écrasement refusé.",
                    match_info.code_match,
                    competition.nom if competition else None,
                    existing.club_a_code_ffvb,
                    match_info.club_a_code_ffvb,
                )
                return "duplicates"
            return self._update_match_if_needed(existing, match_info)

        # Utiliser le code de base pour les poules avec phase aller/retour.
        # Par exemple, "PMAA" (aller) et "PMAR" (retour) doivent partager
        # la même poule "PMA" au lieu de créer deux poules distinctes.
        effective_poule_code = (
            match_info.poule_code_ffvb
            if match_info.poule_code_ffvb
            else match_info.poule_code
        )
        poule = self._get_or_create_poule(
            effective_poule_code, competition,
            poule_nom=match_info.competition_nom,
            entite_code=match_info.entite_code,
            saison_code=match_info.saison,
            poule_code_ffvb=match_info.poule_code_ffvb,
        )

        # Résoudre les clubs et équipes
        equipe_a = self._resolve_equipe(
            match_info.equipe_a_nom,
            match_info.club_a_code_ffvb,
            saison, competition,
            match_info=match_info,
        )
        equipe_b = self._resolve_equipe(
            match_info.equipe_b_nom,
            match_info.club_b_code_ffvb,
            saison, competition,
            match_info=match_info,
        )

        normalized_score_sets = normalize_score_sets(
            match_info.score_sets,
            replace_forfeit_with_zero=match_info.forfait,
        ) or match_info.score_sets
        score_resolution = resolve_match_score(
            normalized_score_sets,
            None,
            legacy_score=normalized_score_sets,
        )
        computed_played = compute_match_played(
            vainqueur=match_info.vainqueur,
            score_sets=normalized_score_sets,
            sets=match_info.sets,
            sets_a=match_info.sets_equipe_a,
            sets_b=match_info.sets_equipe_b,
            forfait=match_info.forfait,
            declared_played=match_info.match_joue,
            trust_declared=True,
        )
        has_details = sets_indicate_played(match_info.sets)

        classification = classify_level(
            competition_name=competition.nom if competition else None,
            niveau=competition.niveau if competition else match_info.niveau,
            categorie=competition.categorie if competition else match_info.categorie_age,
            division=competition.division if competition else match_info.division,
        )

        cat_val = competition.categorie if competition else match_info.categorie_age
        if not cat_val and not classification.is_youth:
            cat_val = "SENIOR"

        sets_detail_export = [
            {"numero": idx, "score_a": sa, "score_b": sb}
            for idx, (sa, sb) in enumerate(match_info.sets, start=1)
        ] if match_info.sets else None

        match_db = MatchDB(
            code_match=match_info.code_match,
            date_match=match_info.date_match,
            heure_match=match_info.heure,
            salle=match_info.salle,
            journee=match_info.journee,
            saison_id=saison.id,
            competition_id=competition.id if competition else None,
            poule_id=poule.id if poule else None,
            equipe_a_id=equipe_a.id if equipe_a else None,
            equipe_b_id=equipe_b.id if equipe_b else None,
            club_a_code_ffvb=match_info.club_a_code_ffvb,
            club_b_code_ffvb=match_info.club_b_code_ffvb,
            vainqueur=match_info.vainqueur,
            score_sets=score_resolution.score_effective,
            score_export=score_resolution.score_export,
            score_pdf=score_resolution.score_pdf,
            sets_detail_export=sets_detail_export,
            sets_equipe_a=match_info.sets_equipe_a,
            sets_equipe_b=match_info.sets_equipe_b,
            match_joue=computed_played,
            forfait=match_info.forfait,
            type_forfait=match_info.type_forfait,
            has_details=has_details,
            score_source="export" if computed_played else None,
            parsing_status="discovered",
            source_url=match_info.feuille_match_url,
            genre=competition.genre if competition else match_info.genre,
            categorie=cat_val,
            niveau=classification.categorie_principale,
            division=classification.division,
            niveau_badge=classification.label,
            niveau_rank=classification.rank,
        )

        self.session.add(match_db)
        if existing_matches_map is not None and competition and competition.id:
            existing_matches_map[(match_db.code_match, competition.id)] = match_db

        # Scores détaillés de sets depuis l'export CSV (phase scraping)
        if match_info.sets and has_details:
            self._replace_match_sets_from_export(match_db, match_info)
            match_db.has_details = True
            match_db.score_source = "export"

        # Arbitres
        for arb_info in match_info.arbitres:
            self._import_arbitre(match_db, arb_info)

        return "imported"

    def _update_match_if_needed(
        self,
        existing: MatchDB,
        match_info: ExportMatchInfo,
    ) -> str:
        """Met à jour un match existant si les nouvelles données sont plus riches."""
        updated = False
        parsed_locked = existing.parsing_status == "parsed"
        normalized_score_sets = normalize_score_sets(
            match_info.score_sets,
            replace_forfeit_with_zero=match_info.forfait,
        ) or match_info.score_sets
        score_resolution = resolve_match_score(
            normalized_score_sets,
            None,
            legacy_score=normalized_score_sets,
        )
        computed_played = compute_match_played(
            vainqueur=match_info.vainqueur,
            score_sets=normalized_score_sets,
            sets=match_info.sets,
            sets_a=match_info.sets_equipe_a,
            sets_b=match_info.sets_equipe_b,
            forfait=match_info.forfait,
            declared_played=match_info.match_joue,
            trust_declared=True,
        )

        # Si l'URL source change significativement, reprogrammer un passage download+parse propre.
        new_source_url = (match_info.feuille_match_url or "").strip() or None
        url_changed = False
        if new_source_url and existing.source_url:
            norm_existing = existing.source_url.rstrip("/").replace("http://", "https://")
            norm_new = new_source_url.rstrip("/").replace("http://", "https://")
            url_changed = (norm_existing != norm_new)
        elif new_source_url != existing.source_url:
            url_changed = True

        if url_changed and new_source_url:
            existing.source_url = new_source_url
            updated = True

            if existing.parsing_status in {"downloaded", "parsed", "error"}:
                existing.parsing_status = "discovered"
                existing.source_pdf = None
                existing.parsed_at = None

        # Mettre à jour les champs manquants ou enrichis
        if not existing.date_match and match_info.date_match:
            existing.date_match = match_info.date_match
            updated = True
        if not existing.heure_match and match_info.heure:
            existing.heure_match = match_info.heure
            updated = True
        if not existing.salle and match_info.salle:
            existing.salle = match_info.salle
            updated = True
        if not existing.club_a_code_ffvb and match_info.club_a_code_ffvb:
            existing.club_a_code_ffvb = match_info.club_a_code_ffvb
            updated = True
        if match_info.sets:
            new_sets_export = [
                {"numero": idx, "score_a": sa, "score_b": sb}
                for idx, (sa, sb) in enumerate(match_info.sets, start=1)
            ]
            if existing.sets_detail_export != new_sets_export:
                existing.sets_detail_export = new_sets_export
                updated = True

        if score_resolution.score_export and existing.score_export != score_resolution.score_export:
            existing.score_export = score_resolution.score_export
            updated = True

        # Le score de l'export prévaut pour le résultat officiel
        if computed_played and score_resolution.score_export:
            if existing.score_sets != score_resolution.score_effective:
                existing.score_sets = score_resolution.score_effective
                updated = True
            if (match_info.sets_equipe_a is not None and match_info.sets_equipe_b is not None) and (
                existing.sets_equipe_a != match_info.sets_equipe_a or existing.sets_equipe_b != match_info.sets_equipe_b
            ):
                existing.sets_equipe_a = match_info.sets_equipe_a
                existing.sets_equipe_b = match_info.sets_equipe_b
                updated = True
            if match_info.vainqueur and existing.vainqueur != match_info.vainqueur:
                existing.vainqueur = match_info.vainqueur
                updated = True

        # Ne pas écraser les données PDF détaillées (SetDB) avec l'export CSV.
        if not parsed_locked:
            if score_resolution.score_export and existing.score_export != score_resolution.score_export:
                existing.score_export = score_resolution.score_export
                updated = True
            if existing.score_pdf is None:
                if existing.score_sets != score_resolution.score_effective:
                    existing.score_sets = score_resolution.score_effective
                    updated = True
                if match_info.vainqueur and existing.vainqueur != match_info.vainqueur:
                    existing.vainqueur = match_info.vainqueur
                    updated = True
                if match_info.sets_equipe_a is not None and existing.sets_equipe_a != match_info.sets_equipe_a:
                    existing.sets_equipe_a = match_info.sets_equipe_a
                    updated = True
                if match_info.sets_equipe_b is not None and existing.sets_equipe_b != match_info.sets_equipe_b:
                    existing.sets_equipe_b = match_info.sets_equipe_b
                    updated = True
                if computed_played:
                    if not existing.match_joue:
                        existing.match_joue = True
                        updated = True
                    if bool(existing.forfait) != bool(match_info.forfait):
                        existing.forfait = match_info.forfait
                        updated = True
                    if existing.type_forfait != match_info.type_forfait:
                        existing.type_forfait = match_info.type_forfait
                        updated = True

            can_overwrite_score = (existing.score_source in {None, "export"}) or (not existing.match_joue)

            # Mettre à jour le score export si le match est joué et que les données changent.
            if computed_played and can_overwrite_score:
                score_changed = (
                    (not existing.match_joue)
                    or existing.vainqueur != match_info.vainqueur
                    or existing.score_sets != normalized_score_sets
                    or (existing.sets_equipe_a or 0) != (match_info.sets_equipe_a or 0)
                    or (existing.sets_equipe_b or 0) != (match_info.sets_equipe_b or 0)
                    or bool(existing.forfait) != bool(match_info.forfait)
                    or existing.type_forfait != match_info.type_forfait
                    or existing.score_source != "export"
                )
                if score_changed:
                    existing.match_joue = True
                    existing.vainqueur = match_info.vainqueur
                    if existing.score_pdf is None:
                        existing.score_sets = score_resolution.score_effective
                    existing.sets_equipe_a = match_info.sets_equipe_a or 0
                    existing.sets_equipe_b = match_info.sets_equipe_b or 0
                    existing.forfait = match_info.forfait
                    existing.type_forfait = match_info.type_forfait
                    existing.score_export = score_resolution.score_export
                    existing.score_source = "export"
                    updated = True

            # Corriger les faux positifs (match marqué joué sans résultat réel)
            if (not computed_played) and existing.match_joue and existing.score_source in {None, "export"}:
                existing.match_joue = False
                existing.vainqueur = None
                existing.score_sets = None
                existing.score_export = None
                existing.sets_equipe_a = 0
                existing.sets_equipe_b = 0
                existing.forfait = False
                if existing.score_source == "export":
                    existing.score_source = None

                # Supprimer les sets injectés par export (si présents)
                for old_set in list(existing.sets):
                    self.session.delete(old_set)
                existing.has_details = False
                updated = True

            # Ajouter/rafraîchir les sets détaillés si disponibles en export
            if (
                match_info.sets
                and sets_indicate_played(match_info.sets)
                and (existing.score_source in {None, "export"} or not existing.has_details)
            ):
                old_scores = [
                    (s.score_a, s.score_b)
                    for s in existing.sets
                    if s.score_a is not None and s.score_b is not None
                ]
                if old_scores != match_info.sets:
                    self._replace_match_sets_from_export(existing, match_info)
                    existing.has_details = True
                    existing.score_source = "export"
                    existing.score_export = score_resolution.score_export
                    updated = True

        if updated:
            existing.updated_at = datetime.now()
            return "updated"
        return "duplicates"

    def _replace_match_sets_from_export(self, match_db: MatchDB, match_info: ExportMatchInfo) -> None:
        """Remplace les sets d'un match par les scores détaillés de l'export."""
        match_db.sets.clear()
        for idx, (score_a, score_b) in enumerate(match_info.sets, start=1):
            match_db.sets.append(
                SetDB(
                    numero=idx,
                    score_a=score_a,
                    score_b=score_b,
                )
            )

    # =================================================================
    # Résolution des entités
    # =================================================================

    def _get_or_create_saison(self, code: str) -> SaisonDB:
        """Récupère ou crée une saison avec les dates de début/fin."""
        if code in self._saison_cache:
            return self._saison_cache[code]

        saison = self.session.execute(
            select(SaisonDB).where(SaisonDB.code == code)
        ).scalar_one_or_none()

        if not saison:
            from datetime import date as datetime_date
            parts = code.split("-")
            annee_debut = int(parts[0])
            annee_fin = int(parts[1]) if len(parts) > 1 else annee_debut + 1
            saison = SaisonDB(
                code=code,
                nom=f"Saison {code}",
                date_debut=datetime_date(annee_debut, 9, 1),
                date_fin=datetime_date(annee_fin, 6, 30),
            )
            self.session.add(saison)
            self.session.flush()

        self._saison_cache[code] = saison
        return saison

    def _get_or_create_entite(self, code: str, nom: Optional[str] = None) -> EntiteFFVBDB:
        """Récupère ou crée une entité FFVB.

        Args:
            code: Code de l'entité (ex: "ABCCS", "LIRA", "PTRA38").
            nom: Nom optionnel de l'entité (pour enrichir).
        """
        if code in self._entite_cache:
            entite = self._entite_cache[code]
            # Enrichir le nom si on a mieux que le code
            if nom and entite.nom == code:
                entite.nom = nom
            return entite

        entite = self.session.execute(
            select(EntiteFFVBDB).where(EntiteFFVBDB.code == code)
        ).scalar_one_or_none()

        if not entite:
            from pyvolley.scrapers.ffvb.entities import detect_entity_type
            entity_type = detect_entity_type(code, nom or "")
            entite = EntiteFFVBDB(
                code=code,
                nom=nom or code,
                type=entity_type,
            )
            self.session.add(entite)
            self.session.flush()
        elif nom and entite.nom == code:
            entite.nom = nom

        self._entite_cache[code] = entite
        return entite

    def _get_or_create_competition(
        self,
        match_info: ExportMatchInfo,
        saison: SaisonDB,
        entite: EntiteFFVBDB,
    ) -> CompetitionDB:
        """Résout ou crée une compétition depuis les métadonnées du match.

        Utilise les champs ``competition_nom``, ``competition_groupe``,
        ``genre``, ``categorie_age``, ``niveau``, ``division`` renseignés
        par ``enrich_matches_with_competition_info`` pour créer des
        compétitions riches et bien structurées.

        Le regroupement se fait par ``competition_groupe`` (heading parent
        de la page d'accueil FFVB) : toutes les poules d'un même groupe
        partagent la même compétition. Par exemple, les poules EMA, EMB,
        EMC sont toutes rattachées à la compétition « ELITE MASCULINE ».

        Quand ``competition_groupe`` n'est pas disponible, on utilise le
        code de poule comme clé de regroupement.
        """
        # Clé de regroupement : les poules d'un même heading partagent
        # une compétition. Le heading est typiquement "ELITE MASCULINE",
        # "NATIONALE 2 FÉMININE", etc.
        comp_key_name = match_info.competition_groupe or match_info.poule_code

        # Normaliser genre et catégorie AVANT le cache et la recherche DB
        genre = normalize_genre(match_info.genre) or normalize_genre(comp_key_name)
        categorie = normalize_categorie(match_info.categorie_age) or normalize_categorie(comp_key_name)

        classification = classify_level(
            competition_name=comp_key_name,
            niveau=match_info.niveau,
            categorie=categorie,
            division=match_info.division or match_info.division_code,
        )
        if not categorie and not classification.is_youth:
            categorie = "SENIOR"

        entite_id = entite.id if entite else None
        cache_key = (comp_key_name, saison.id, genre, categorie, entite_id)
        if cache_key in self._competition_cache:
            return self._competition_cache[cache_key]

        # 1. Chercher par nom + saison + genre + catégorie + entité
        stmt = (
            select(CompetitionDB)
            .where(
                CompetitionDB.nom == comp_key_name,
                CompetitionDB.saison_id == saison.id,
            )
        )
        if entite_id is not None:
            stmt = stmt.where(CompetitionDB.entite_id == entite_id)
        else:
            stmt = stmt.where(CompetitionDB.entite_id.is_(None))
        if genre:
            stmt = stmt.where(CompetitionDB.genre == genre)
        else:
            stmt = stmt.where(CompetitionDB.genre.is_(None))
        if categorie:
            stmt = stmt.where(CompetitionDB.categorie == categorie)
        else:
            stmt = stmt.where(CompetitionDB.categorie.is_(None))

        competition = self.session.execute(stmt).scalar_one_or_none()

        # 2. Fallback : chercher par nom + saison + genre + entité
        if not competition and genre:
            stmt_cg = select(CompetitionDB).where(
                CompetitionDB.nom == comp_key_name,
                CompetitionDB.saison_id == saison.id,
                CompetitionDB.genre == genre,
            )
            if entite_id is not None:
                stmt_cg = stmt_cg.where(CompetitionDB.entite_id == entite_id)
            else:
                stmt_cg = stmt_cg.where(CompetitionDB.entite_id.is_(None))
            competition = self.session.execute(stmt_cg).scalars().first()

        # 3. Fallback : chercher par nom + saison + entité
        if not competition:
            stmt_nom = select(CompetitionDB).where(
                CompetitionDB.nom == comp_key_name,
                CompetitionDB.saison_id == saison.id,
            )
            if entite_id is not None:
                stmt_nom = stmt_nom.where(CompetitionDB.entite_id == entite_id)
            else:
                stmt_nom = stmt_nom.where(CompetitionDB.entite_id.is_(None))
            candidates = self.session.execute(stmt_nom).scalars().all()
            if len(candidates) == 1:
                competition = candidates[0]

        if not competition:
            # Extraire un code court
            code_comp = match_info.poule_code
            if match_info.division_code:
                # Compétitions jeunes : utiliser le code division
                code_comp = match_info.division_code
            elif match_info.competition_groupe:
                # Essayer d'extraire un code depuis le nom du groupe
                m = re.match(r'^([A-Z0-9]{2,6})\s*-', match_info.competition_groupe)
                if m:
                    code_comp = m.group(1)

            try:
                with self.session.begin_nested():
                    competition = CompetitionDB(
                        nom=comp_key_name,
                        code_competition=code_comp,
                        genre=genre,
                        categorie=categorie,
                        niveau=classification.categorie_principale,
                        division=classification.division,
                        niveau_badge=classification.label,
                        niveau_rank=classification.rank,
                        saison_id=saison.id,
                        entite_id=entite_id,
                    )
                    self.session.add(competition)
                    self.session.flush()
            except IntegrityError:
                # En cas de conflit d'unicité, récupérer l'enregistrement existant
                stmt_conflict = select(CompetitionDB).where(
                    CompetitionDB.nom == comp_key_name,
                    CompetitionDB.saison_id == saison.id,
                    CompetitionDB.genre == genre,
                    CompetitionDB.categorie == categorie,
                )
                if entite_id is not None:
                    stmt_conflict = stmt_conflict.where(CompetitionDB.entite_id == entite_id)
                else:
                    stmt_conflict = stmt_conflict.where(CompetitionDB.entite_id.is_(None))
                competition = self.session.execute(stmt_conflict).scalar_one_or_none()
                if not competition and genre:
                    stmt_cg = select(CompetitionDB).where(
                        CompetitionDB.nom == comp_key_name,
                        CompetitionDB.saison_id == saison.id,
                        CompetitionDB.genre == genre,
                    )
                    if entite_id is not None:
                        stmt_cg = stmt_cg.where(CompetitionDB.entite_id == entite_id)
                    else:
                        stmt_cg = stmt_cg.where(CompetitionDB.entite_id.is_(None))
                    competition = self.session.execute(stmt_cg).scalars().first()
                if not competition:
                    stmt_cs = select(CompetitionDB).where(
                        CompetitionDB.nom == comp_key_name,
                        CompetitionDB.saison_id == saison.id,
                    )
                    if entite_id is not None:
                        stmt_cs = stmt_cs.where(CompetitionDB.entite_id == entite_id)
                    else:
                        stmt_cs = stmt_cs.where(CompetitionDB.entite_id.is_(None))
                    competition = self.session.execute(stmt_cs).scalars().first()

        # Enrichir si des métadonnées manquent
        if competition:
            updated = False
            if not competition.genre and genre:
                competition.genre = genre
                updated = True
            if not competition.categorie and categorie:
                competition.categorie = categorie
                updated = True
            if not competition.niveau_badge or competition.niveau_rank == -1:
                classification = classify_level(
                    competition_name=competition.nom,
                    niveau=competition.niveau or match_info.niveau,
                    categorie=competition.categorie or categorie,
                    division=competition.division or match_info.division or match_info.division_code,
                )
                competition.niveau = classification.categorie_principale
                competition.division = classification.division
                competition.niveau_badge = classification.label
                competition.niveau_rank = classification.rank
                updated = True
            if not competition.entite_id and entite_id:
                competition.entite_id = entite_id
                updated = True
            if updated:
                try:
                    with self.session.begin_nested():
                        self.session.flush()
                except IntegrityError:
                    pass

            self._competition_cache[cache_key] = competition
            canonical_key = (
                competition.nom,
                competition.saison_id,
                competition.genre,
                competition.categorie,
                competition.entite_id,
            )
            self._competition_cache[canonical_key] = competition
            raw_key = (
                comp_key_name,
                saison.id,
                match_info.genre,
                match_info.categorie_age,
                entite_id,
            )
            self._competition_cache[raw_key] = competition

        return competition

    def _get_or_create_poule(
        self,
        poule_code: str,
        competition: CompetitionDB,
        poule_nom: Optional[str] = None,
        entite_code: Optional[str] = None,
        saison_code: Optional[str] = None,
        poule_code_ffvb: Optional[str] = None,
    ) -> PouleDB:
        """Résout ou crée une poule.

        Args:
            poule_code: Code de la poule (ex: "EMA", "2FA").
            competition: Compétition parente.
            poule_nom: Nom complet optionnel (ex: "ELITE MASCULINE - POULE A").
            entite_code: Code entité pour construire les URLs FFVB.
            saison_code: Saison pour construire les URLs FFVB.
            poule_code_ffvb: Code poule FFVB résolu (ex: "DSF" pour "DSFA").
                Si non fourni, utilise poule_code pour les URLs.
        """
        cache_key = (poule_code, competition.id)
        if cache_key in self._poule_cache:
            return self._poule_cache[cache_key]

        poule = self.session.execute(
            select(PouleDB).where(
                PouleDB.code == poule_code,
                PouleDB.competition_id == competition.id,
            )
        ).scalar_one_or_none()

        if not poule:
            nom = poule_nom or f"Poule {poule_code}"
            try:
                with self.session.begin_nested():
                    poule = PouleDB(
                        code=poule_code,
                        nom=nom,
                        competition_id=competition.id,
                    )
                    self.session.add(poule)
                    self.session.flush()
            except IntegrityError:
                poule = self.session.execute(
                    select(PouleDB).where(
                        PouleDB.code == poule_code,
                        PouleDB.competition_id == competition.id,
                    )
                ).scalar_one_or_none()
        elif poule_nom and poule.nom == f"Poule {poule_code}":
            # Enrichir le nom si on a mieux
            poule.nom = poule_nom

        if poule:
            self._poule_cache[cache_key] = poule
        return poule

    def _resolve_club(
        self,
        nom: Optional[str],
        code_ffvb: Optional[str],
    ) -> Optional[ClubDB]:
        """Résout un club par son code FFVB (priorité) ou par nom.

        Le matching par ``code_ffvb`` est déterministe et fiable.
        Le matching par nom est un fallback.
        """
        if not nom and not code_ffvb:
            return None

        # 1. Matching par code FFVB (priorité absolue)
        if code_ffvb:
            if code_ffvb in self._club_cache:
                return self._club_cache[code_ffvb]

            club = self.session.execute(
                select(ClubDB).where(ClubDB.code_ffvb == code_ffvb)
            ).scalar_one_or_none()

            if club:
                self._club_cache[code_ffvb] = club
                # Mettre à jour le nom si nécessaire
                if nom and not club.nom_court:
                    club.nom_court = nom
                return club

            # Créer le club avec le code FFVB (seule source autorisée pour créer un club)
            dept = department_from_club_code(code_ffvb)
            club = ClubDB(
                nom=nom or f"Club {code_ffvb}",
                code_ffvb=code_ffvb,
                departement=dept,
            )
            self.session.add(club)
            self.session.flush()
            self._club_cache[code_ffvb] = club
            return club

        # 2. Fallback : matching par nom normalisé UNIQUEMENT sur les clubs existants
        if nom:
            normalized = normalize_club_name(nom)
            if normalized in self._club_name_cache:
                return self._club_name_cache[normalized]

            # Chercher par alias
            alias = self.session.execute(
                select(ClubAliasDB).where(ClubAliasDB.alias == normalized)
            ).scalar_one_or_none()

            if alias:
                club = alias.club
                self._club_name_cache[normalized] = club
                return club

            # Chercher par nom normalisé via le cache mémoire
            if self._all_clubs_normalized_cache is None:
                self._all_clubs_normalized_cache = {}
                clubs = self.session.execute(select(ClubDB)).scalars().all()
                for c in clubs:
                    norm = normalize_club_name(c.nom)
                    if norm not in self._all_clubs_normalized_cache:
                        self._all_clubs_normalized_cache[norm] = c

            if normalized in self._all_clubs_normalized_cache:
                c = self._all_clubs_normalized_cache[normalized]
                self._club_name_cache[normalized] = c
                return c

            # RÈGLE MÉTIER : Ne JAMAIS créer de club sans code FFVB valide.
            # Si aucun club existant ne correspond, on ne crée pas de club fantôme.
            return None

        return None

    def _resolve_equipe(
        self,
        nom: Optional[str],
        code_ffvb: Optional[str],
        saison: SaisonDB,
        competition: Optional[CompetitionDB],
        match_info: Optional[ExportMatchInfo] = None,
    ) -> Optional[EquipeDB]:
        """Résout ou crée une équipe."""
        if not nom:
            return None

        cache_key = (nom, saison.id, competition.id if competition else None)
        if cache_key in self._equipe_cache:
            return self._equipe_cache[cache_key]

        comp_id = competition.id if competition else None
        equipe = self.session.execute(
            select(EquipeDB).where(
                EquipeDB.nom == nom,
                EquipeDB.saison_id == saison.id,
                EquipeDB.competition_id == comp_id,
            )
        ).scalar_one_or_none()

        if not equipe:
            club = self._resolve_club(nom, code_ffvb)

            # Extraire genre, catégorie, niveau, division
            genre = (match_info.genre if match_info else None) or (competition.genre if competition else None)
            categorie = (match_info.categorie_age if match_info else None) or (competition.categorie if competition else None)
            comp_nom = competition.nom if competition else None
            div_val = (match_info.division if match_info else None) or (competition.division if competition else None)

            classification = classify_level(
                competition_name=comp_nom,
                niveau=(match_info.niveau if match_info else None) or (competition.niveau if competition else None),
                categorie=categorie,
                division=div_val,
            )
            if not categorie and not classification.is_youth:
                categorie = "SENIOR"

            equipe = EquipeDB(
                nom=nom,
                genre=genre,
                categorie=categorie,
                niveau=classification.categorie_principale,
                division=classification.division,
                niveau_badge=classification.label,
                niveau_rank=classification.rank,
                club_id=club.id if club else None,
                saison_id=saison.id,
                competition_id=comp_id,
            )
            self.session.add(equipe)
            self.session.flush()
        elif not equipe.niveau_badge or equipe.niveau_rank == -1:
            classification = classify_level(
                competition_name=competition.nom if competition else None,
                niveau=equipe.niveau or (competition.niveau if competition else None),
                categorie=equipe.categorie or (competition.categorie if competition else None),
                division=equipe.division or (competition.division if competition else None),
            )
            equipe.niveau = classification.categorie_principale
            equipe.division = classification.division
            equipe.niveau_badge = classification.label
            equipe.niveau_rank = classification.rank

        self._equipe_cache[cache_key] = equipe
        return equipe

    # =================================================================
    # Arbitres
    # =================================================================

    def _import_arbitre(
        self,
        match_db: MatchDB,
        arb_info: ArbitreInfo,
    ) -> None:
        """Importe un arbitre et l'associe au match."""
        if not arb_info.nom and not arb_info.licence:
            return

        licence = arb_info.licence or None
        cache_key = licence or arb_info.nom

        if cache_key in self._arbitre_cache:
            arbitre = self._arbitre_cache[cache_key]
        else:
            # Chercher par licence
            arbitre = None
            if licence:
                arbitre = self.session.execute(
                    select(ArbitreDB).where(ArbitreDB.licence == licence)
                ).scalar_one_or_none()

            if not arbitre:
                arbitre = ArbitreDB(
                    licence=licence,
                    nom=arb_info.nom,
                    ligue=arb_info.ligue,
                    comite_departemental=arb_info.comite_departemental,
                )
                self.session.add(arbitre)

            self._arbitre_cache[cache_key] = arbitre

        # Déterminer le rôle (1er ou 2e arbitre)
        role = f"arbitre_{len(match_db.arbitrages) + 1}"

        # Vérifier qu'il n'est pas déjà assigné
        already_assigned = any(
            am.arbitre == arbitre or (arbitre.id is not None and am.arbitre_id == arbitre.id)
            for am in match_db.arbitrages
        )
        if not already_assigned:
            match_db.arbitrages.append(
                ArbitreMatchDB(
                    arbitre=arbitre,
                    role=role,
                )
            )

    # =================================================================
    # Enrichissement des clubs depuis l'adressier
    # =================================================================

    def enrich_clubs(
        self,
        clubs_info: list[AdressierClubInfo],
        entite_code: str,
        saison: str,
        base_url: str,
        force_reenrich: bool = False,
        geocode: bool = True,
    ) -> dict:
        """Enrichit les clubs en base avec les données de l'adressier FFVB.

        Met à jour les champs du club (adresse, correspondant, couleurs,
        dirigeants, salles) à partir des données de l'adressier.

        Args:
            clubs_info: Liste d'``AdressierClubInfo``.
            entite_code: Code de l'entité (pour construire les URLs).
            saison: Saison au format ``YYYY/YYYY``.
            base_url: URL de base FFVB.
            force_reenrich: Si ``True``, met à jour aussi les clubs déjà enrichis.

        Returns:
            Dict ``{"enriched": N, "created": N, "skipped": N}``.
        """
        stats = {"enriched": 0, "created": 0, "skipped": 0, "already_up_to_date": 0}

        # Pré-charger les clubs existants par code FFVB pour éviter les requêtes N+1
        all_codes = [c.code_ffvb for c in clubs_info if c.code_ffvb]
        existing_clubs_map: dict[str, ClubDB] = {}
        if all_codes:
            for i in range(0, len(all_codes), 900):
                chunk = all_codes[i : i + 900]
                for c in self.session.scalars(
                    select(ClubDB).where(ClubDB.code_ffvb.in_(chunk))
                ).all():
                    existing_clubs_map[c.code_ffvb] = c

        # Pré-géocodage ciblé par batch CSV (BAN) :
        # On ne traite que les clubs nouveaux ou dont les coordonnées manquent encore !
        batch_geo_results: dict[str, Optional[GeocodingResult]] = {}
        if geocode:
            geo_items = []
            for c_info in clubs_info:
                if not c_info.code_ffvb:
                    continue

                # Si le club existe déjà, qu'il est déjà enrichi et qu'on ne force pas la réécriture :
                existing_club = existing_clubs_map.get(c_info.code_ffvb)
                if not force_reenrich and existing_club and self._has_adressier_data(existing_club):
                    # Vérifier si club et salles ont déjà leurs coordonnées GPS
                    club_has_coords = existing_club.latitude is not None and existing_club.longitude is not None
                    salles_have_coords = all(
                        s.latitude is not None and s.longitude is not None
                        for s in existing_club.salles
                    )
                    if club_has_coords and (salles_have_coords or not existing_club.salles):
                        continue

                c_city = None
                if c_info.correspondant_ville:
                    _, c_city = _split_postal_city(c_info.correspondant_ville)
                c_dept = department_from_club_code(c_info.code_ffvb)
                c_ligue = getattr(c_info, "ligue", None) or (DEPT_TO_LIGUE.get(c_dept) if c_dept else None)
                for s_info in c_info.salles:
                    v = s_info.ville or c_city
                    salle_id = f"salle_{c_info.code_ffvb}_{s_info.numero}"
                    geo_items.append({
                        "id": salle_id,
                        "adresse": s_info.adresse,
                        "ville": v,
                        "nom": s_info.nom,
                        "departement": c_dept,
                        "ligue": c_ligue,
                    })
                if c_city:
                    club_id = f"club_{c_info.code_ffvb}"
                    geo_items.append({
                        "id": club_id,
                        "adresse": None,
                        "ville": c_city,
                        "nom": c_info.nom,
                        "departement": c_dept,
                        "ligue": c_ligue,
                    })
            if geo_items:
                batch_geo_results = geocode_addresses_batch(
                    geo_items,
                    use_cache=True,
                    allow_nominatim=False,
                )

        for club_info in clubs_info:
            if not club_info.code_ffvb:
                stats["skipped"] += 1
                continue

            dept = department_from_club_code(club_info.code_ffvb)

            # Trouver ou créer le club
            club = existing_clubs_map.get(club_info.code_ffvb)
            if not club:
                club = self.session.execute(
                    select(ClubDB).where(ClubDB.code_ffvb == club_info.code_ffvb)
                ).scalar_one_or_none()

            if not club:
                # Réconciliation : vérifier si un club existait sans code FFVB
                normalized = normalize_club_name(club_info.nom)
                existing_stub = self.session.execute(
                    select(ClubDB).where(ClubDB.code_ffvb.is_(None), ClubDB.nom == club_info.nom)
                ).scalars().first()
                if not existing_stub:
                    alias = self.session.execute(
                        select(ClubAliasDB).where(ClubAliasDB.alias == normalized)
                    ).scalar_one_or_none()
                    if alias and not alias.club.code_ffvb:
                        existing_stub = alias.club

                if existing_stub:
                    club = existing_stub
                    club.code_ffvb = club_info.code_ffvb
                    if not club.departement and dept:
                        club.departement = dept
                    stats["enriched"] += 1
                else:
                    club = ClubDB(
                        nom=club_info.nom,
                        code_ffvb=club_info.code_ffvb,
                        departement=dept,
                    )
                    self.session.add(club)
                    stats["created"] += 1
                existing_clubs_map[club_info.code_ffvb] = club
            else:
                if not force_reenrich and self._has_adressier_data(club):
                    stats["skipped"] += 1
                    stats["already_up_to_date"] += 1
                    continue
                stats["enriched"] += 1

            # Mettre à jour les champs
            club.nom = club_info.nom
            if not club.departement and dept:
                club.departement = dept
            if not club.nom_court:
                inferred_nom_court = _infer_nom_court_from_teams(
                    [equipe.nom for equipe in club.equipes if equipe.nom],
                    club_info.nom,
                )
                if inferred_nom_court:
                    club.nom_court = inferred_nom_court
            if club_info.ligue:
                club.ligue = club_info.ligue
            if club_info.couleurs:
                club.couleurs = club_info.couleurs
            if club_info.president:
                club.president = club_info.president
            if club_info.entraineur:
                club.entraineur = club_info.entraineur
            if club_info.entraineur_adjoint:
                club.entraineur_adjoint = club_info.entraineur_adjoint
            if club_info.correspondant_nom:
                club.correspondant_nom = club_info.correspondant_nom
            if club_info.correspondant_adresse:
                club.correspondant_adresse = club_info.correspondant_adresse
            if club_info.correspondant_ville:
                club.correspondant_ville = club_info.correspondant_ville
                postal_code, city_name = _split_postal_city(club_info.correspondant_ville)
                if city_name:
                    club.ville = city_name
                if not club.departement:
                    departement = _department_from_postal(postal_code)
                    if departement:
                        club.departement = departement
            if not club.departement and club.code_ffvb:
                club.departement = department_from_club_code(club.code_ffvb)
            if club_info.correspondant_telephone:
                club.correspondant_telephone = club_info.correspondant_telephone
            if club_info.correspondant_portable:
                club.correspondant_portable = club_info.correspondant_portable
            if club_info.correspondant_email:
                club.correspondant_email = club_info.correspondant_email

            # Salles — mise à jour in-place pour respecter la contrainte UNIQUE (club_id, numero)
            existing_salles = {s.numero: s for s in club.salles}
            new_numeros = {s_info.numero for s_info in club_info.salles}
            for num, s in list(existing_salles.items()):
                if num not in new_numeros:
                    self.session.delete(s)

            for salle_info in club_info.salles:
                lat, lng = None, None
                if geocode:
                    salle_id = f"salle_{club_info.code_ffvb}_{salle_info.numero}"
                    geo_res = batch_geo_results.get(salle_id)
                    if geo_res:
                        lat, lng = geo_res.latitude, geo_res.longitude

                if salle_info.numero in existing_salles:
                    salle = existing_salles[salle_info.numero]
                    salle.nom = salle_info.nom
                    salle.adresse = salle_info.adresse
                    salle.ville = salle_info.ville
                    salle.telephone = salle_info.telephone
                    salle.sol = salle_info.sol
                    salle.capacite = salle_info.capacite
                    salle.transport = salle_info.transport
                    if lat is not None and lng is not None:
                        salle.latitude = lat
                        salle.longitude = lng
                else:
                    club.salles.append(
                        SalleClubDB(
                            numero=salle_info.numero,
                            nom=salle_info.nom,
                            adresse=salle_info.adresse,
                            ville=salle_info.ville,
                            telephone=salle_info.telephone,
                            sol=salle_info.sol,
                            capacite=salle_info.capacite,
                            transport=salle_info.transport,
                            latitude=lat,
                            longitude=lng,
                        )
                    )

            # La localisation du club est celle de son siège social (adresse administrative),
            # tandis que les salles (gymnases) conservent leurs propres coordonnées distinctes.
            if club.latitude is None or club.longitude is None:
                # Si le club n'a pas encore de coordonnées, tenter le géocodage sur son siège social ou sa ville
                addr = club.adresse_siege or None
                city = f"{club.code_postal_siege or ''} {club.ville_siege or ''}".strip() or club.ville
                if (addr or city) and geocode:
                    c_d = club.departement or department_from_club_code(club.code_ffvb)
                    c_l = club.ligue or (DEPT_TO_LIGUE.get(c_d) if c_d else None)
                    city_geo = geocode_address(
                        adresse=addr,
                        ville=city,
                        nom=club.nom,
                        departement=c_d,
                        ligue=c_l,
                        allow_nominatim=False,
                    )
                    if city_geo:
                        club.latitude = city_geo.latitude
                        club.longitude = city_geo.longitude

        self.session.flush()
        if geocode:
            get_geocoding_cache().save()

        logger.info(
            "Enrichissement clubs %s: %d enrichis, %d créés, %d ignorés%s",
            entite_code,
            stats["enriched"], stats["created"], stats["skipped"],
            " (forcé)" if force_reenrich else "",
        )

        return stats
