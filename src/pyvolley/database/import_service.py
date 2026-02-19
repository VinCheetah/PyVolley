"""
Service d'import des données de matchs dans la base de données.

Gère l'import des données extraites par les parsers vers la base de données
SQLAlchemy, avec résolution correcte des entités (clubs, équipes, joueurs,
compétitions, poules) et création des liens entre elles.
"""

import re
import logging
from typing import Optional, List, Any, Union
from datetime import datetime, date as datetime_date, time as datetime_time

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..core.models import Match, Joueur, Equipe, Set, Arbitre, Sanction, Officiel
from .models import (
    ClubDB, ClubAliasDB, EquipeDB, JoueurDB, MatchDB, SetDB,
    FormationDB, ChangementDB, TimeoutDB,
    ArbitreDB, ArbitreMatchDB, SaisonDB, CompetitionDB, PouleDB,
    EntiteFFVBDB, ParticipationMatchDB, SanctionDB, OfficielMatchDB,
)

logger = logging.getLogger(__name__)


def normalize_club_name(name: str) -> str:
    """Normalise un nom de club pour le matching (minuscule, sans ponctuation superflue)."""
    n = name.upper().strip()
    n = re.sub(r'[.\-/\']', ' ', n)
    n = re.sub(r'\s+', ' ', n)
    return n.strip()


class MatchImportService:
    """
    Service pour importer les données de matchs dans la base de données.

    Gère les relations et évite les doublons en utilisant les identifiants
    naturels (licence joueur, code match+saison, nom club, etc.).
    """

    def __init__(self, session: Session):
        self.session = session
        # Cache local pour éviter les requêtes répétitives dans un batch
        self._saison_cache: dict[str, SaisonDB] = {}
        self._club_cache: dict[str, ClubDB] = {}
        self._equipe_cache: dict[tuple[str, int], EquipeDB] = {}
        self._joueur_cache: dict[str, JoueurDB] = {}
        self._arbitre_cache: dict[str, ArbitreDB] = {}
        self._competition_cache: dict[tuple[str, int, Optional[str]], CompetitionDB] = {}
        self._poule_cache: dict[tuple[str, int], PouleDB] = {}
        # Track participations ajoutées (non-flushées) pour éviter les doublons
        # Nécessaire car autoflush=False empêche les queries de voir les adds en attente
        self._participation_seen: set[tuple[int, int]] = set()

    def clear_caches(self) -> None:
        """Vide tous les caches internes.

        À appeler impérativement après un ``session.rollback()`` : les objets
        cachés sont alors détachés et leurs identifiants potentiellement invalides.
        """
        self._saison_cache.clear()
        self._club_cache.clear()
        self._equipe_cache.clear()
        self._joueur_cache.clear()
        self._arbitre_cache.clear()
        self._competition_cache.clear()
        self._poule_cache.clear()
        self._participation_seen.clear()

    # =================================================================
    # Import principal
    # =================================================================

    def import_match(self, match_data: Match) -> Optional[MatchDB]:
        """
        Importe un match complet dans la base de données.

        Crée ou réutilise les entités liées (saison, compétition, poule,
        clubs, équipes, joueurs, arbitres).
        """
        # 1. Saison
        saison = self._get_or_create_saison(match_data)

        # 2. Vérifier si le match existe déjà
        saison_id = saison.id if saison else None
        existing = self._get_match_by_code(match_data.code_match, saison_id)
        if existing:
            logger.debug(f"Match {match_data.code_match} déjà présent, ignoré")
            return None

        # 3. Compétition & Poule
        competition = self._get_or_create_competition(match_data, saison)
        poule = self._get_or_create_poule(match_data, competition)

        # 4. Clubs & Équipes
        equipe_a_db = self._resolve_equipe(match_data.equipe_a, match_data, saison)
        equipe_b_db = self._resolve_equipe(match_data.equipe_b, match_data, saison)

        # 5. Créer le match
        heure_str = self._time_to_string(match_data.heure) if match_data.heure else None

        match_db = MatchDB(
            code_match=match_data.code_match,
            journee=match_data.journee,
            date_match=self._parse_date(match_data.date),
            heure_match=heure_str,
            lieu=match_data.lieu,
            salle=match_data.salle,
            saison_id=saison.id if saison else None,
            competition_id=competition.id if competition else None,
            poule_id=poule.id if poule else None,
            equipe_a_id=equipe_a_db.id if equipe_a_db else None,
            equipe_b_id=equipe_b_db.id if equipe_b_db else None,
            vainqueur=match_data.vainqueur_nom,
            score_sets=match_data.score_final,
            sets_equipe_a=match_data.sets_a,
            sets_equipe_b=match_data.sets_b,
            duree_totale=match_data.duree_totale,
            match_joue=getattr(match_data, 'match_joue', False),
            has_details=getattr(match_data, 'has_details', False),
            score_source=getattr(match_data, 'score_source', None),
            remarques=match_data.remarques,
            source_pdf=match_data.source_pdf,
            parsed_at=match_data.parsed_at,
        )
        self.session.add(match_db)
        self.session.flush()

        # 6. Sets (avec formations, changements, timeouts)
        self._import_sets(match_db, match_data.sets)

        # 7. Joueurs & participations
        if match_data.equipe_a and equipe_a_db:
            self._import_joueurs(match_db, match_data.equipe_a, equipe_a_db)
        if match_data.equipe_b and equipe_b_db:
            self._import_joueurs(match_db, match_data.equipe_b, equipe_b_db)
        # Flush les participations pour que les prochaines queries les voient
        self.session.flush()

        # 8. Arbitres
        self._import_arbitres(match_db, match_data.arbitres)

        # 9. Sanctions
        self._import_sanctions(match_db, match_data.sanctions)

        # 10. Officiels d'équipe
        if match_data.equipe_a:
            self._import_officiels(match_db, match_data.equipe_a.officiels, "A")
        if match_data.equipe_b:
            self._import_officiels(match_db, match_data.equipe_b.officiels, "B")

        return match_db

    def import_matches(self, matches: List[Match]) -> dict:
        """Importe plusieurs matchs avec commit par batch.

        La détection de doublons se fait en base de données (code_match +
        saison_id) : c'est l'unique source de vérité, indépendante de tout
        cache fichier.  Après un ``reset_db``, tous les matchs seront
        ré-importés même si le cache de parsing n'a pas été vidé.

        Returns:
            Statistiques d'import : total, imported, duplicates, errors.
        """
        stats = {"total": len(matches), "imported": 0, "duplicates": 0, "errors": []}

        for match_data in matches:
            try:
                result = self.import_match(match_data)
                if result:
                    stats["imported"] += 1
                else:
                    stats["duplicates"] += 1
            except Exception as e:
                stats["errors"].append({"code_match": match_data.code_match, "error": str(e)})
                logger.warning(f"Import error for {match_data.code_match}: {e}")
                self.session.rollback()
                self.clear_caches()

        self.session.commit()
        return stats

    # =================================================================
    # Saison
    # =================================================================

    def _get_or_create_saison(self, match_data: Match) -> Optional[SaisonDB]:
        """Crée ou récupère la saison."""
        code = None

        if match_data.saison:
            # Normaliser le format : "2024/2025" -> "2024-2025"
            code = match_data.saison.replace("/", "-")
        elif match_data.date:
            date_obj = match_data.date if isinstance(match_data.date, datetime_date) else self._parse_date(match_data.date)
            if date_obj:
                annee = date_obj.year if date_obj.month >= 8 else date_obj.year - 1
                code = f"{annee}-{annee + 1}"

        if not code:
            return None

        if code in self._saison_cache:
            return self._saison_cache[code]

        existing = self.session.scalar(select(SaisonDB).where(SaisonDB.code == code))
        if existing:
            self._saison_cache[code] = existing
            return existing

        parts = code.split("-")
        annee_debut = int(parts[0])
        annee_fin = int(parts[1])

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

    # =================================================================
    # Compétition & Poule
    # =================================================================

    def _get_or_create_competition(
        self, match_data: Match, saison: Optional[SaisonDB]
    ) -> Optional[CompetitionDB]:
        """Crée ou récupère la compétition.

        La compétition est identifiée par son nom + saison + genre.
        """
        if not match_data.competition:
            return None
        if not saison:
            return None

        genre = match_data.genre.value if match_data.genre else None
        cache_key = (match_data.competition, saison.id, genre)

        if cache_key in self._competition_cache:
            return self._competition_cache[cache_key]

        # Chercher une compétition existante
        stmt = (
            select(CompetitionDB)
            .where(
                CompetitionDB.nom == match_data.competition,
                CompetitionDB.saison_id == saison.id,
            )
        )
        if genre:
            stmt = stmt.where(CompetitionDB.genre == genre)

        existing = self.session.scalar(stmt)
        if existing:
            self._competition_cache[cache_key] = existing
            return existing

        categorie = match_data.categorie.value if match_data.categorie else None

        # Extraire un code lisible depuis le nom de compétition
        comp_code = self._extract_code_from_competition_name(match_data.competition)

        competition = CompetitionDB(
            nom=match_data.competition,
            code_competition=comp_code,
            genre=genre,
            categorie=categorie,
            saison_id=saison.id,
        )
        self.session.add(competition)
        self.session.flush()
        self._competition_cache[cache_key] = competition
        return competition

    def _get_or_create_poule(
        self, match_data: Match, competition: Optional[CompetitionDB]
    ) -> Optional[PouleDB]:
        """Crée ou récupère la poule."""
        poule_code = getattr(match_data, 'competition_code', None)
        if not poule_code or not competition:
            return None

        cache_key = (poule_code, competition.id)
        if cache_key in self._poule_cache:
            return self._poule_cache[cache_key]

        existing = self.session.scalar(
            select(PouleDB).where(
                PouleDB.code == poule_code,
                PouleDB.competition_id == competition.id,
            )
        )
        if existing:
            self._poule_cache[cache_key] = existing
            return existing

        poule = PouleDB(
            code=poule_code,
            nom=match_data.competition,  # Use full competition name as poule label
            competition_id=competition.id,
        )
        self.session.add(poule)
        self.session.flush()
        self._poule_cache[cache_key] = poule
        return poule

    @staticmethod
    def _extract_code_from_competition_name(nom: str) -> str:
        """Extrait un code court depuis le nom de la compétition.

        Ex: 'EMA - ELITE MASCULINE - POULE A' → 'EMA'
            'PMA - PRÉNATIONLAE MASCULINE A' → 'PMA'
        """
        if not nom:
            return "COMP"
        # Si le nom commence par un code (lettres/chiffres avant un ' - ')
        m = re.match(r'^([A-Z0-9]{2,6})\s*-', nom)
        if m:
            return m.group(1)
        # Sinon prendre les initiales
        words = re.findall(r'\b\w', nom.upper())
        return ''.join(words[:5]) or "COMP"

    # =================================================================
    # Club & Équipe
    # =================================================================

    def _resolve_equipe(
        self, equipe_data: Optional[Equipe], match_data: Match, saison: Optional[SaisonDB]
    ) -> Optional[EquipeDB]:
        """Résout / crée une équipe et son club associé."""
        if not equipe_data:
            return None

        nom_equipe = equipe_data.nom
        saison_id = saison.id if saison else None

        # Cache
        cache_key = (nom_equipe, saison_id or 0)
        if cache_key in self._equipe_cache:
            return self._equipe_cache[cache_key]

        # Chercher l'équipe existante
        stmt = select(EquipeDB).where(EquipeDB.nom == nom_equipe)
        if saison_id:
            stmt = stmt.where(EquipeDB.saison_id == saison_id)
        existing = self.session.scalar(stmt)
        if existing:
            self._equipe_cache[cache_key] = existing
            return existing

        # Résoudre le club
        club_nom = equipe_data.club_nom or nom_equipe
        club = self._get_or_create_club(club_nom)

        genre = match_data.genre.value if match_data.genre else None
        categorie = match_data.categorie.value if match_data.categorie else None

        equipe = EquipeDB(
            nom=nom_equipe,
            numero_equipe=equipe_data.numero_equipe,
            genre=genre,
            categorie=categorie,
            club_id=club.id if club else None,
            saison_id=saison_id,
        )
        self.session.add(equipe)
        self.session.flush()
        self._equipe_cache[cache_key] = equipe
        return equipe

    def _get_or_create_club(self, nom: str) -> ClubDB:
        """Crée ou récupère un club par nom (avec matching par alias)."""
        normalized = normalize_club_name(nom)

        if normalized in self._club_cache:
            return self._club_cache[normalized]

        # 1. Chercher par alias
        alias_match = self.session.scalar(
            select(ClubAliasDB).where(ClubAliasDB.alias == normalized)
        )
        if alias_match:
            club = alias_match.club
            self._club_cache[normalized] = club
            return club

        # 2. Chercher par nom exact
        existing = self.session.scalar(
            select(ClubDB).where(ClubDB.nom == nom)
        )
        if existing:
            # Créer un alias pour le nom normalisé
            if normalized != normalize_club_name(existing.nom):
                alias = ClubAliasDB(alias=normalized, club_id=existing.id)
                self.session.add(alias)
                self.session.flush()
            self._club_cache[normalized] = existing
            return existing

        # 3. Créer le club
        club = ClubDB(nom=nom)
        self.session.add(club)
        self.session.flush()

        # Créer l'alias normalisé
        alias = ClubAliasDB(alias=normalized, club_id=club.id)
        self.session.add(alias)
        self.session.flush()

        self._club_cache[normalized] = club
        return club

    # =================================================================
    # Sets
    # =================================================================

    def _import_sets(self, match_db: MatchDB, sets: List[Set]) -> None:
        """Importe les sets d'un match avec formations, changements, timeouts."""
        for set_data in sets:
            heure_debut_str = self._time_to_string(set_data.debut) if set_data.debut else None
            heure_fin_str = self._time_to_string(set_data.fin) if set_data.fin else None

            set_db = SetDB(
                match_id=match_db.id,
                numero=set_data.numero,
                score_a=set_data.score_a,
                score_b=set_data.score_b,
                heure_debut=heure_debut_str,
                heure_fin=heure_fin_str,
                duree_minutes=set_data.duree_minutes,
                service_initial=set_data.service_initial,
            )
            self.session.add(set_db)
            self.session.flush()

            # Formations
            for label, team_data in [
                ("A", set_data.equipe_a),
                ("B", set_data.equipe_b),
            ]:
                f = team_data.formation if team_data else None
                if f:
                    form_db = FormationDB(
                        set_id=set_db.id,
                        equipe=label,
                        position_1=f.position_1,
                        position_2=f.position_2,
                        position_3=f.position_3,
                        position_4=f.position_4,
                        position_5=f.position_5,
                        position_6=f.position_6,
                    )
                    self.session.add(form_db)

            # Changements & Timeouts from SetTeamData
            for label, team_data in [("A", set_data.equipe_a), ("B", set_data.equipe_b)]:
                if not team_data:
                    continue
                for chg in team_data.changements:
                    chg_db = ChangementDB(
                        set_id=set_db.id,
                        equipe=label,
                        joueur_entrant=chg.joueur_entrant,
                        joueur_sortant=chg.joueur_sortant,
                        position=chg.position,
                        score_a=chg.score_a,
                        score_b=chg.score_b,
                    )
                    self.session.add(chg_db)
                for to in team_data.timeouts:
                    to_db = TimeoutDB(
                        set_id=set_db.id,
                        equipe=label,
                        score_a=to.score_a,
                        score_b=to.score_b,
                    )
                    self.session.add(to_db)

    # =================================================================
    # Joueurs & Participations
    # =================================================================

    def _import_joueurs(
        self, match_db: MatchDB, equipe_data: Equipe, equipe_db: EquipeDB
    ) -> None:
        """Importe les joueurs d'une équipe et crée les participations.

        Gère les doublons via un set en mémoire (``_participation_seen``) car
        ``autoflush=False`` empêche les queries de voir les adds en attente.
        """
        all_joueurs = list(equipe_data.joueurs)
        # Les libéros doivent déjà être fusionnés dans joueurs par le parser v5
        # mais on vérifie au cas où (par licence OU par numéro+nom)
        for lib in equipe_data.liberos:
            dup = False
            for j in all_joueurs:
                if j.licence and lib.licence and j.licence == lib.licence:
                    dup = True
                    break
                if j.numero and lib.numero and j.numero == lib.numero and j.nom == lib.nom:
                    dup = True
                    break
            if not dup:
                all_joueurs.append(lib)

        # Dédupliquer la liste elle-même par licence (protège contre les
        # doublons provenant du parsing)
        seen_licences: set[str] = set()
        unique_joueurs: list = []
        for jd in all_joueurs:
            key = jd.licence or f"{jd.nom}_{jd.prenom}"
            if key in seen_licences:
                continue
            seen_licences.add(key)
            unique_joueurs.append(jd)

        for joueur_data in unique_joueurs:
            licence = joueur_data.licence
            if not licence or licence.strip() == "":
                licence = f"TEMP_{hash(f'{joueur_data.nom}_{joueur_data.prenom}') % 100000:06d}"

            joueur_db = self._get_or_create_joueur(licence, joueur_data.nom, joueur_data.prenom)

            # Vérifier via le set en mémoire (fiable même sans autoflush)
            part_key = (match_db.id, joueur_db.id)
            if part_key in self._participation_seen:
                logger.debug(
                    f"Participation doublon ignorée: joueur={joueur_db.id} "
                    f"match={match_db.id}"
                )
                continue

            # Double-check en DB (pour la robustesse, au cas où la session
            # aurait été flushée entre-temps)
            existing_part = self.session.scalar(
                select(ParticipationMatchDB).where(
                    ParticipationMatchDB.match_id == match_db.id,
                    ParticipationMatchDB.joueur_id == joueur_db.id,
                )
            )
            if existing_part:
                self._participation_seen.add(part_key)
                continue

            participation = ParticipationMatchDB(
                match_id=match_db.id,
                joueur_id=joueur_db.id,
                equipe_id=equipe_db.id,
                numero_maillot=joueur_data.numero,
                est_libero=joueur_data.est_libero,
                est_capitaine=joueur_data.est_capitaine,
            )
            self.session.add(participation)
            self._participation_seen.add(part_key)

    def _get_or_create_joueur(self, licence: str, nom: str, prenom: str) -> JoueurDB:
        """Crée ou récupère un joueur par sa licence."""
        if licence in self._joueur_cache:
            return self._joueur_cache[licence]

        existing = self.session.scalar(
            select(JoueurDB).where(JoueurDB.licence == licence)
        )
        if existing:
            self._joueur_cache[licence] = existing
            return existing

        joueur = JoueurDB(licence=licence, nom=nom, prenom=prenom)
        self.session.add(joueur)
        self.session.flush()
        self._joueur_cache[licence] = joueur
        return joueur

    # =================================================================
    # Arbitres
    # =================================================================

    def _import_arbitres(self, match_db: MatchDB, arbitres: List[Arbitre]) -> None:
        """Importe les arbitres d'un match."""
        for arb_data in arbitres:
            arbitre_db = self._get_or_create_arbitre(arb_data)

            role = arb_data.role.value if arb_data.role else "Inconnu"
            arb_match = ArbitreMatchDB(
                arbitre_id=arbitre_db.id,
                match_id=match_db.id,
                role=role,
            )
            self.session.add(arb_match)

    def _get_or_create_arbitre(self, arb_data: Arbitre) -> ArbitreDB:
        """Crée ou récupère un arbitre."""
        # Clé de cache: licence ou nom+prénom
        cache_key = arb_data.licence or f"{arb_data.nom}_{arb_data.prenom or ''}"

        if cache_key in self._arbitre_cache:
            return self._arbitre_cache[cache_key]

        # Chercher par licence si disponible
        if arb_data.licence:
            existing = self.session.scalar(
                select(ArbitreDB).where(ArbitreDB.licence == arb_data.licence)
            )
            if existing:
                self._arbitre_cache[cache_key] = existing
                return existing

        # Chercher par nom
        stmt = select(ArbitreDB).where(ArbitreDB.nom == arb_data.nom)
        if arb_data.prenom:
            stmt = stmt.where(ArbitreDB.prenom == arb_data.prenom)
        existing = self.session.scalar(stmt)
        if existing:
            self._arbitre_cache[cache_key] = existing
            return existing

        arbitre = ArbitreDB(
            nom=arb_data.nom,
            prenom=arb_data.prenom,
            licence=arb_data.licence,
            ligue=arb_data.ligue,
        )
        self.session.add(arbitre)
        self.session.flush()
        self._arbitre_cache[cache_key] = arbitre
        return arbitre

    # =================================================================
    # Sanctions
    # =================================================================

    def _import_sanctions(self, match_db: MatchDB, sanctions: List[Sanction]) -> None:
        """Importe les sanctions d'un match."""
        for s in sanctions:
            type_sanction = s.type.value if s.type else "A"
            sanction_db = SanctionDB(
                match_id=match_db.id,
                type_sanction=type_sanction,
                set_numero=s.set_numero,
                equipe=s.equipe,
                joueur_numero=s.joueur_numero,
                score_a=s.score_a,
                score_b=s.score_b,
            )
            self.session.add(sanction_db)

    # =================================================================
    # Officiels d'équipe
    # =================================================================

    def _import_officiels(
        self, match_db: MatchDB, officiels: List[Officiel], equipe_label: str
    ) -> None:
        """Importe les officiels d'équipe (entraîneurs, managers)."""
        for off in officiels:
            off_db = OfficielMatchDB(
                match_id=match_db.id,
                equipe=equipe_label,
                role=off.role,
                nom=off.nom,
                prenom=off.prenom,
                licence=off.licence,
            )
            self.session.add(off_db)

    # =================================================================
    # Helpers
    # =================================================================

    def _get_match_by_code(self, code_match: str, saison_id: Optional[int]) -> Optional[MatchDB]:
        """Cherche un match existant par code + saison.

        Quand ``saison_id`` est fourni, la recherche utilise le couple
        (code_match, saison_id) — ce qui correspond à la contrainte
        d'unicité ``uq_match_code_saison``.

        Quand ``saison_id`` est ``None``, on cherche uniquement les matchs
        qui n'ont pas de saison rattachée pour éviter les faux positifs
        inter-saisons.
        """
        stmt = select(MatchDB).where(MatchDB.code_match == code_match)
        if saison_id is not None:
            stmt = stmt.where(MatchDB.saison_id == saison_id)
        else:
            stmt = stmt.where(MatchDB.saison_id.is_(None))
        return self.session.scalar(stmt)

    # =================================================================
    # Mise à jour des scores (complétion en ligne)
    # =================================================================

    def update_match_scores(
        self,
        code_match: str,
        saison_id: Optional[int],
        *,
        score_sets: str,
        sets_a: int,
        sets_b: int,
        set_scores: list[tuple[int, int]],
        source: str = "online",
        duree_totale: Optional[str] = None,
        vainqueur: Optional[str] = None,
    ) -> Optional[MatchDB]:
        """Met à jour les scores d'un match existant depuis une source externe.

        N'écrase pas les scores déjà renseignés depuis le PDF, sauf si
        ``score_source`` est ``None`` (match sans détails).

        Args:
            code_match: Code du match (ex: "EMA001")
            saison_id: ID de la saison en base
            score_sets: Score en sets (ex: "3/2")
            sets_a / sets_b: Nombre de sets gagnés par chaque équipe
            set_scores: Liste de tuples (score_a, score_b) pour chaque set
            source: Origine des données ("online", "manual")
            duree_totale: Durée totale du match (optionnel)
            vainqueur: Nom du vainqueur (optionnel)

        Returns:
            Le MatchDB mis à jour, ou None si le match n'existe pas ou
            a déjà des détails.
        """
        match_db = self._get_match_by_code(code_match, saison_id)
        if not match_db:
            logger.debug("update_match_scores: match %s non trouvé", code_match)
            return None

        # Ne pas écraser les scores PDF existants
        if match_db.score_source == "pdf" and match_db.has_details:
            logger.debug(
                "update_match_scores: match %s a déjà des détails PDF, ignoré",
                code_match,
            )
            return None

        # Mettre à jour le résultat global
        match_db.score_sets = score_sets
        match_db.sets_equipe_a = sets_a
        match_db.sets_equipe_b = sets_b
        match_db.match_joue = True
        match_db.has_details = bool(set_scores)
        match_db.score_source = source

        if duree_totale:
            match_db.duree_totale = duree_totale
        if vainqueur:
            match_db.vainqueur = vainqueur

        # Supprimer les anciens sets (tous à 0)
        for old_set in list(match_db.sets):
            self.session.delete(old_set)
        self.session.flush()

        # Créer les nouveaux sets
        for i, (sa, sb) in enumerate(set_scores, 1):
            set_db = SetDB(
                match_id=match_db.id,
                numero=i,
                score_a=sa,
                score_b=sb,
            )
            self.session.add(set_db)

        match_db.updated_at = datetime.now()
        self.session.flush()

        logger.info(
            "Scores mis à jour pour %s (saison_id=%s) depuis %s: %s",
            code_match, saison_id, source, score_sets,
        )
        return match_db

    def get_matches_without_scores(
        self, saison_id: Optional[int] = None,
    ) -> list[MatchDB]:
        """Récupère les matchs qui n'ont pas de scores détaillés.

        Utile pour le système de complétion en ligne : on cherche les matchs
        dont ``has_details`` est False mais qui ont un vainqueur (donc jouables).
        """
        stmt = (
            select(MatchDB)
            .where(
                MatchDB.has_details == False,  # noqa: E712
            )
        )
        if saison_id is not None:
            stmt = stmt.where(MatchDB.saison_id == saison_id)
        return list(self.session.scalars(stmt).all())

    @staticmethod
    def _parse_date(date_val) -> Optional[datetime_date]:
        """Parse une date depuis différents formats."""
        if date_val is None:
            return None
        if isinstance(date_val, datetime):
            return date_val.date()
        if isinstance(date_val, datetime_date):
            return date_val
        if isinstance(date_val, str):
            for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(date_val, fmt).date()
                except ValueError:
                    continue
        return None

    @staticmethod
    def _time_to_string(time_val) -> Optional[str]:
        """Convertit un objet time en string HH:MM:SS."""
        if time_val is None:
            return None
        if isinstance(time_val, str):
            return time_val if len(time_val) >= 5 and ':' in time_val else None
        if isinstance(time_val, datetime_time):
            return time_val.strftime("%H:%M:%S")
        return None


class BulkImportService:
    """Service pour l'import massif de données."""

    def __init__(self, session: Session):
        self.session = session
        self.import_service = MatchImportService(session)

    def import_from_parser_results(
        self, results: List[dict], commit_batch_size: int = 100
    ) -> dict:
        """Importe les résultats de parsing par batch."""
        stats = {
            "total": len(results), "imported": 0,
            "duplicates": 0, "skipped": 0, "errors": [],
        }

        for i, result in enumerate(results):
            try:
                if not result.get("success", False):
                    stats["skipped"] += 1
                    continue

                match_data = result.get("match")
                if not match_data:
                    stats["skipped"] += 1
                    continue

                if isinstance(match_data, dict):
                    from ..core.models import Match as MatchModel
                    match = MatchModel(**match_data)
                else:
                    match = match_data

                saison = self.import_service._get_or_create_saison(match)
                saison_id = saison.id if saison else None

                if self.import_service._get_match_by_code(match.code_match, saison_id):
                    stats["duplicates"] += 1
                else:
                    self.import_service.import_match(match)
                    stats["imported"] += 1

                if (i + 1) % commit_batch_size == 0:
                    self.session.commit()

            except Exception as e:
                stats["errors"].append({"index": i, "error": str(e)})
                self.session.rollback()
                self.import_service.clear_caches()

        try:
            self.session.commit()
        except Exception as e:
            stats["errors"].append({"final_commit": str(e)})
            self.session.rollback()

        return stats
