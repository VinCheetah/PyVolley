"""
Service de complétion et synchronisation des matchs depuis les calendriers FFVB.

Workflow :
  1. Interroge la base de données pour trouver les poules d'une saison.
  2. Récupère les matchs en ligne depuis les calendriers FFVB.
  3. **Crée** les matchs manquants (pas de feuille de match / matchs à venir).
  4. **Met à jour** les matchs existants : scores, date, heure, arbitres,
     journée, total de points, forfaits, vainqueur.

Usage::

    from sqlalchemy.orm import Session
    from pyvolley.database.score_completion import ScoreCompletionService

    service = ScoreCompletionService(session)
    stats = service.complete_scores_for_saison("2025-2026")
    print(stats)
"""

import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from pyvolley.database.models import (
    ArbitreDB,
    ArbitreMatchDB,
    CompetitionDB,
    EntiteFFVBDB,
    EquipeDB,
    MatchDB,
    PouleDB,
    SaisonDB,
    SetDB,
)
from pyvolley.database.import_service import MatchImportService
from pyvolley.scrapers.score_scraper import FFVBScoreScraper, OnlineMatchScore

logger = logging.getLogger(__name__)


# =====================================================================
# Service principal
# =====================================================================


class ScoreCompletionService:
    """Synchronise les matchs et scores depuis les calendriers en ligne FFVB.

    Gère deux axes :

    * **Complétion** — enrichit les matchs existants avec les données en
      ligne (scores, date, heure, arbitres, journée, vainqueur, forfait).
    * **Synchronisation** — crée dans la base les matchs qui existent en
      ligne mais pas localement (feuille de match manquante, matchs à
      venir, matchs non encore joués).

    Le code entité FFVB est résolu depuis ``CompetitionDB.entite``.
    Le code de poule FFVB est dérivé de ``CompetitionDB.code_competition``
    (les codes en base ``PMAA`` / ``PMAR`` pointent vers la même URL FFVB
    ``poule=PMA``).
    """

    def __init__(
        self,
        session: Session,
        scraper: Optional[FFVBScoreScraper] = None,
    ):
        self.session = session
        self.scraper = scraper or FFVBScoreScraper()
        self.import_service = MatchImportService(session)

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _ffvb_poule_code(poule: PouleDB) -> Optional[str]:
        """Code de poule FFVB pour l'URL de calendrier.

        Utilise ``competition.code_competition`` (ex. ``PMA``), qui est le
        paramètre ``poule=`` dans l'URL du calendrier FFVB.

        Fallback : retire le dernier caractère du code en base (``PMAA`` →
        ``PMA``).
        """
        comp = poule.competition
        if comp and comp.code_competition:
            return comp.code_competition
        # Fallback heuristique
        if len(poule.code) >= 4:
            return poule.code[:-1]
        return poule.code

    def _get_entity_code_for_poule(self, poule: PouleDB) -> Optional[str]:
        """Détermine le code entité FFVB (``LIRA``, ``ABCCS`` …).

        Remonte ``Poule → Competition → EntiteFFVB``.
        Fallback : extrait le code depuis le chemin ``source_pdf``.
        """
        comp = poule.competition
        if comp and comp.entite:
            return comp.entite.code

        match = self.session.scalar(
            select(MatchDB)
            .where(MatchDB.poule_id == poule.id)
            .where(MatchDB.source_pdf.isnot(None))
            .limit(1)
        )
        if match and match.source_pdf:
            m = re.search(r"data/pdfs/\d{4}-\d{4}/([^/]+)/", match.source_pdf)
            if m:
                return m.group(1)
        return None

    def _find_equipe(
        self,
        nom: str,
        competition_id: Optional[int],
        saison_id: Optional[int],
    ) -> Optional[EquipeDB]:
        """Cherche une équipe par nom exact d'abord dans la compétition,
        puis dans la saison entière."""
        if not nom:
            return None

        nom_upper = nom.strip().upper()

        if competition_id:
            eq = self.session.scalar(
                select(EquipeDB).where(
                    func.upper(EquipeDB.nom) == nom_upper,
                    EquipeDB.competition_id == competition_id,
                )
            )
            if eq:
                return eq

        if saison_id:
            eq = self.session.scalar(
                select(EquipeDB).where(
                    func.upper(EquipeDB.nom) == nom_upper,
                    EquipeDB.saison_id == saison_id,
                )
            )
            if eq:
                return eq

        return None

    def _parse_date(self, date_str: str):
        """Parse une date au format ``dd/mm/yy`` ou ``dd/mm/yyyy``."""
        for fmt in ("%d/%m/%y", "%d/%m/%Y"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None

    def _get_or_create_arbitre(
        self,
        nom: str,
        prenom: Optional[str] = None,
    ) -> ArbitreDB:
        """Cherche ou crée un arbitre par nom / prénom."""
        stmt = select(ArbitreDB).where(ArbitreDB.nom == nom)
        if prenom:
            stmt = stmt.where(ArbitreDB.prenom == prenom)
        existing = self.session.scalar(stmt)
        if existing:
            return existing

        arbitre = ArbitreDB(nom=nom, prenom=prenom)
        self.session.add(arbitre)
        self.session.flush()
        return arbitre

    # ── poule → DB poule mapping ────────────────────────────────────

    def _find_db_poule_for_code(
        self,
        code_match: str,
        poules_by_prefix: dict[str, PouleDB],
    ) -> Optional[PouleDB]:
        """Trouve la PouleDB correspondant à un code de match.

        Les codes de match commencent par le code de poule en base :
        ``PMAA001`` → poule ``PMAA``, ``PMAR003`` → poule ``PMAR``.
        """
        upper = code_match.upper()
        # Tester les préfixes du plus long au plus court
        for prefix in sorted(poules_by_prefix, key=len, reverse=True):
            if upper.startswith(prefix):
                return poules_by_prefix[prefix]
        return None

    # ── création de matchs ──────────────────────────────────────────

    def _create_match_from_online(
        self,
        oms: OnlineMatchScore,
        saison: SaisonDB,
        poule: PouleDB,
    ) -> MatchDB:
        """Crée un nouveau MatchDB depuis un OnlineMatchScore."""
        comp = poule.competition

        # Résoudre les équipes
        equipe_a = self._find_equipe(
            oms.equipe_a, comp.id if comp else None, saison.id,
        )
        equipe_b = self._find_equipe(
            oms.equipe_b, comp.id if comp else None, saison.id,
        )

        match_db = MatchDB(
            code_match=oms.code_match,
            saison_id=saison.id,
            competition_id=comp.id if comp else None,
            poule_id=poule.id,
            equipe_a_id=equipe_a.id if equipe_a else None,
            equipe_b_id=equipe_b.id if equipe_b else None,
            date_match=self._parse_date(oms.date) if oms.date else None,
            heure_match=oms.heure,
            journee=oms.journee,
            vainqueur=oms.vainqueur,
            match_joue=oms.match_joue,
            has_details=False,
            score_source=None,
        )

        # Remplir les scores si disponibles
        if oms.has_result and (oms.is_complete or oms.is_forfait):
            match_db.score_sets = oms.score_sets or ""
            match_db.sets_equipe_a = oms.sets_a
            match_db.sets_equipe_b = oms.sets_b
            match_db.match_joue = True
            match_db.has_details = bool(oms.set_scores)
            match_db.score_source = "online"

        self.session.add(match_db)
        self.session.flush()

        # Ajouter les sets détaillés
        if oms.set_scores:
            for i, (sa, sb) in enumerate(oms.set_scores, 1):
                self.session.add(SetDB(
                    match_id=match_db.id,
                    numero=i,
                    score_a=sa,
                    score_b=sb,
                ))
            self.session.flush()

        return match_db

    # ── mise à jour d'un match existant ─────────────────────────────

    def _update_match_from_online(
        self,
        match_db: MatchDB,
        oms: OnlineMatchScore,
        saison: SaisonDB,
    ) -> str:
        """Met à jour un match existant depuis les données en ligne.

        Returns:
            ``"full"`` si les scores ont été mis à jour,
            ``"metadata"`` si seulement les métadonnées,
            ``"skipped"`` si rien n'a changé.
        """
        result = "skipped"

        # ─── Métadonnées manquantes ──────────────────────────────
        metadata_updated = False

        if oms.date and not match_db.date_match:
            parsed = self._parse_date(oms.date)
            if parsed:
                match_db.date_match = parsed
                metadata_updated = True

        if oms.heure and not match_db.heure_match:
            match_db.heure_match = oms.heure
            metadata_updated = True

        if oms.journee and not match_db.journee:
            match_db.journee = oms.journee
            metadata_updated = True

        if oms.vainqueur and not match_db.vainqueur:
            match_db.vainqueur = oms.vainqueur
            metadata_updated = True

        # Synchroniser le flag match_joue
        if oms.match_joue and not match_db.match_joue:
            match_db.match_joue = True
            metadata_updated = True

        if metadata_updated:
            result = "metadata"

        # ─── Scores ──────────────────────────────────────────────
        if match_db.score_source == "pdf" and match_db.has_details:
            return result

        if oms.is_complete or oms.is_forfait:
            updated = self.import_service.update_match_scores(
                code_match=match_db.code_match,
                saison_id=saison.id,
                score_sets=oms.score_sets or "",
                sets_a=oms.sets_a,
                sets_b=oms.sets_b,
                set_scores=oms.set_scores or [],
                source="online",
                vainqueur=oms.vainqueur,
            )
            if updated:
                result = "full"

        return result

    # ── ajout d'arbitres ────────────────────────────────────────────

    def _add_arbitres_from_online(
        self,
        match_db: MatchDB,
        oms: OnlineMatchScore,
    ) -> int:
        """Ajoute les arbitres depuis les données en ligne (sans doublons).

        Returns:
            Nombre d'arbitres ajoutés.
        """
        count = 0

        existing = list(match_db.arbitrages) if hasattr(match_db, "arbitrages") else []
        existing_names = set()
        for am in existing:
            if am.arbitre:
                existing_names.add(f"{am.arbitre.nom}_{am.arbitre.prenom or ''}")

        for nom_complet, role in [
            (oms.arbitre_1, "1er"),
            (oms.arbitre_2, "2ème"),
        ]:
            if not nom_complet:
                continue

            parts = nom_complet.strip().split(maxsplit=1)
            nom = parts[0]
            prenom = parts[1] if len(parts) > 1 else None

            if f"{nom}_{prenom or ''}" in existing_names:
                continue

            arbitre_db = self._get_or_create_arbitre(nom, prenom)
            self.session.add(ArbitreMatchDB(
                arbitre_id=arbitre_db.id,
                match_id=match_db.id,
                role=role,
            ))
            count += 1

        if count:
            self.session.flush()
        return count

    # ── méthode principale ──────────────────────────────────────────

    def complete_scores_for_saison(
        self,
        saison_code: str,
        *,
        entity_codes: Optional[list[str]] = None,
        dry_run: bool = False,
        progress_callback=None,
    ) -> dict:
        """Synchronise et complète les matchs d'une saison.

        Pour chaque poule de la saison :

        1. Récupère les matchs en ligne depuis le calendrier FFVB.
        2. **Crée** les matchs absents de la base (feuille de match
           manquante, matchs à venir).
        3. **Met à jour** les matchs existants (scores, métadonnées,
           arbitres).

        Args:
            saison_code: Code de la saison (ex. ``"2025-2026"``).
            entity_codes: Restreindre aux entités spécifiées (optionnel).
            dry_run: Si ``True``, ne fait pas de modifications en base.
            progress_callback: Callable(ffvb_code, n_online, n_created,
                n_updated) appelé après chaque poule.

        Returns:
            Dictionnaire de statistiques.
        """
        stats = {
            "saison": saison_code,
            "poules_processed": 0,
            "poules_skipped": 0,
            "total_online": 0,
            "matches_created": 0,
            "matches_updated": 0,
            "metadata_updated": 0,
            "already_complete": 0,
            "skipped_exempt": 0,
            "forfeits_updated": 0,
            "arbitres_added": 0,
            "upcoming_created": 0,
            "errors": [],
        }

        # ── 1. Trouver la saison ─────────────────────────────────
        saison = self.session.scalar(
            select(SaisonDB).where(SaisonDB.code == saison_code)
        )
        if not saison:
            stats["errors"].append(f"Saison {saison_code} non trouvée en base")
            logger.error("Saison %s non trouvée", saison_code)
            return stats

        saison_ffvb = saison_code.replace("-", "/")

        # ── 2. Collecter les poules de cette saison ───────────────
        all_poules: list[PouleDB] = list(self.session.scalars(
            select(PouleDB)
            .join(CompetitionDB)
            .where(CompetitionDB.saison_id == saison.id)
        ))

        if not all_poules:
            stats["errors"].append("Aucune poule trouvée pour cette saison")
            return stats

        # Grouper par (entity_code, ffvb_poule_code)
        # Plusieurs poules DB (PMAA + PMAR) partagent le même code FFVB (PMA)
        groups: dict[tuple[str, str], list[PouleDB]] = defaultdict(list)

        for poule in all_poules:
            entity_code = self._get_entity_code_for_poule(poule)
            ffvb_code = self._ffvb_poule_code(poule)
            if not entity_code or not ffvb_code:
                logger.warning(
                    "Impossible de résoudre entité/poule pour %s", poule.code,
                )
                stats["poules_skipped"] += 1
                continue

            if entity_codes and entity_code not in entity_codes:
                stats["poules_skipped"] += 1
                continue

            groups[(entity_code, ffvb_code)].append(poule)

        # ── 3. Pour chaque groupe, scraper et synchroniser ────────
        for (entity_code, ffvb_code), poules in groups.items():
            try:
                online_scores = self.scraper.get_scores_for_poule(
                    entity_code, ffvb_code, saison_ffvb,
                )
            except Exception as e:
                msg = f"Erreur scraping {entity_code}/{ffvb_code}: {e}"
                stats["errors"].append(msg)
                logger.warning(msg)
                continue

            stats["total_online"] += len(online_scores)
            stats["poules_processed"] += 1

            # Index DB existant : code_match → MatchDB
            # (chercher tous les matchs de ces poules, pas seulement
            # ceux sans détails)
            poule_ids = [p.id for p in poules]
            existing_matches: list[MatchDB] = list(self.session.scalars(
                select(MatchDB).where(
                    MatchDB.saison_id == saison.id,
                    MatchDB.poule_id.in_(poule_ids),
                )
            ))
            db_index: dict[str, MatchDB] = {
                m.code_match: m for m in existing_matches
            }

            # Mapping code poule DB → PouleDB (pour affecter les créations)
            poules_by_prefix: dict[str, PouleDB] = {
                p.code.upper(): p for p in poules
            }

            # Compteurs locaux pour le callback
            n_created = 0
            n_updated = 0

            for oms in online_scores:
                match_db = db_index.get(oms.code_match)

                if match_db is None:
                    # ── Match absent → créer ──────────────────────
                    if oms.is_exempt:
                        stats["skipped_exempt"] += 1
                        continue

                    target_poule = self._find_db_poule_for_code(
                        oms.code_match, poules_by_prefix,
                    )
                    if not target_poule:
                        # Fallback : première poule du groupe
                        target_poule = poules[0]

                    if dry_run:
                        status = "à venir" if not oms.match_joue else "joué"
                        logger.info(
                            "[DRY RUN] Créerait %s : %s vs %s (%s) %s",
                            oms.code_match, oms.equipe_a, oms.equipe_b,
                            status, oms.date or "",
                        )
                    else:
                        try:
                            new_match = self._create_match_from_online(
                                oms, saison, target_poule,
                            )
                            # Ajouter les arbitres
                            if oms.arbitre_1 or oms.arbitre_2:
                                stats["arbitres_added"] += (
                                    self._add_arbitres_from_online(
                                        new_match, oms,
                                    )
                                )
                        except Exception as e:
                            stats["errors"].append(
                                f"Erreur création {oms.code_match}: {e}"
                            )
                            self.session.rollback()
                            self.import_service.clear_caches()
                            continue

                    stats["matches_created"] += 1
                    n_created += 1
                    if not oms.match_joue:
                        stats["upcoming_created"] += 1

                else:
                    # ── Match existant → mettre à jour ─────────────
                    if oms.is_exempt:
                        stats["skipped_exempt"] += 1
                        continue

                    if dry_run:
                        if not oms.has_result:
                            continue
                        logger.info(
                            "[DRY RUN] Maj %s: %s (%s) forfait=%s "
                            "date=%s arbitres=%s",
                            match_db.code_match,
                            oms.score_sets,
                            oms.set_scores,
                            oms.is_forfait,
                            oms.date,
                            oms.arbitres,
                        )
                        stats["matches_updated"] += 1
                        n_updated += 1
                        continue

                    try:
                        result = self._update_match_from_online(
                            match_db, oms, saison,
                        )
                        if result == "full":
                            stats["matches_updated"] += 1
                            n_updated += 1
                            if oms.is_forfait:
                                stats["forfeits_updated"] += 1
                        elif result == "metadata":
                            stats["metadata_updated"] += 1
                            n_updated += 1
                        else:
                            stats["already_complete"] += 1

                        # Ajouter les arbitres
                        if oms.arbitre_1 or oms.arbitre_2:
                            stats["arbitres_added"] += (
                                self._add_arbitres_from_online(
                                    match_db, oms,
                                )
                            )

                    except Exception as e:
                        stats["errors"].append(
                            f"Erreur mise à jour {match_db.code_match}: {e}"
                        )
                        self.session.rollback()
                        self.import_service.clear_caches()

            if progress_callback:
                progress_callback(
                    ffvb_code, len(online_scores), n_created, n_updated,
                )

        # ── 4. Commit ─────────────────────────────────────────────
        if not dry_run:
            try:
                self.session.commit()
            except Exception as e:
                stats["errors"].append(f"Erreur commit final: {e}")
                self.session.rollback()

        logger.info(
            "Complétion saison %s : %d poules traitées, "
            "%d créés (%d à venir), %d mis à jour (%d metadata), "
            "%d arbitres, %d erreurs",
            saison_code,
            stats["poules_processed"],
            stats["matches_created"],
            stats["upcoming_created"],
            stats["matches_updated"],
            stats["metadata_updated"],
            stats["arbitres_added"],
            len(stats["errors"]),
        )
        return stats

    # ── résumé ──────────────────────────────────────────────────────

    def get_completion_summary(self, saison_code: str) -> dict:
        """Résumé de l'état de complétion des scores pour une saison."""
        saison = self.session.scalar(
            select(SaisonDB).where(SaisonDB.code == saison_code)
        )
        if not saison:
            return {"error": f"Saison {saison_code} non trouvée"}

        total = self.session.scalar(
            select(func.count(MatchDB.id))
            .where(MatchDB.saison_id == saison.id)
        ) or 0

        with_details = self.session.scalar(
            select(func.count(MatchDB.id))
            .where(MatchDB.saison_id == saison.id)
            .where(MatchDB.has_details == True)  # noqa: E712
        ) or 0

        match_joue = self.session.scalar(
            select(func.count(MatchDB.id))
            .where(MatchDB.saison_id == saison.id)
            .where(MatchDB.match_joue == True)  # noqa: E712
        ) or 0

        upcoming = self.session.scalar(
            select(func.count(MatchDB.id))
            .where(MatchDB.saison_id == saison.id)
            .where(MatchDB.match_joue == False)  # noqa: E712
        ) or 0

        by_source: dict[str, int] = {}
        for source in ("pdf", "online", "manual"):
            count = self.session.scalar(
                select(func.count(MatchDB.id))
                .where(MatchDB.saison_id == saison.id)
                .where(MatchDB.score_source == source)
            ) or 0
            if count > 0:
                by_source[source] = count

        no_source = self.session.scalar(
            select(func.count(MatchDB.id))
            .where(MatchDB.saison_id == saison.id)
            .where(MatchDB.score_source.is_(None))
        ) or 0
        if no_source > 0:
            by_source["none"] = no_source

        return {
            "saison": saison_code,
            "total_matches": total,
            "match_joue": match_joue,
            "upcoming": upcoming,
            "with_details": with_details,
            "without_details": total - with_details,
            "by_source": by_source,
            "completion_pct": (
                round(with_details / total * 100, 1) if total else 0.0
            ),
        }
