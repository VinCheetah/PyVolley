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

import logging
import unicodedata
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo, ArbitreInfo
from pyvolley.scrapers.ffvb.adressier_scraper import AdressierClubInfo, SalleInfo
from pyvolley.database.models import (
    SaisonDB, EntiteFFVBDB, CompetitionDB, PouleDB,
    ClubDB, ClubAliasDB, EquipeDB, MatchDB,
    ArbitreDB, ArbitreMatchDB, ImportLogDB,
    SalleClubDB,
)

logger = logging.getLogger(__name__)


def normalize_club_name(name: str) -> str:
    """Normalise un nom de club pour le matching."""
    n = name.upper().strip()
    n = ''.join(
        c for c in unicodedata.normalize('NFD', n)
        if unicodedata.category(c) != 'Mn'
    )
    n = re.sub(r'[.\-/\'\",;:()]+', ' ', n)
    n = re.sub(r'\s+\d$', '', n.strip())
    n = re.sub(r'\bSAINTE?\b', 'ST', n)
    n = re.sub(r'\bSTE\b', 'ST', n)
    n = re.sub(r'\s+', ' ', n)
    return n.strip()


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
        self._equipe_cache: dict[tuple, EquipeDB] = {}
        self._arbitre_cache: dict[str, ArbitreDB] = {}  # licence → ArbitreDB

    def clear_caches(self) -> None:
        """Vide tous les caches internes."""
        for cache in (
            self._saison_cache, self._entite_cache, self._competition_cache,
            self._poule_cache, self._club_cache, self._club_name_cache,
            self._equipe_cache, self._arbitre_cache,
        ):
            cache.clear()

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
        entite = self._get_or_create_entite(entite_code)

        for match_info in matches:
            try:
                result = self._import_single_match(
                    match_info, saison, entite
                )
                stats[result] += 1
            except Exception as e:
                logger.error(
                    "Erreur import match %s: %s",
                    match_info.code_match, e,
                )
                stats["errors"] += 1

        # Finaliser l'audit
        log_entry.finished_at = datetime.now()
        log_entry.imported = stats["imported"]
        log_entry.updated = stats["updated"]
        log_entry.duplicates = stats["duplicates"]
        log_entry.errors = stats["errors"]
        log_entry.status = "success" if stats["errors"] == 0 else "partial"

        logger.info(
            "Import %s: %d importés, %d mis à jour, %d doublons, %d erreurs",
            entite_code,
            stats["imported"], stats["updated"],
            stats["duplicates"], stats["errors"],
        )

        return stats

    # =================================================================
    # Import d'un match individuel
    # =================================================================

    def _import_single_match(
        self,
        match_info: ExportMatchInfo,
        saison: SaisonDB,
        entite: EntiteFFVBDB,
    ) -> str:
        """Importe un seul match. Retourne le type de résultat."""

        # Vérifier si le match existe déjà
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
        poule = self._get_or_create_poule(
            match_info.poule_code, competition
        )

        # Résoudre les clubs et équipes
        equipe_a = self._resolve_equipe(
            match_info.equipe_a_nom,
            match_info.club_a_code_ffvb,
            saison, competition,
        )
        equipe_b = self._resolve_equipe(
            match_info.equipe_b_nom,
            match_info.club_b_code_ffvb,
            saison, competition,
        )

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
            score_sets=match_info.score_sets,
            sets_equipe_a=match_info.sets_equipe_a,
            sets_equipe_b=match_info.sets_equipe_b,
            match_joue=match_info.match_joue,
            forfait=match_info.forfait,
            score_source="export" if match_info.match_joue else None,
            parsing_status="discovered",
            source_url=match_info.feuille_match_url,
        )

        self.session.add(match_db)
        self.session.flush()

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

        # Ne pas écraser les données PDF par des données export
        if existing.parsing_status == "parsed":
            return "duplicates"

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

        # Mettre à jour le score si le match est maintenant joué
        if match_info.match_joue and not existing.match_joue:
            existing.match_joue = True
            existing.vainqueur = match_info.vainqueur
            existing.score_sets = match_info.score_sets
            existing.sets_equipe_a = match_info.sets_equipe_a
            existing.sets_equipe_b = match_info.sets_equipe_b
            existing.forfait = match_info.forfait
            existing.score_source = "export"
            updated = True

        if updated:
            existing.updated_at = datetime.now()
            return "updated"
        return "duplicates"

    # =================================================================
    # Résolution des entités
    # =================================================================

    def _get_or_create_saison(self, code: str) -> SaisonDB:
        """Récupère ou crée une saison."""
        if code in self._saison_cache:
            return self._saison_cache[code]

        saison = self.session.execute(
            select(SaisonDB).where(SaisonDB.code == code)
        ).scalar_one_or_none()

        if not saison:
            saison = SaisonDB(code=code)
            self.session.add(saison)
            self.session.flush()

        self._saison_cache[code] = saison
        return saison

    def _get_or_create_entite(self, code: str) -> EntiteFFVBDB:
        """Récupère ou crée une entité FFVB."""
        if code in self._entite_cache:
            return self._entite_cache[code]

        entite = self.session.execute(
            select(EntiteFFVBDB).where(EntiteFFVBDB.code == code)
        ).scalar_one_or_none()

        if not entite:
            entite = EntiteFFVBDB(
                code=code,
                nom=code,  # sera enrichi plus tard
            )
            self.session.add(entite)
            self.session.flush()

        self._entite_cache[code] = entite
        return entite

    def _get_or_create_competition(
        self,
        match_info: ExportMatchInfo,
        saison: SaisonDB,
        entite: EntiteFFVBDB,
    ) -> CompetitionDB:
        """Résout ou crée une compétition depuis le code du match."""
        # Utiliser le code poule comme nom de compétition par défaut
        cache_key = (match_info.poule_code, saison.id)
        if cache_key in self._competition_cache:
            return self._competition_cache[cache_key]

        competition = self.session.execute(
            select(CompetitionDB).where(
                CompetitionDB.code_competition == match_info.poule_code,
                CompetitionDB.saison_id == saison.id,
            )
        ).scalar_one_or_none()

        if not competition:
            competition = CompetitionDB(
                nom=f"Compétition {match_info.poule_code}",
                code_competition=match_info.poule_code,
                saison_id=saison.id,
                entite_id=entite.id,
            )
            self.session.add(competition)
            self.session.flush()

        self._competition_cache[cache_key] = competition
        return competition

    def _get_or_create_poule(
        self,
        poule_code: str,
        competition: CompetitionDB,
    ) -> PouleDB:
        """Résout ou crée une poule."""
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
            poule = PouleDB(
                code=poule_code,
                nom=f"Poule {poule_code}",
                competition_id=competition.id,
            )
            self.session.add(poule)
            self.session.flush()

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

            # Chercher par nom normalisé
            clubs = self.session.execute(select(ClubDB)).scalars().all()
            for c in clubs:
                if normalize_club_name(c.nom) == normalized:
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
            return club

        return None

    def _resolve_equipe(
        self,
        nom: Optional[str],
        code_ffvb: Optional[str],
        saison: SaisonDB,
        competition: Optional[CompetitionDB],
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
            equipe = EquipeDB(
                nom=nom,
                club_id=club.id if club else None,
                saison_id=saison.id,
                competition_id=comp_id,
            )
            self.session.add(equipe)
            self.session.flush()

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
    ) -> dict:
        """Enrichit les clubs en base avec les données de l'adressier FFVB.

        Met à jour les champs du club (adresse, correspondant, couleurs,
        dirigeants, salles, URLs) à partir des données de l'adressier.

        Args:
            clubs_info: Liste d'``AdressierClubInfo``.
            entite_code: Code de l'entité (pour construire les URLs).
            saison: Saison au format ``YYYY/YYYY``.
            base_url: URL de base FFVB.

        Returns:
            Dict ``{"enriched": N, "created": N, "skipped": N}``.
        """
        from pyvolley.scrapers.ffvb.adressier_scraper import (
            build_club_planning_url,
            build_club_classement_url,
        )

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
                stats["enriched"] += 1

            # Mettre à jour les champs
            club.nom = club_info.nom
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
                # Extraire la ville pour le champ principal
                if not club.ville:
                    club.ville = club_info.correspondant_ville
            if club_info.correspondant_telephone:
                club.correspondant_telephone = club_info.correspondant_telephone
            if club_info.correspondant_portable:
                club.correspondant_portable = club_info.correspondant_portable
            if club_info.correspondant_email:
                club.correspondant_email = club_info.correspondant_email

            # URLs
            club.url_planning = build_club_planning_url(
                base_url, entite_code, club_info.code_ffvb,
            )
            club.url_classement = build_club_classement_url(
                base_url, entite_code, saison, club_info.code_ffvb,
            )

            # Salles — supprimer les existantes et recréer
            self.session.execute(
                select(SalleClubDB).where(SalleClubDB.club_id == club.id)
            )
            # Supprimer les salles existantes
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
            "Enrichissement clubs %s: %d enrichis, %d créés, %d ignorés",
            entite_code,
            stats["enriched"], stats["created"], stats["skipped"],
        )

        return stats
