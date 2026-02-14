"""
Service de complétion des scores de matchs depuis des sources en ligne.

Workflow :
  1. Interroge la base de données pour trouver les matchs sans détails de score.
  2. Récupère les scores depuis les calendriers FFVB en ligne.
  3. Met à jour les matchs existants avec les données récupérées.

Usage::

    from sqlalchemy.orm import Session
    from pyvolley.database.score_completion import ScoreCompletionService

    service = ScoreCompletionService(session)
    stats = service.complete_scores_for_saison("2022-2023")
    print(stats)
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select, func

from pyvolley.database.models import (
    MatchDB, SaisonDB, PouleDB, CompetitionDB, EntiteFFVBDB,
)
from pyvolley.database.import_service import MatchImportService
from pyvolley.scrapers.score_scraper import FFVBScoreScraper, OnlineMatchScore

logger = logging.getLogger(__name__)


class ScoreCompletionService:
    """
    Complète les scores manquants dans la base de données via le scraping
    en ligne des résultats FFVB.
    """

    def __init__(
        self,
        session: Session,
        scraper: Optional[FFVBScoreScraper] = None,
    ):
        self.session = session
        self.scraper = scraper or FFVBScoreScraper()
        self.import_service = MatchImportService(session)

    def complete_scores_for_saison(
        self,
        saison_code: str,
        *,
        entity_codes: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Complète les scores manquants pour tous les matchs d'une saison.

        Args:
            saison_code: Code de la saison (ex: "2022-2023")
            entity_codes: Restreindre aux entités spécifiées (optionnel)
            dry_run: Si True, ne fait pas de modifications en base

        Returns:
            Statistiques : total_checked, updated, skipped, errors
        """
        stats = {
            "saison": saison_code,
            "total_without_details": 0,
            "scores_found_online": 0,
            "updated": 0,
            "skipped_already_detailed": 0,
            "skipped_no_online_data": 0,
            "errors": [],
        }

        # 1. Trouver la saison
        saison = self.session.scalar(
            select(SaisonDB).where(SaisonDB.code == saison_code)
        )
        if not saison:
            stats["errors"].append(f"Saison {saison_code} non trouvée en base")
            logger.error("Saison %s non trouvée", saison_code)
            return stats

        # 2. Trouver les matchs sans détails de score
        matches_without = self.import_service.get_matches_without_scores(saison.id)
        stats["total_without_details"] = len(matches_without)

        if not matches_without:
            logger.info("Aucun match sans détails pour la saison %s", saison_code)
            return stats

        # 3. Grouper par poule pour optimiser les requêtes
        from collections import defaultdict
        poule_matches: dict[int, list[MatchDB]] = defaultdict(list)
        orphan_matches: list[MatchDB] = []

        for m in matches_without:
            if m.poule_id:
                poule_matches[m.poule_id].append(m)
            else:
                orphan_matches.append(m)

        # 4. Pour chaque poule, récupérer les scores en ligne
        saison_ffvb = saison_code.replace("-", "/")

        for poule_id, matches in poule_matches.items():
            poule = self.session.get(PouleDB, poule_id)
            if not poule:
                continue

            # Trouver le code entité
            entity_code = self._get_entity_code_for_poule(poule)
            if not entity_code:
                logger.warning(
                    "Impossible de déterminer l'entité pour la poule %s",
                    poule.code,
                )
                continue

            if entity_codes and entity_code not in entity_codes:
                continue

            # Récupérer les scores en ligne
            try:
                online_scores = self.scraper.get_scores_for_poule(
                    entity_code, poule.code, saison_ffvb,
                )
            except Exception as e:
                stats["errors"].append(
                    f"Erreur scraping {entity_code}/{poule.code}: {e}"
                )
                continue

            # Créer un index par code match
            online_index = {s.code_match: s for s in online_scores}
            stats["scores_found_online"] += len(online_scores)

            # 5. Mettre à jour les matchs
            for match_db in matches:
                oms = online_index.get(match_db.code_match)
                if not oms or not oms.is_complete:
                    stats["skipped_no_online_data"] += 1
                    continue

                if dry_run:
                    stats["updated"] += 1
                    logger.info(
                        "[DRY RUN] Mise à jour %s: %s (%s)",
                        match_db.code_match, oms.score_sets, oms.set_scores,
                    )
                    continue

                try:
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
                        stats["updated"] += 1
                    else:
                        stats["skipped_already_detailed"] += 1
                except Exception as e:
                    stats["errors"].append(
                        f"Erreur mise à jour {match_db.code_match}: {e}"
                    )
                    self.session.rollback()
                    self.import_service.clear_caches()

        if not dry_run:
            try:
                self.session.commit()
            except Exception as e:
                stats["errors"].append(f"Erreur commit final: {e}")
                self.session.rollback()

        logger.info(
            "Complétion saison %s terminée : %d mis à jour, %d sans données, "
            "%d erreurs",
            saison_code,
            stats["updated"],
            stats["skipped_no_online_data"],
            len(stats["errors"]),
        )
        return stats

    def _get_entity_code_for_poule(self, poule: PouleDB) -> Optional[str]:
        """Détermine le code entité FFVB à partir d'une poule.

        Remonte la hiérarchie : Poule → Competition → EntiteFFVB.
        Si pas d'entité explicite, tente d'extraire le code depuis le
        chemin du PDF source des matchs de cette poule.
        """
        comp = poule.competition
        if comp and comp.entite:
            return comp.entite.code

        # Fallback : regarder le source_pdf des matchs de la poule
        match = self.session.scalar(
            select(MatchDB)
            .where(MatchDB.poule_id == poule.id)
            .where(MatchDB.source_pdf.isnot(None))
            .limit(1)
        )
        if match and match.source_pdf:
            # Extraire le code entité depuis le chemin
            # Pattern: data/pdfs/2022-2023/ENTITY_CODE/...
            import re
            m = re.search(r'data/pdfs/\d{4}-\d{4}/([^/]+)/', match.source_pdf)
            if m:
                return m.group(1)

        return None

    def get_completion_summary(self, saison_code: str) -> dict:
        """
        Résumé de l'état de complétion des scores pour une saison.

        Returns:
            Dictionnaire avec les statistiques de complétion :
            total_matches, with_details, without_details, by_source, etc.
        """
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

        # Par source
        by_source = {}
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
            "with_details": with_details,
            "without_details": total - with_details,
            "by_source": by_source,
            "completion_pct": round(with_details / total * 100, 1) if total else 0.0,
        }
