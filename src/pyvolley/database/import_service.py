"""
Service d'import des données de matchs dans la base de données.

Gère l'import des données extraites par les parsers vers la base de données
SQLAlchemy, avec résolution correcte des entités (clubs, équipes, joueurs,
compétitions, poules) et création des liens entre elles.
"""

import re
import logging
import hashlib
from typing import Optional, List, Any, Union
from datetime import datetime, date as datetime_date, time as datetime_time

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..core.models import Match, Joueur, Equipe, Set, Arbitre, Sanction, Officiel
from ..core.geo_data import extract_entite_code_from_path, get_departments_for_entite
from .models import (
    ClubDB, ClubAliasDB, EquipeDB, JoueurDB, MatchDB, SetDB,
    FormationDB, ChangementDB, TimeoutDB,
    ArbitreDB, ArbitreMatchDB, SaisonDB, CompetitionDB, PouleDB,
    EntiteFFVBDB, ParticipationMatchDB, SanctionDB, OfficielMatchDB,
    PersonneDB,
)

logger = logging.getLogger(__name__)


import unicodedata


def normalize_club_name(name: str) -> str:
    """Normalise un nom de club pour le matching.

    - Majuscules
    - Supprime les accents
    - Remplace ponctuation par espaces
    - Supprime les numéros d'équipe en fin de nom (ex: " 2", " 3")
    - Normalise SAINT/ST, SAINTE/STE
    - Coalescence d'espaces
    """
    n = name.upper().strip()
    # Supprimer les accents
    n = ''.join(
        c for c in unicodedata.normalize('NFD', n)
        if unicodedata.category(c) != 'Mn'
    )
    # Ponctuation → espaces
    n = re.sub(r'[.\-/\'\",;:()]+', ' ', n)
    # Supprimer numéro d'équipe final (chiffre isolé en fin)
    n = re.sub(r'\s+\d$', '', n.strip())
    # Normaliser SAINT-/SAINTE-
    n = re.sub(r'\bSAINTE?\b', 'ST', n)
    n = re.sub(r'\bSTE\b', 'ST', n)
    # Coalescence espaces
    n = re.sub(r'\s+', ' ', n)
    return n.strip()


def extract_club_core_name(name: str) -> str:
    """Extrait le nom-noyau d'un club en supprimant les suffixes de volley courants.

    Utilisé pour le matching souple entre variantes d'un même club.

    Exemples :
        'LYON PESD VB'       → 'LYON PESD'
        'LYON PESD VOLLEY'   → 'LYON PESD'
        'VBC CHAMALIERES'    → 'VBC CHAMALIERES'  (préfixe, pas suffixe)
        'ASUL LYON VB'       → 'ASUL LYON'
        'E. FOREZIENNE VB'   → 'E FOREZIENNE'
        'TOUVET VOLLEY-BALL' → 'TOUVET'
    """
    n = normalize_club_name(name)
    # Supprimer les suffixes de volley courants en fin de nom
    # Ordonnés du plus long au plus court pour matcher "VOLLEY BALL" avant "VOLLEY"
    volleyball_suffixes = [
        r'\s+VOLLEY\s*BALL$',
        r'\s+VOLLEYBALL$',
        r'\s+VOLLEY$',
        r'\s+VB$',
        r'\s+AVB$',
        r'\s+VBC$',
        r'\s+VC$',
    ]
    for suffix in volleyball_suffixes:
        n = re.sub(suffix, '', n)
    return n.strip()


def _club_names_match(name_a: str, name_b: str) -> bool:
    """Détermine si deux noms de clubs désignent probablement le même club.

    Règles de matching :
    1. Noms normalisés identiques → True
    2. Noms-noyaux identiques → True (gère 'LYON VB' vs 'LYON VOLLEY')
    3. L'un est préfixe de l'autre (≥ 5 chars) → True (gère 'AS CALUIRE' vs 'AS CALUIRE VB')
    4. Variantes d'orthographe proches → True (Levenshtein ≤ 2 pour les noms courts)
    """
    na = normalize_club_name(name_a)
    nb = normalize_club_name(name_b)

    # 1. Noms normalisés identiques
    if na == nb:
        return True

    # 2. Noms-noyaux identiques
    core_a = extract_club_core_name(name_a)
    core_b = extract_club_core_name(name_b)
    if core_a == core_b and len(core_a) >= 4:
        return True

    # 3. L'un est préfixe de l'autre (pour les cas avec/sans suffixe VB)
    if len(na) >= 5 and len(nb) >= 5:
        if na.startswith(nb) or nb.startswith(na):
            # Vérifier que le suffixe est un mot de volley courant
            longer, shorter = (na, nb) if len(na) > len(nb) else (nb, na)
            suffix = longer[len(shorter):].strip()
            if not suffix or re.match(r'^(VB|VBC|VC|AVB|VOLLEY|VOLLEYBALL|VOLLEY\s*BALL)$', suffix):
                return True

    # 4. Distance d'édition pour les variantes orthographiques proches
    #    (ex: SESSINS vs SEYSSINS, ECHIROLLES vs ECHIROLLES)
    if abs(len(core_a) - len(core_b)) <= 2 and len(core_a) >= 6:
        dist = _levenshtein(core_a, core_b)
        if dist <= 2:
            return True

    return False


def _levenshtein(s1: str, s2: str) -> int:
    """Distance de Levenshtein entre deux chaînes."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if not s2:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr_row.append(min(
                curr_row[j] + 1,       # insertion
                prev_row[j + 1] + 1,   # deletion
                prev_row[j] + cost,    # substitution
            ))
        prev_row = curr_row
    return prev_row[-1]


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
        self._equipe_cache: dict[tuple, EquipeDB] = {}
        self._joueur_cache: dict[str, JoueurDB] = {}
        self._personne_cache: dict[str, PersonneDB] = {}
        self._arbitre_cache: dict[str, ArbitreDB] = {}
        self._competition_cache: dict[tuple[str, int, Optional[str], Optional[str]], CompetitionDB] = {}
        self._poule_cache: dict[tuple[str, int], PouleDB] = {}
        self._entite_cache: dict[str, EntiteFFVBDB] = {}
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
        self._personne_cache.clear()
        self._arbitre_cache.clear()
        self._competition_cache.clear()
        self._poule_cache.clear()
        self._entite_cache.clear()
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
        equipe_a_db = self._resolve_equipe(match_data.equipe_a, match_data, saison, competition)
        equipe_b_db = self._resolve_equipe(match_data.equipe_b, match_data, saison, competition)

        # 5. Créer le match
        heure_str = self._time_to_string(match_data.heure) if match_data.heure else None

        match_db = MatchDB(
            code_match=match_data.code_match,
            journee=match_data.journee,
            date_match=self._parse_date(match_data.date),
            heure_match=heure_str,
            salle=match_data.salle or match_data.lieu,
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
            score_source=getattr(match_data, 'score_source', 'pdf'),
            parsing_status="parsed",
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

    def import_matches(
        self,
        matches: List[Match],
        *,
        batch_size: int = 200,
    ) -> dict:
        """Importe plusieurs matchs avec commit par batch.

        La détection de doublons se fait en base de données (code_match +
        saison_id) : c'est l'unique source de vérité, indépendante de tout
        cache fichier.  Après un ``reset_db``, tous les matchs seront
        ré-importés même si le cache de parsing n'a pas été vidé.

        Chaque batch est commité indépendamment afin qu'une erreur ne fasse
        pas perdre tous les matchs déjà importés.

        Returns:
            Statistiques d'import : total, imported, committed, duplicates,
            errors (avec détails).
        """
        stats: dict = {
            "total": len(matches),
            "imported": 0,
            "committed": 0,
            "duplicates": 0,
            "errors": [],
        }
        batch_imported = 0

        for i, match_data in enumerate(matches):
            try:
                result = self.import_match(match_data)
                if result:
                    stats["imported"] += 1
                    batch_imported += 1
                else:
                    stats["duplicates"] += 1
            except Exception as e:
                stats["errors"].append({
                    "code_match": match_data.code_match,
                    "error": str(e),
                })
                logger.warning("Import error for %s: %s", match_data.code_match, e)
                self.session.rollback()
                self.clear_caches()
                # Le rollback a annulé les matchs non commités de ce batch
                stats["imported"] -= batch_imported
                batch_imported = 0

            # Commit par batch
            if batch_imported > 0 and (i + 1) % batch_size == 0:
                try:
                    self.session.commit()
                    stats["committed"] += batch_imported
                    batch_imported = 0
                except Exception as e:
                    logger.error("Batch commit failed at index %d: %s", i, e)
                    self.session.rollback()
                    self.clear_caches()
                    stats["errors"].append({"batch_commit": str(e), "index": i})
                    stats["imported"] -= batch_imported
                    batch_imported = 0

        # Commit final
        if batch_imported > 0:
            try:
                self.session.commit()
                stats["committed"] += batch_imported
            except Exception as e:
                logger.error("Final commit failed: %s", e)
                self.session.rollback()
                self.clear_caches()
                stats["errors"].append({"final_commit": str(e)})
                stats["imported"] -= batch_imported

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

    def _get_or_create_entite(self, entite_code: str, organisateur: Optional[str] = None) -> Optional[EntiteFFVBDB]:
        """Crée ou récupère une entité FFVB (ligue, comité, nationale).
        
        Args:
            entite_code: Code de l'entité (ex: "PTRA38", "LIRA", "ABCCS")
            organisateur: Nom de l'organisateur extrait du PDF (fallback pour le nom)
        """
        if not entite_code:
            return None
        
        entite_code = entite_code.strip()
        
        if entite_code in self._entite_cache:
            return self._entite_cache[entite_code]
        
        existing = self.session.scalar(
            select(EntiteFFVBDB).where(EntiteFFVBDB.code == entite_code)
        )
        if existing:
            self._entite_cache[entite_code] = existing
            return existing
        
        # Déterminer le type et le nom
        from ..scrapers.ffvb.entities import detect_entity_type
        entity_type = detect_entity_type(entite_code, organisateur or "")
        
        # Nom : utiliser l'organisateur parsé du PDF si dispo, sinon le code
        nom = organisateur if organisateur else entite_code
        
        entite = EntiteFFVBDB(
            code=entite_code,
            nom=nom,
            type=entity_type,
        )
        self.session.add(entite)
        self.session.flush()
        self._entite_cache[entite_code] = entite
        return entite

    def _resolve_entite(self, match_data: Match) -> Optional[EntiteFFVBDB]:
        """Résout l'entité FFVB organisatrice depuis le chemin PDF et/ou l'organisateur.
        
        Priorité :
        1. Code entité extrait du chemin source_pdf
        2. Fallback : organisateur parsé du header PDF (non utilisé seul car pas de code)
        """
        entite_code = extract_entite_code_from_path(match_data.source_pdf)
        if not entite_code:
            return None
        
        organisateur = getattr(match_data, 'organisateur', None)
        return self._get_or_create_entite(entite_code, organisateur)

    def _get_or_create_competition(
        self, match_data: Match, saison: Optional[SaisonDB]
    ) -> Optional[CompetitionDB]:
        """Crée ou récupère la compétition.

        La compétition est identifiée par son nom + saison + genre.
        Lie l'entité organisatrice (ligue, comité, nationale) si disponible.
        """
        if not match_data.competition:
            return None
        if not saison:
            return None

        genre = match_data.genre.value if match_data.genre else None
        categorie = match_data.categorie.value if match_data.categorie else None
        cache_key = (match_data.competition, saison.id, genre, categorie)

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
        else:
            stmt = stmt.where(CompetitionDB.genre.is_(None))
        if categorie:
            stmt = stmt.where(CompetitionDB.categorie == categorie)
        else:
            stmt = stmt.where(CompetitionDB.categorie.is_(None))

        existing = self.session.scalar(stmt)
        if existing:
            # If entite_id is not yet linked, try to link it now
            if not existing.entite_id:
                entite = self._resolve_entite(match_data)
                if entite:
                    existing.entite_id = entite.id
            self._competition_cache[cache_key] = existing
            return existing

        # Extraire un code lisible depuis le nom de compétition
        comp_code = self._extract_code_from_competition_name(match_data.competition)

        # Résoudre l'entité organisatrice
        entite = self._resolve_entite(match_data)

        competition = CompetitionDB(
            nom=match_data.competition,
            code_competition=comp_code,
            genre=genre,
            categorie=categorie,
            saison_id=saison.id,
            entite_id=entite.id if entite else None,
        )
        self.session.add(competition)
        self.session.flush()
        self._competition_cache[cache_key] = competition
        return competition

    def _get_or_create_poule(
        self, match_data: Match, competition: Optional[CompetitionDB]
    ) -> Optional[PouleDB]:
        """Crée ou récupère la poule.
        
        Pour les compétitions jeunes (ACJEUNES), infère automatiquement
        le numéro de tour à partir du code poule.
        """
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
    def _is_youth_competition(competition: CompetitionDB) -> bool:
        """Checks if a competition is a Coupe de France Jeunes."""
        if competition.nom and competition.nom.startswith("CdF Jeunes"):
            return True
        if competition.entite and competition.entite.code == "ACJEUNES":
            return True
        return False

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

    @staticmethod
    def _extract_niveau_division(competition_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """Extrait le niveau et la division depuis le nom de la compétition.

        Couvre tous les niveaux FFVB : Elite, Ligue A/B, Nationale (N1-N3),
        Prénational, Régional (R1-R3), Départemental (D1-D3), Loisir,
        ainsi que les variantes orthographiques et abréviations.

        Exemples :
            'EMA - ELITE MASCULINE - POULE A'                 → ('ELITE', None)
            'PFA - PRENATIONAL FEMININS POULE A'               → ('PRÉNATIONAL', None)
            'RFC - REGIONAL FEMININS POULE C'                  → ('RÉGIONAL', None)
            'R1M - REGIONALE 1 MASCULINE'                      → ('RÉGIONAL', '1')
            'D2F - DEPARTEMENTALE 2 FEMININE'                  → ('DÉPARTEMENTAL', '2')
            'NM2 - NATIONALE 2 MASCULINE'                      → ('NATIONAL', '2')
            'N3F - NATIONALE 3 FEMININE'                       → ('NATIONAL', '3')
            'CHAMPIONNAT REGIONAL ELITE M15 MASCULINS'         → ('ELITE', None)
            'TOURNOI REGIONAL M13 FEMININS POULE A'            → ('RÉGIONAL', None)
            'TQE M18 FEMININS POULE C'                         → ('ELITE', None)
            'COUPE DE FRANCE'                                  → (None, None)
        """
        if not competition_name:
            return None, None

        upper = competition_name.upper()

        # ── Détection du niveau (du plus élevé au plus bas) ──
        # L'ordre est important : ELITE doit être testé avant REGIONAL
        # car "CHAMPIONNAT REGIONAL ELITE" doit donner ELITE.
        niveau_patterns = [
            # Pro & Elite
            (r'\bELITE\b', 'ELITE'),
            (r'\bLIGUE\s*[AB]\b', 'ELITE'),
            (r'\bLAF\b|\bLBF\b|\bLAM\b|\bLBM\b', 'ELITE'),
            (r'\bTQE\b', 'ELITE'),  # Tournoi Qualification Élite
            (r'\bTQ\b', 'RÉGIONAL'),  # Tournoi de Qualification (régional)
            # National
            (r'\bPR[EÉ]NATIONAL(?:E|AUX|ES?)?\b', 'PRÉNATIONAL'),
            (r'\bPRENATIONAL(?:E|AUX|ES?)?\b', 'PRÉNATIONAL'),
            (r'\bNATIONAL(?:E|AUX|ES?)?\b', 'NATIONAL'),
            # Régional
            (r'\bR[EÉ]GIONAL(?:E|AUX|ES?)?\b', 'RÉGIONAL'),
            (r'\bREGIONAL(?:E|AUX|ES?)?\b', 'RÉGIONAL'),
            # Départemental
            (r'\bD[EÉ]PARTEMENTAL(?:E|AUX|ES?)?\b', 'DÉPARTEMENTAL'),
            (r'\bDEPARTEMENTAL(?:E|AUX|ES?)?\b', 'DÉPARTEMENTAL'),
            # Loisir
            (r'\bLOISIR(?:S)?\b', 'LOISIR'),
            # Tournoi sans qualification de niveau → régional par défaut
            (r'\bTOURNOI\b', 'RÉGIONAL'),
            (r'\bCHAMPIONNAT\b', 'RÉGIONAL'),
        ]

        niveau = None
        for pattern, label in niveau_patterns:
            if re.search(pattern, upper):
                niveau = label
                break

        # Fallback : détecter le niveau via le code abrégé de début
        # P** → Prénational, R** → Régional, D** → Départemental, N** → National, E** → Elite
        # Exclure les codes de catégories d'âge : B (Benjamin), C (Cadet), M (Minime)
        if not niveau:
            m = re.match(r'^([A-Z])([MF])([A-Z\d]?)\s*-', upper)
            if m:
                code_prefix = m.group(1)
                # B, C, M sont des catégories d'âge, pas des niveaux
                if code_prefix not in ('B', 'C', 'M'):
                    prefix_map = {
                        'P': 'PRÉNATIONAL',
                        'R': 'RÉGIONAL',
                        'D': 'DÉPARTEMENTAL',
                        'N': 'NATIONAL',
                        'E': 'ELITE',
                    }
                    niveau = prefix_map.get(code_prefix)

        # ── Extraction de la division (chiffre significatif) ──
        # On ne considère PAS les lettres de poule comme des divisions.
        division = None
        if niveau:
            # 1. Chercher un chiffre dans le nom complet après le mot du niveau
            #    Ex: "NATIONALE 2", "REGIONALE 1", "DEPARTEMENTALE 3"
            for niv_word in [r'NATIONAL(?:E|AUX|ES?)?', r'R[EÉ]GIONAL(?:E|AUX|ES?)?',
                             r'REGIONAL(?:E|AUX|ES?)?', r'D[EÉ]PARTEMENTAL(?:E|AUX|ES?)?',
                             r'DEPARTEMENTAL(?:E|AUX|ES?)?', r'PR[EÉ]NATIONAL(?:E|AUX|ES?)?',
                             r'PRENATIONAL(?:E|AUX|ES?)?']:
                m = re.search(rf'\b{niv_word}\s+(\d)\b', upper)
                if m:
                    division = m.group(1)
                    break

            # 2. Chercher dans le code abrégé : "N3F", "R1M", "D2F"
            if not division:
                m = re.match(r'^[A-Z](\d)[MF]?\s*-', upper)
                if m:
                    division = m.group(1)

            # 3. Chercher N2, N3, R1, R2, D1 isolés dans le nom
            if not division:
                m = re.search(r'\b[NRD](\d)\b', upper)
                if m:
                    division = m.group(1)

        return niveau, division

    def _resolve_equipe(
        self, equipe_data: Optional[Equipe], match_data: Match,
        saison: Optional[SaisonDB], competition: Optional[CompetitionDB] = None,
    ) -> Optional[EquipeDB]:
        """Résout / crée une équipe et son club associé.

        Une équipe est identifiée par (nom, saison, compétition).
        Deux équipes avec le même nom mais dans des compétitions différentes
        (ex: même club en SENIOR et M18) sont des entités distinctes.
        """
        if not equipe_data:
            return None

        nom_equipe = equipe_data.nom
        saison_id = saison.id if saison else None
        competition_id = competition.id if competition else None
        genre = match_data.genre.value if match_data.genre else None
        categorie = match_data.categorie.value if match_data.categorie else None

        # Cache key inclut la compétition, le genre et la catégorie
        # pour séparer les équipes par genre et catégorie d'âge
        cache_key = (nom_equipe, saison_id or 0, competition_id or 0, genre, categorie)
        if cache_key in self._equipe_cache:
            return self._equipe_cache[cache_key]

        # Chercher l'équipe existante (nom + saison + compétition)
        stmt = select(EquipeDB).where(EquipeDB.nom == nom_equipe)
        if saison_id:
            stmt = stmt.where(EquipeDB.saison_id == saison_id)
        if competition_id:
            stmt = stmt.where(EquipeDB.competition_id == competition_id)
        else:
            stmt = stmt.where(EquipeDB.competition_id.is_(None))
        existing = self.session.scalar(stmt)
        if existing:
            self._equipe_cache[cache_key] = existing
            return existing

        # Résoudre le club
        club_nom = equipe_data.club_nom or nom_equipe
        club = self._get_or_create_club(club_nom)

        genre = match_data.genre.value if match_data.genre else None
        categorie = match_data.categorie.value if match_data.categorie else None

        # Extraire niveau/division depuis le nom de compétition
        comp_nom = competition.nom if competition else match_data.competition
        niveau, division = self._extract_niveau_division(comp_nom)

        equipe = EquipeDB(
            nom=nom_equipe,
            numero_equipe=equipe_data.numero_equipe,
            genre=genre,
            categorie=categorie,
            club_id=club.id if club else None,
            saison_id=saison_id,
            competition_id=competition_id,
            niveau=niveau,
            division=division,
        )
        self.session.add(equipe)
        self.session.flush()
        self._equipe_cache[cache_key] = equipe
        return equipe

    def _get_or_create_club(self, nom: str) -> ClubDB:
        """Crée ou récupère un club par nom (avec matching par alias et fuzzy).

        Stratégie de résolution en 5 étapes :
        1. Cache mémoire (nom normalisé)
        2. Alias exact en BDD (nom normalisé)
        3. Nom exact en BDD
        4. Matching souple : comparaison du nom-noyau (sans suffixes VB/volley)
           et distance d'édition avec tous les clubs existants
        5. Création si aucune correspondance
        """
        normalized = normalize_club_name(nom)

        if normalized in self._club_cache:
            return self._club_cache[normalized]

        # 1. Chercher par alias exact
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
                self._create_alias_safe(normalized, existing.id)
            self._club_cache[normalized] = existing
            return existing

        # 3. Matching souple : comparer avec tous les clubs existants
        #    D'abord regarder dans le cache mémoire
        for cached_name, cached_club in self._club_cache.items():
            if _club_names_match(nom, cached_club.nom):
                # Créer un alias pour ce nouveau nom
                self._create_alias_safe(normalized, cached_club.id)
                self._club_cache[normalized] = cached_club
                logger.info(
                    f"Club fuzzy-match: '{nom}' → '{cached_club.nom}' (cache)"
                )
                return cached_club

        #    Puis chercher en BDD (limité pour les performances)
        all_clubs = list(self.session.scalars(select(ClubDB)))
        for existing_club in all_clubs:
            if _club_names_match(nom, existing_club.nom):
                self._create_alias_safe(normalized, existing_club.id)
                self._club_cache[normalized] = existing_club
                logger.info(
                    f"Club fuzzy-match: '{nom}' → '{existing_club.nom}' (DB)"
                )
                return existing_club

        # 4. Créer le club
        club = ClubDB(nom=nom)
        self.session.add(club)
        self.session.flush()

        # Créer l'alias normalisé
        self._create_alias_safe(normalized, club.id)

        self._club_cache[normalized] = club
        return club

    def _create_alias_safe(self, alias: str, club_id: int) -> None:
        """Crée un alias de club si il n'existe pas déjà."""
        existing = self.session.scalar(
            select(ClubAliasDB).where(ClubAliasDB.alias == alias)
        )
        if not existing:
            self.session.add(ClubAliasDB(alias=alias, club_id=club_id))
            self.session.flush()

    # =================================================================
    # Sets
    # =================================================================

    def _import_sets(self, match_db: MatchDB, sets: List[Set]) -> None:
        """Importe les sets d'un match avec formations, changements, timeouts, services."""
        for set_data in sets:
            heure_debut_str = self._time_to_string(set_data.debut) if set_data.debut else None
            heure_fin_str = self._time_to_string(set_data.fin) if set_data.fin else None

            # Sérialiser les données de services (position → scores cumulés)
            # Les clés int doivent être converties en str pour JSON
            services_a = None
            services_b = None
            if set_data.equipe_a and set_data.equipe_a.services:
                services_a = {
                    str(k): v for k, v in set_data.equipe_a.services.items()
                }
            if set_data.equipe_b and set_data.equipe_b.services:
                services_b = {
                    str(k): v for k, v in set_data.equipe_b.services.items()
                }

            set_db = SetDB(
                match_id=match_db.id,
                numero=set_data.numero,
                score_a=set_data.score_a,
                score_b=set_data.score_b,
                heure_debut=heure_debut_str,
                heure_fin=heure_fin_str,
                duree_minutes=set_data.duree_minutes,
                service_initial=set_data.service_initial,
                services_a=services_a,
                services_b=services_b,
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
            licence_str = (jd.licence or "").strip()
            if licence_str and licence_str != "0":
                key = f"LIC:{licence_str}"
            else:
                numero = (jd.numero or "").strip()
                key = f"NAME:{jd.nom.strip().upper()}|{jd.prenom.strip().upper()}|{numero}"
            if key in seen_licences:
                continue
            seen_licences.add(key)
            unique_joueurs.append(jd)

        for joueur_data in unique_joueurs:
            joueur_db = self._get_or_create_joueur(
                joueur_data.licence,
                joueur_data.nom,
                joueur_data.prenom,
            )

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

    def _build_no_licence_key(self, nom: str, prenom: str) -> str:
        normalized = f"{nom.strip().upper()}|{prenom.strip().upper()}"
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        return f"NL-{digest}"

    def _get_or_create_personne(
        self,
        *,
        licence: Optional[str],
        nom: str,
        prenom: Optional[str],
        categorie: str,
    ) -> PersonneDB:
        licence_norm = (licence or "").strip()
        prenom_norm = (prenom or "").strip() or None

        if licence_norm and licence_norm != "0":
            cache_key = f"LIC:{licence_norm}"
            if cache_key in self._personne_cache:
                return self._personne_cache[cache_key]
            existing = self.session.scalar(
                select(PersonneDB).where(PersonneDB.licence == licence_norm)
            )
            if existing:
                if not existing.prenom and prenom_norm:
                    existing.prenom = prenom_norm
                if not existing.categorie:
                    existing.categorie = categorie
                self._personne_cache[cache_key] = existing
                return existing
            personne = PersonneDB(
                licence=licence_norm,
                nom=nom.strip().upper(),
                prenom=prenom_norm,
                categorie=categorie,
            )
            self.session.add(personne)
            self.session.flush()
            self._personne_cache[cache_key] = personne
            return personne

        cache_key = f"NAME:{nom.strip().upper()}|{(prenom_norm or '').upper()}|{categorie}"
        if cache_key in self._personne_cache:
            return self._personne_cache[cache_key]

        existing = self.session.scalar(
            select(PersonneDB).where(
                PersonneDB.nom == nom.strip().upper(),
                PersonneDB.prenom == prenom_norm,
                PersonneDB.categorie == categorie,
            )
        )
        if existing:
            self._personne_cache[cache_key] = existing
            return existing

        personne = PersonneDB(
            licence=None,
            nom=nom.strip().upper(),
            prenom=prenom_norm,
            categorie=categorie,
        )
        self.session.add(personne)
        self.session.flush()
        self._personne_cache[cache_key] = personne
        return personne

    def _get_or_create_joueur(self, licence: Optional[str], nom: str, prenom: str) -> JoueurDB:
        """Crée ou récupère un joueur en évitant les collisions sur licence 0/manquante."""
        licence_norm = (licence or "").strip()
        has_real_licence = bool(licence_norm and licence_norm != "0")

        if has_real_licence:
            cache_key = f"LIC:{licence_norm}"
            if cache_key in self._joueur_cache:
                return self._joueur_cache[cache_key]

            existing = self.session.scalar(
                select(JoueurDB).where(JoueurDB.licence == licence_norm)
            )
            if existing:
                self._joueur_cache[cache_key] = existing
                return existing

            personne = self._get_or_create_personne(
                licence=licence_norm,
                nom=nom,
                prenom=prenom,
                categorie="joueur",
            )
            joueur = JoueurDB(
                licence=licence_norm,
                nom=nom,
                prenom=prenom,
                personne_id=personne.id,
            )
            self.session.add(joueur)
            self.session.flush()
            self._joueur_cache[cache_key] = joueur
            return joueur

        fallback_licence = self._build_no_licence_key(nom, prenom)
        cache_key = f"NO_LIC:{fallback_licence}"
        if cache_key in self._joueur_cache:
            return self._joueur_cache[cache_key]

        existing = self.session.scalar(
            select(JoueurDB).where(JoueurDB.licence == fallback_licence)
        )
        if existing:
            self._joueur_cache[cache_key] = existing
            return existing

        personne = self._get_or_create_personne(
            licence=None,
            nom=nom,
            prenom=prenom,
            categorie="joueur",
        )
        joueur = JoueurDB(
            licence=fallback_licence,
            nom=nom,
            prenom=prenom,
            personne_id=personne.id,
        )
        self.session.add(joueur)
        self.session.flush()
        self._joueur_cache[cache_key] = joueur
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
            personne = self._get_or_create_personne(
                licence=off.licence,
                nom=off.nom,
                prenom=off.prenom,
                categorie="officiel",
            )
            off_db = OfficielMatchDB(
                match_id=match_db.id,
                equipe=equipe_label,
                role=off.role,
                nom=off.nom,
                prenom=off.prenom,
                licence=off.licence,
                personne_id=personne.id,
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

    # =================================================================
    # Enrichissement depuis un PDF parsé (Phase 2)
    # =================================================================

    def enrich_from_pdf(
        self,
        match_db: MatchDB,
        parsed: Match,
        *,
        force: bool = False,
    ) -> bool:
        """Enrichit un match existant en base avec les données d'un PDF parsé.

        C'est la méthode clé qui relie la Phase 1 (scrape CSV → DB) à la
        Phase 2 (parse PDF → enrichissement). Elle met à jour le match avec
        les données détaillées extraites du PDF : compositions, formations,
        changements, timeouts, sanctions, arbitres, officiels.

        Les scores et métadonnées ne sont **pas** écrasés si déjà présents
        depuis l'export CSV (sauf si ``force=True``).

        Args:
            match_db: Enregistrement en base à enrichir.
            parsed: Match Pydantic extrait du parser PDF.
            force: Si True, écrase les données existantes y compris les scores.

        Returns:
            True si le match a été enrichi, False si rien n'a changé.
        """
        if not force and match_db.parsing_status == "parsed" and match_db.has_details:
            logger.debug(
                "enrich_from_pdf: match %s déjà parsé, ignoré",
                match_db.code_match,
            )
            return False

        updated = False
        saison = match_db.saison

        # ── Métadonnées du match (compléter, ne pas écraser) ──
        if parsed.date and (not match_db.date_match or force):
            match_db.date_match = self._parse_date(parsed.date)
            updated = True
        if parsed.heure and (not match_db.heure_match or force):
            match_db.heure_match = self._time_to_string(parsed.heure)
            updated = True
        if parsed.salle and (not match_db.salle or force):
            match_db.salle = parsed.salle
            updated = True
        if parsed.lieu and (not match_db.salle or force):
            match_db.salle = match_db.salle or parsed.lieu
            updated = True
        if parsed.journee and (not match_db.journee or force):
            match_db.journee = parsed.journee
            updated = True

        # ── Résultat (mettre à jour si plus riche ou si forcé) ──
        if parsed.match_joue and (not match_db.match_joue or force):
            match_db.match_joue = True
            updated = True
        if parsed.vainqueur_nom and (not match_db.vainqueur or force):
            match_db.vainqueur = parsed.vainqueur_nom
            updated = True
        if parsed.score_final and (not match_db.score_sets or force):
            match_db.score_sets = parsed.score_final
            updated = True
        if (parsed.sets_a or parsed.sets_b) and (
            (match_db.sets_equipe_a == 0 and match_db.sets_equipe_b == 0) or force
        ):
            match_db.sets_equipe_a = parsed.sets_a
            match_db.sets_equipe_b = parsed.sets_b
            updated = True
        if parsed.duree_totale and (not match_db.duree_totale or force):
            match_db.duree_totale = parsed.duree_totale
            updated = True

        # ── Remarques ──
        if parsed.remarques:
            if match_db.remarques:
                if parsed.remarques not in match_db.remarques:
                    match_db.remarques = f"{match_db.remarques} | {parsed.remarques}"
                    updated = True
            else:
                match_db.remarques = parsed.remarques
                updated = True

        # ── Sets détaillés (supprimer les anciens, recréer) ──
        if parsed.sets:
            # Supprimer les sets existants (scores basiques de l'export)
            for old_set in list(match_db.sets):
                self.session.delete(old_set)
            self.session.flush()

            self._import_sets(match_db, parsed.sets)
            match_db.has_details = True
            match_db.score_source = "pdf"
            updated = True

        # ── Équipes & Joueurs ──
        if parsed.equipe_a:
            equipe_a_db = self._resolve_equipe(
                parsed.equipe_a, parsed, saison,
                match_db.competition,
            )
            if equipe_a_db:
                if not match_db.equipe_a_id or force:
                    match_db.equipe_a_id = equipe_a_db.id
                    updated = True
                self._import_joueurs(match_db, parsed.equipe_a, equipe_a_db)

        if parsed.equipe_b:
            equipe_b_db = self._resolve_equipe(
                parsed.equipe_b, parsed, saison,
                match_db.competition,
            )
            if equipe_b_db:
                if not match_db.equipe_b_id or force:
                    match_db.equipe_b_id = equipe_b_db.id
                    updated = True
                self._import_joueurs(match_db, parsed.equipe_b, equipe_b_db)

        self.session.flush()

        # ── Arbitres ──
        if parsed.arbitres:
            # Supprimer les anciennes associations (souvent basiques depuis l'export)
            for old_am in list(match_db.arbitrages):
                self.session.delete(old_am)
            self.session.flush()
            self._import_arbitres(match_db, parsed.arbitres)
            updated = True

        # ── Sanctions ──
        if parsed.sanctions:
            # Supprimer les anciennes sanctions
            for old_s in list(match_db.sanctions):
                self.session.delete(old_s)
            self.session.flush()
            self._import_sanctions(match_db, parsed.sanctions)
            updated = True

        # ── Officiels d'équipe ──
        if parsed.equipe_a and parsed.equipe_a.officiels:
            for old_off in [o for o in match_db.officiels if o.equipe == "A"]:
                self.session.delete(old_off)
            self.session.flush()
            self._import_officiels(match_db, parsed.equipe_a.officiels, "A")
            updated = True
        if parsed.equipe_b and parsed.equipe_b.officiels:
            for old_off in [o for o in match_db.officiels if o.equipe == "B"]:
                self.session.delete(old_off)
            self.session.flush()
            self._import_officiels(match_db, parsed.equipe_b.officiels, "B")
            updated = True

        # ── Statut et métadonnées ──
        if updated:
            match_db.parsing_status = "parsed"
            match_db.source_pdf = parsed.source_pdf
            match_db.parsed_at = parsed.parsed_at or datetime.now()
            match_db.updated_at = datetime.now()
            self.session.flush()

        return updated

    # =================================================================
    # Requêtes de statut pour le pipeline
    # =================================================================

    def get_matches_by_status(
        self,
        status: str,
        saison_id: Optional[int] = None,
        *,
        limit: Optional[int] = None,
        played_only: bool = False,
    ) -> list[MatchDB]:
        """Récupère les matchs par statut de parsing.

        Args:
            status: Statut souhaité ("discovered", "downloaded", "parsed", "error").
            saison_id: Filtrer par saison (optionnel).
            limit: Nombre max de résultats.
            played_only: Ne retourner que les matchs joués (match_joue=True).

        Returns:
            Liste de MatchDB correspondants.
        """
        stmt = select(MatchDB).where(MatchDB.parsing_status == status)
        if saison_id is not None:
            stmt = stmt.where(MatchDB.saison_id == saison_id)
        if played_only:
            stmt = stmt.where(MatchDB.match_joue == True)  # noqa: E712
        stmt = stmt.order_by(MatchDB.code_match)
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def get_parsing_status_summary(
        self,
        saison_id: Optional[int] = None,
    ) -> dict[str, int]:
        """Retourne un résumé du nombre de matchs par statut de parsing.

        Returns:
            Dict {"discovered": N, "downloaded": N, "parsed": N, "error": N, ...}
        """
        from sqlalchemy import func

        stmt = (
            select(
                MatchDB.parsing_status,
                func.count(MatchDB.id),
            )
            .group_by(MatchDB.parsing_status)
        )
        if saison_id is not None:
            stmt = stmt.where(MatchDB.saison_id == saison_id)

        result = self.session.execute(stmt).all()
        return {status: count for status, count in result}

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
        self, results: List[dict], commit_batch_size: int = 200
    ) -> dict:
        """Importe les résultats de parsing par batch.

        Chaque batch est commité indépendamment pour éviter de perdre
        tout le travail en cas d'erreur ponctuelle.
        """
        stats = {
            "total": len(results), "imported": 0, "committed": 0,
            "duplicates": 0, "skipped": 0, "errors": [],
        }
        batch_imported = 0

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
                    batch_imported += 1

                if batch_imported > 0 and (i + 1) % commit_batch_size == 0:
                    try:
                        self.session.commit()
                        stats["committed"] += batch_imported
                        batch_imported = 0
                    except Exception as e:
                        self.session.rollback()
                        self.import_service.clear_caches()
                        stats["errors"].append({"batch_commit": str(e), "index": i})
                        stats["imported"] -= batch_imported
                        batch_imported = 0

            except Exception as e:
                stats["errors"].append({"index": i, "error": str(e)})
                self.session.rollback()
                self.import_service.clear_caches()
                stats["imported"] -= batch_imported
                batch_imported = 0

        if batch_imported > 0:
            try:
                self.session.commit()
                stats["committed"] += batch_imported
            except Exception as e:
                stats["errors"].append({"final_commit": str(e)})
                self.session.rollback()
                stats["imported"] -= batch_imported

        return stats
