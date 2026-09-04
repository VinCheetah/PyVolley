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

from sqlalchemy.orm import Session
from sqlalchemy import select

from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo, ArbitreInfo
from pyvolley.scrapers.ffvb.adressier_scraper import AdressierClubInfo, SalleInfo
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

logger = logging.getLogger(__name__)


_POSTAL_CITY_RE = re.compile(r"^\s*(\d{5})\s+(.+?)\s*$")
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

    match = _POSTAL_CITY_RE.match(cleaned)
    if not match:
        return None, cleaned

    postal_code = match.group(1)
    city = match.group(2).strip() or None
    return postal_code, city


def _department_from_postal(postal_code: Optional[str]) -> Optional[str]:
    if not postal_code or len(postal_code) != 5 or not postal_code.isdigit():
        return None

    if postal_code.startswith(("97", "98")):
        return postal_code[:3]

    if postal_code.startswith("20"):
        return "2A" if postal_code[2] in {"0", "1"} else "2B"

    return postal_code[:2]


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

        # Pré-charger les matchs existants pour éviter N+1 requêtes SELECT
        existing_matches_map: dict[str, MatchDB] = {}
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
                    existing_matches_map[m_db.code_match] = m_db

        for match_info in matches:
            try:
                with self.session.begin_nested():
                    result = self._import_single_match(
                        match_info, saison, entite,
                        existing_match=existing_matches_map.get(match_info.code_match),
                    )
                stats[result] += 1
            except Exception as e:
                logger.error(
                    "Erreur import match %s: %s",
                    match_info.code_match, e,
                )
                self.clear_caches()
                stats["errors"] += 1

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
    ) -> str:
        """Importe un seul match. Retourne le type de résultat."""

        # Vérifier si le match existe déjà
        existing = existing_match
        if existing is None:
            existing = self.session.execute(
                select(MatchDB).where(
                    MatchDB.code_match == match_info.code_match,
                    MatchDB.saison_id == saison.id,
                )
            ).scalar_one_or_none()

        if existing:
            return self._update_match_if_needed(existing, match_info)

        # Créer le match
        competition = self._get_or_create_competition(
            match_info, saison, entite
        )

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
            sets_equipe_a=match_info.sets_equipe_a,
            sets_equipe_b=match_info.sets_equipe_b,
            match_joue=computed_played,
            forfait=match_info.forfait,
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
        self.session.flush()

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

        # Si l'URL source change, reprogrammer un passage download+parse propre.
        new_source_url = (match_info.feuille_match_url or "").strip() or None
        if new_source_url and existing.source_url != new_source_url:
            existing.source_url = new_source_url
            updated = True

            if existing.parsing_status in {"downloaded", "parsed", "error"}:
                existing.parsing_status = "discovered"
                existing.source_pdf = None
                existing.parsed_at = None

        # Mettre à jour les champs manquants
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
        if not existing.club_b_code_ffvb and match_info.club_b_code_ffvb:
            existing.club_b_code_ffvb = match_info.club_b_code_ffvb
            updated = True

        # Ne pas écraser les données PDF détaillées avec l'export CSV.
        if not parsed_locked:
            existing.score_export = score_resolution.score_export
            if existing.score_pdf is None:
                existing.score_sets = score_resolution.score_effective
                existing.vainqueur = match_info.vainqueur
                existing.sets_equipe_a = match_info.sets_equipe_a
                existing.sets_equipe_b = match_info.sets_equipe_b
                if computed_played:
                    existing.match_joue = True
                    existing.forfait = match_info.forfait
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
                    or existing.score_source != "export"
                )
                if score_changed:
                    existing.match_joue = True
                    existing.vainqueur = match_info.vainqueur
                    if existing.score_pdf is None:
                        existing.score_sets = score_resolution.score_effective
                    existing.sets_equipe_a = match_info.sets_equipe_a
                    existing.sets_equipe_b = match_info.sets_equipe_b
                    existing.forfait = match_info.forfait
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
        for old_set in list(match_db.sets):
            self.session.delete(old_set)
        self.session.flush()

        for idx, (score_a, score_b) in enumerate(match_info.sets, start=1):
            self.session.add(
                SetDB(
                    match_id=match_db.id,
                    numero=idx,
                    score_a=score_a,
                    score_b=score_b,
                )
            )
        self.session.flush()

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
        genre = match_info.genre
        categorie = match_info.categorie_age

        cache_key = (comp_key_name, saison.id, genre, categorie)
        if cache_key in self._competition_cache:
            return self._competition_cache[cache_key]

        # Chercher par nom + saison + genre + catégorie
        stmt = (
            select(CompetitionDB)
            .where(
                CompetitionDB.nom == comp_key_name,
                CompetitionDB.saison_id == saison.id,
            )
        )
        if genre:
            stmt = stmt.where(CompetitionDB.genre == genre)
        else:
            stmt = stmt.where(CompetitionDB.genre.is_(None))
        if categorie:
            stmt = stmt.where(CompetitionDB.categorie == categorie)
        else:
            stmt = stmt.where(CompetitionDB.categorie.is_(None))

        competition = self.session.execute(stmt).scalar_one_or_none()

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

            classification = classify_level(
                competition_name=comp_key_name,
                niveau=match_info.niveau,
                categorie=categorie,
                division=match_info.division or match_info.division_code,
            )
            if not categorie and not classification.is_youth:
                categorie = "SENIOR"

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
                entite_id=entite.id,
            )
            self.session.add(competition)
            self.session.flush()

        # Enrichir si des métadonnées manquent
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
        if not competition.entite_id and entite:
            competition.entite_id = entite.id
            updated = True
        if updated:
            self.session.flush()

        self._competition_cache[cache_key] = competition
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
            poule = PouleDB(
                code=poule_code,
                nom=nom,
                competition_id=competition.id,
            )
            self.session.add(poule)
            self.session.flush()
        elif poule_nom and poule.nom == f"Poule {poule_code}":
            # Enrichir le nom si on a mieux
            poule.nom = poule_nom

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

            # Créer le club avec le code FFVB
            club = ClubDB(
                nom=nom or f"Club {code_ffvb}",
                code_ffvb=code_ffvb,
            )
            self.session.add(club)
            self.session.flush()
            self._club_cache[code_ffvb] = club
            return club

        # 2. Fallback : matching par nom normalisé
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

            # Créer le club sans code FFVB
            club = ClubDB(nom=nom)
            self.session.add(club)
            self.session.flush()
            # Ajouter l'alias
            alias_db = ClubAliasDB(alias=normalized, club_id=club.id)
            self.session.add(alias_db)
            self.session.flush()
            self._club_name_cache[normalized] = club
            self._all_clubs_normalized_cache[normalized] = club
            return club

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
                self.session.flush()

            self._arbitre_cache[cache_key] = arbitre

        # Déterminer le rôle (1er ou 2e arbitre)
        existing_roles = self.session.execute(
            select(ArbitreMatchDB).where(
                ArbitreMatchDB.match_id == match_db.id,
            )
        ).scalars().all()

        role = f"arbitre_{len(existing_roles) + 1}"

        # Vérifier qu'il n'est pas déjà assigné
        already_assigned = any(
            am.arbitre_id == arbitre.id for am in existing_roles
        )
        if not already_assigned:
            am = ArbitreMatchDB(
                arbitre_id=arbitre.id,
                match_id=match_db.id,
                role=role,
            )
            self.session.add(am)
            self.session.flush()

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
        stats = {"enriched": 0, "created": 0, "skipped": 0}

        for club_info in clubs_info:
            if not club_info.code_ffvb:
                stats["skipped"] += 1
                continue

            # Trouver ou créer le club
            club = self.session.execute(
                select(ClubDB).where(ClubDB.code_ffvb == club_info.code_ffvb)
            ).scalar_one_or_none()

            if not club:
                club = ClubDB(
                    nom=club_info.nom,
                    code_ffvb=club_info.code_ffvb,
                )
                self.session.add(club)
                self.session.flush()
                stats["created"] += 1
            else:
                if not force_reenrich and self._has_adressier_data(club):
                    stats["skipped"] += 1
                    continue
                stats["enriched"] += 1

            # Mettre à jour les champs
            club.nom = club_info.nom
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
                departement = _department_from_postal(postal_code)
                if departement:
                    club.departement = departement
            if club_info.correspondant_telephone:
                club.correspondant_telephone = club_info.correspondant_telephone
            if club_info.correspondant_portable:
                club.correspondant_portable = club_info.correspondant_portable
            if club_info.correspondant_email:
                club.correspondant_email = club_info.correspondant_email

            # Salles — supprimer les existantes et recréer
            for existing_salle in club.salles:
                self.session.delete(existing_salle)
            self.session.flush()

            for salle_info in club_info.salles:
                salle = SalleClubDB(
                    club_id=club.id,
                    numero=salle_info.numero,
                    nom=salle_info.nom,
                    adresse=salle_info.adresse,
                    ville=salle_info.ville,
                    telephone=salle_info.telephone,
                    sol=salle_info.sol,
                    capacite=salle_info.capacite,
                    transport=salle_info.transport,
                )
                self.session.add(salle)

            self.session.flush()

        logger.info(
            "Enrichissement clubs %s: %d enrichis, %d créés, %d ignorés%s",
            entite_code,
            stats["enriched"], stats["created"], stats["skipped"],
            " (forcé)" if force_reenrich else "",
        )

        return stats
