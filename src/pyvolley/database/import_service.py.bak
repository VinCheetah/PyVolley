"""
Service d'import des données de matchs dans la base de données.

Ce module gère l'import des données extraites par les parsers
vers la base de données SQLAlchemy.
"""

from typing import Optional, List, Any, Union
from datetime import datetime, date as datetime_date, time as datetime_time

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..core.models import Match, Joueur, Equipe, Set, Arbitre, Sanction
from .models import (
    ClubDB, EquipeDB, JoueurDB, MatchDB, SetDB,
    ArbitreDB, ArbitreMatchDB, SaisonDB, CompetitionDB, 
    ParticipationMatchDB, SanctionDB
)
from .repositories import (
    JoueurRepository, ClubRepository, EquipeRepository, MatchRepository
)


class MatchImportService:
    """
    Service pour importer les données de matchs dans la base de données.
    
    Gère les relations et évite les doublons.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.joueur_repo = JoueurRepository(session)
        self.club_repo = ClubRepository(session)
        self.equipe_repo = EquipeRepository(session)
        self.match_repo = MatchRepository(session)
    
    def import_match(self, match_data: Match) -> Optional[MatchDB]:
        """
        Importe un match complet dans la base de données.
        
        Args:
            match_data: Données du match à importer (modèle Pydantic)
            
        Returns:
            Le match créé ou None si erreur
        """
        # Vérifier si le match existe déjà
        existing = self.match_repo.get_by_code(match_data.code_match)
        if existing:
            return existing
        
        # Créer ou récupérer la saison
        saison = self._get_or_create_saison(match_data)
        
        # Créer ou récupérer la compétition
        competition = self._get_or_create_competition(match_data, saison)
        
        # Créer ou récupérer les équipes
        equipe_a_nom = match_data.equipe_a.nom if match_data.equipe_a else "Équipe A"
        equipe_b_nom = match_data.equipe_b.nom if match_data.equipe_b else "Équipe B"
        
        equipe_a = self._get_or_create_equipe(equipe_a_nom, match_data.ligue)
        equipe_b = self._get_or_create_equipe(equipe_b_nom, match_data.ligue)
        
        # Parser la date
        date_match = self._parse_date(match_data.date)
        
        # Créer le match
        match_db = MatchDB(
            code_match=match_data.code_match,
            journee=match_data.journee,
            date_match=date_match,
            heure_match=match_data.heure,
            lieu=match_data.lieu,
            salle=match_data.salle,
            competition_id=competition.id if competition else None,
            saison_id=saison.id if saison else None,
            equipe_a_id=equipe_a.id,
            equipe_b_id=equipe_b.id,
            vainqueur_nom=match_data.vainqueur_nom,
            score_final=match_data.score_final,
            duree_totale=match_data.duree_totale,
            remarques=match_data.remarques,
            source_pdf=match_data.source_pdf,
        )
        
        self.session.add(match_db)
        self.session.flush()  # Pour obtenir l'ID
        
        # Ajouter les sets
        self._import_sets(match_db, match_data.sets)
        
        # Ajouter les joueurs et participations
        if match_data.equipe_a:
            self._import_joueurs(match_db, match_data.equipe_a, equipe_a, is_equipe_a=True)
        if match_data.equipe_b:
            self._import_joueurs(match_db, match_data.equipe_b, equipe_b, is_equipe_a=False)
        
        # Ajouter les arbitres
        self._import_arbitres(match_db, match_data.arbitres)
        
        # Ajouter les sanctions
        self._import_sanctions(match_db, match_data.sanctions)
        
        return match_db
    
    def import_matches(self, matches: List[Match]) -> dict:
        """
        Importe plusieurs matchs.
        
        Returns:
            Statistiques d'import (succès, échecs, doublons)
        """
        stats = {
            "total": len(matches),
            "imported": 0,
            "duplicates": 0,
            "errors": []
        }
        
        for match_data in matches:
            try:
                # Vérifier si le match existe déjà avant l'import
                if self.match_repo.get_by_code(match_data.code_match):
                    stats["duplicates"] += 1
                    continue
                
                result = self.import_match(match_data)
                if result:
                    stats["imported"] += 1
                    
            except Exception as e:
                stats["errors"].append({
                    "code_match": match_data.code_match,
                    "error": str(e)
                })
        
        self.session.commit()
        return stats
    
    def _get_or_create_saison(self, match_data: Match) -> Optional[SaisonDB]:
        """Crée ou récupère la saison."""
        # Utiliser la saison du match si fournie
        if match_data.saison:
            parts = match_data.saison.split("-")
            if len(parts) == 2:
                try:
                    annee_debut = int(parts[0])
                    annee_fin = int(parts[1])
                    code = match_data.saison
                except ValueError:
                    return None
            else:
                return None
        elif match_data.date:
            # Extraire la saison de la date
            date = match_data.date if isinstance(match_data.date, datetime_date) else self._parse_date(match_data.date)
            if date:
                if date.month >= 9:
                    annee_debut = date.year
                else:
                    annee_debut = date.year - 1
                annee_fin = annee_debut + 1
                code = f"{annee_debut}-{annee_fin}"
            else:
                return None
        else:
            return None
        
        # Chercher la saison existante
        stmt = select(SaisonDB).where(SaisonDB.code == code)
        existing = self.session.scalar(stmt)
        
        if existing:
            return existing
        
        saison = SaisonDB(
            code=code, 
            nom=f"Saison {code}",
            date_debut=datetime_date(annee_debut, 9, 1),
            date_fin=datetime_date(annee_fin, 6, 30),
        )
        self.session.add(saison)
        self.session.flush()
        return saison
    
    def _get_or_create_competition(
        self, 
        match_data: Match, 
        saison: Optional[SaisonDB]
    ) -> Optional[CompetitionDB]:
        """Crée ou récupère la compétition."""
        if not match_data.competition:
            return None
        
        stmt = select(CompetitionDB).where(
            CompetitionDB.nom == match_data.competition
        )
        if saison:
            stmt = stmt.where(CompetitionDB.saison_id == saison.id)
        
        existing = self.session.scalar(stmt)
        if existing:
            return existing
        
        # Convertir les enums en strings si nécessaire
        categorie = match_data.categorie.value if match_data.categorie else None
        genre = match_data.genre.value if match_data.genre else None
        
        # Générer un code de compétition unique incluant le genre
        code = self._generate_competition_code(match_data.competition, saison, genre)
        
        competition = CompetitionDB(
            code=code,
            nom=match_data.competition,
            ligue=match_data.ligue,
            categorie=categorie,
            genre=genre,
            saison_id=saison.id if saison else None,
        )
        self.session.add(competition)
        self.session.flush()
        return competition
    
    def _generate_competition_code(self, nom: str, saison: Optional[SaisonDB], genre: Optional[str] = None) -> str:
        """Génère un code unique pour une compétition."""
        import re
        # Extraire les initiales du nom
        words = re.findall(r'\b\w', nom.upper())
        code = ''.join(words[:4])
        if not code:
            code = "COMP"
        # Ajouter le genre pour éviter les doublons (M/F)
        if genre:
            code = f"{code}_{genre[0]}"
        # Ajouter la saison
        if saison:
            code = f"{code}_{saison.code}"
        return code[:25]
    
    def _get_or_create_equipe(
        self, 
        nom: str, 
        ligue: Optional[str] = None
    ) -> EquipeDB:
        """Crée ou récupère une équipe."""
        equipe, _ = self.equipe_repo.get_or_create(nom)
        return equipe
    
    def _import_sets(self, match_db: MatchDB, sets: List[Set]) -> None:
        """Importe les sets d'un match."""
        for set_data in sets:
            set_db = SetDB(
                match_id=match_db.id,
                numero=set_data.numero,
                score_a=set_data.score_a,
                score_b=set_data.score_b,
                heure_debut=set_data.debut,
                heure_fin=set_data.fin,
            )
            self.session.add(set_db)
    
    def _import_joueurs(
        self, 
        match_db: MatchDB, 
        equipe_data: Equipe, 
        equipe_db: EquipeDB,
        is_equipe_a: bool
    ) -> None:
        """Importe les joueurs d'une équipe et leurs participations."""
        all_joueurs = list(equipe_data.joueurs) + list(equipe_data.liberos)
        
        for joueur_data in all_joueurs:
            # Générer une licence temporaire si absente
            licence = joueur_data.licence
            if not licence or licence.strip() == "":
                # Créer une licence temporaire basée sur le nom
                licence = f"TEMP_{hash(f'{joueur_data.nom}_{joueur_data.prenom}') % 100000:06d}"
            
            # Créer ou récupérer le joueur
            joueur_db, created = self.joueur_repo.get_or_create(
                licence=licence,
                nom=joueur_data.nom,
                prenom=joueur_data.prenom
            )
            
            # Créer la participation
            participation = ParticipationMatchDB(
                match_id=match_db.id,
                joueur_id=joueur_db.id,
                equipe_id=equipe_db.id,
                numero_maillot=joueur_data.numero,
                est_libero=joueur_data.est_libero or (joueur_data in equipe_data.liberos),
                est_capitaine=joueur_data.est_capitaine,
            )
            self.session.add(participation)
    
    def _import_arbitres(
        self, 
        match_db: MatchDB, 
        arbitres: List[Arbitre]
    ) -> None:
        """Importe les arbitres d'un match."""
        for arb_data in arbitres:
            # Chercher l'arbitre existant
            stmt = select(ArbitreDB).where(
                ArbitreDB.nom == arb_data.nom,
            )
            if arb_data.prenom:
                stmt = stmt.where(ArbitreDB.prenom == arb_data.prenom)
            
            existing = self.session.scalar(stmt)
            
            if not existing:
                arbitre_db = ArbitreDB(
                    nom=arb_data.nom,
                    prenom=arb_data.prenom,
                    licence=arb_data.licence,
                    ligue=arb_data.ligue,
                )
                self.session.add(arbitre_db)
                self.session.flush()
                arbitre_id = arbitre_db.id
            else:
                arbitre_id = existing.id
            
            # Créer la relation arbitre-match
            role = arb_data.role.value if arb_data.role else None
            arb_match = ArbitreMatchDB(
                arbitre_id=arbitre_id,
                match_id=match_db.id,
                role=role,
            )
            self.session.add(arb_match)
    
    def _import_sanctions(
        self, 
        match_db: MatchDB, 
        sanctions: List[Sanction]
    ) -> None:
        """Importe les sanctions d'un match."""
        for sanction_data in sanctions:
            # Convertir le type de sanction
            type_sanction = sanction_data.type.value if sanction_data.type else None
            
            # Formater le score
            score = None
            if sanction_data.score_a is not None and sanction_data.score_b is not None:
                score = f"{sanction_data.score_a}-{sanction_data.score_b}"
            
            sanction_db = SanctionDB(
                match_id=match_db.id,
                set_numero=sanction_data.set_numero,
                equipe=sanction_data.equipe,
                joueur_numero=sanction_data.joueur_numero,
                type_sanction=type_sanction,
                score=score,
            )
            self.session.add(sanction_db)
    
    def _parse_date(
        self, 
        date_val: Union[str, datetime_date, datetime, None]
    ) -> Optional[datetime_date]:
        """Parse une date depuis une chaîne ou la retourne telle quelle."""
        if date_val is None:
            return None
        
        if isinstance(date_val, datetime):
            return date_val.date()
        
        if isinstance(date_val, datetime_date):
            return date_val
        
        if isinstance(date_val, str):
            formats = [
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%Y-%m-%d",
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(date_val, fmt).date()
                except ValueError:
                    continue
        
        return None


class BulkImportService:
    """
    Service pour l'import massif de données.
    
    Optimisé pour de gros volumes de données avec gestion des transactions.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.import_service = MatchImportService(session)
    
    def import_from_parser_results(
        self, 
        results: List[dict], 
        commit_batch_size: int = 100
    ) -> dict:
        """
        Importe les résultats de parsing.
        
        Args:
            results: Liste de dicts avec les résultats du parser
            commit_batch_size: Nombre de matchs par commit
            
        Returns:
            Statistiques d'import
        """
        stats = {
            "total": len(results),
            "imported": 0,
            "duplicates": 0,
            "skipped": 0,
            "errors": []
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
                
                # Convertir le dict en modèle Match si nécessaire
                if isinstance(match_data, dict):
                    match = Match(**match_data)
                else:
                    match = match_data
                
                # Import
                if self.import_service.match_repo.get_by_code(match.code_match):
                    stats["duplicates"] += 1
                else:
                    self.import_service.import_match(match)
                    stats["imported"] += 1
                
                # Commit par batch
                if (i + 1) % commit_batch_size == 0:
                    self.session.commit()
                    
            except Exception as e:
                stats["errors"].append({
                    "index": i,
                    "error": str(e)
                })
                self.session.rollback()
        
        # Commit final
        try:
            self.session.commit()
        except Exception as e:
            stats["errors"].append({"final_commit": str(e)})
            self.session.rollback()
        
        return stats
