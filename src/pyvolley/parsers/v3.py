"""
Parser V3 - Implémentation basée sur pdfplumber.

Ce parser utilise pdfplumber pour l'extraction de texte
avec une meilleure gestion des tables et positions.
"""

import time
import re
from pathlib import Path
from typing import Optional
from datetime import datetime, date as dt_date, time as dt_time
from collections import defaultdict

import pdfplumber

from pyvolley.parsers.base import BaseParser, ParseResult
from pyvolley.core.models import (
    Match, Set, Joueur, Equipe, Arbitre, Sanction,
    Genre, Categorie, RoleArbitre, TypeSanction
)


class MatchSheetParserV3(BaseParser):
    """
    Parser V3 pour les feuilles de match FFVB.
    
    Utilise pdfplumber pour extraire le texte avec les positions
    et les tables de manière plus fiable.
    
    Points forts:
    - Meilleure extraction des tables
    - API plus simple que PyMuPDF
    - Gestion native des caractères Unicode
    
    Limites:
    - Légèrement plus lent que PyMuPDF
    - Nécessite pdfplumber comme dépendance
    """
    
    # Zones verticales du PDF (coordonnées Y)
    ZONE_HEADER = (0, 55)       # Compétition, code match
    ZONE_TEAMS = (55, 90)       # Noms des équipes
    ZONE_SETS_1_2 = (90, 165)   # Sets 1 et 2
    ZONE_SETS_3_4 = (165, 250)  # Sets 3 et 4
    ZONE_JOUEURS = (280, 400)   # Liste des joueurs
    ZONE_RESULTS = (420, 550)   # Résultats finaux
    
    TOTAL_FIELDS = 30
    
    @property
    def name(self) -> str:
        return "MatchSheetParserV3"
    
    @property
    def version(self) -> str:
        return "3.0.0"
    
    def can_parse(self, pdf_path: Path) -> bool:
        """Vérifie si le fichier est un PDF FFVB valide."""
        pdf_path = Path(pdf_path)
        
        if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
            return False
        
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                if len(pdf.pages) == 0:
                    return False
                text = pdf.pages[0].extract_text() or ""
                markers = ["Ligue", "CHAMPIONNAT", "Vainqueur", "Set"]
                return any(marker in text for marker in markers)
        except Exception:
            return False
    
    def parse(self, pdf_path: Path) -> ParseResult:
        """Parse un fichier PDF de feuille de match."""
        pdf_path = Path(pdf_path)
        start_time = time.time()
        result = ParseResult(success=False)
        
        try:
            if not pdf_path.exists():
                result.add_error(f"Fichier non trouvé: {pdf_path}")
                return result
            
            with pdfplumber.open(str(pdf_path)) as pdf:
                if len(pdf.pages) == 0:
                    result.add_error("PDF vide")
                    return result
                
                page = pdf.pages[0]
                words = page.extract_words()
                tables = page.extract_tables()
                full_text = page.extract_text() or ""
                
                if not words:
                    result.add_error("Aucun texte extrait du PDF")
                    return result
                
                fields_count = 0
                
                # Parser les sections
                header = self._parse_header(words, full_text)
                fields_count += sum(1 for v in header.values() if v)
                
                equipes = self._parse_equipes(words)
                fields_count += sum(1 for v in equipes.values() if v)
                
                resultat = self._parse_resultat(words, full_text)
                fields_count += sum(1 for v in resultat.values() if v)
                
                # Vérifier si match joué
                if not resultat.get("vainqueur") and not resultat.get("score_final"):
                    result.add_warning("Match non joué ou annulé")
                
                sets = self._parse_sets(words, tables)
                fields_count += len(sets) * 3
                
                joueurs_a, joueurs_b = self._parse_joueurs(words, tables)
                fields_count += len(joueurs_a) + len(joueurs_b)
                
                arbitres = self._parse_arbitres(words, full_text)
                fields_count += len(arbitres)
                
                # Construire le match
                match = self._build_match(
                    header, equipes, resultat, 
                    sets, joueurs_a, joueurs_b,
                    arbitres, pdf_path
                )
                
                result.success = True
                result.match = match
                result.fields_extracted = fields_count
                result.fields_total = self.TOTAL_FIELDS
                
        except Exception as e:
            result.add_error(f"Erreur de parsing: {str(e)}")
            import traceback
            result.add_error(traceback.format_exc())
        
        finally:
            result.parse_time_ms = (time.time() - start_time) * 1000
            self._record_result(result)
        
        return result
    
    def _get_words_in_zone(self, words: list, y_min: float, y_max: float) -> list:
        """Filtre les mots dans une zone verticale."""
        return [w for w in words if y_min <= w['top'] < y_max]
    
    def _parse_header(self, words: list, full_text: str) -> dict:
        """Parse l'en-tête du match."""
        header = {
            "ligue": None,
            "competition": None,
            "code_match": None,
            "journee": None,
            "date": None,
            "heure": None,
            "lieu": None,
            "salle": None,
            "saison": None,
            "categorie": None,
            "genre": None,
        }
        
        header_words = self._get_words_in_zone(words, 0, 60)
        header_text = ' '.join(w['text'] for w in header_words)
        
        # Ligue - prendre uniquement le nom de la ligue (ex: ILE-DE-FRANCE)
        ligue_match = re.search(r'Ligue\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ\-]+(?:-[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ]+)*)', full_text, re.IGNORECASE)
        if ligue_match:
            header["ligue"] = f"Ligue {ligue_match.group(1)}"
        
        # Compétition - prendre jusqu'à POULE X
        comp_match = re.search(r'(CHAMPIONNAT[^:]+?(?:POULE\s+[A-Z]))', full_text)
        if not comp_match:
            comp_match = re.search(r'(CHAMPIONNAT[^M]+MASCULIN|CHAMPIONNAT[^F]+FEMININ)', full_text, re.IGNORECASE)
        if comp_match:
            header["competition"] = comp_match.group(1).strip()
        
        # Code match
        code_match = re.search(r'Match:\s*(\w+)', header_text)
        if code_match:
            header["code_match"] = code_match.group(1)
        
        # Journée
        jour_match = re.search(r'Jour:\s*(\d+)', header_text)
        if jour_match:
            header["journee"] = jour_match.group(1)
        
        # Date
        date_pattern = r'(Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)\s+(\d{1,2})\s+(\w+)\s+(\d{4})'
        date_match = re.search(date_pattern, full_text)
        if date_match:
            header["date"] = f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3)} {date_match.group(4)}"
            # Parser en objet date
            try:
                mois = {
                    'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4,
                    'mai': 5, 'juin': 6, 'juillet': 7, 'août': 8,
                    'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12
                }
                jour = int(date_match.group(2))
                mois_num = mois.get(date_match.group(3).lower(), 1)
                annee = int(date_match.group(4))
                header["date_obj"] = dt_date(annee, mois_num, jour)
            except Exception:
                pass
        
        # Heure
        heure_match = re.search(r'à\s+(\d{1,2})h(\d{2})', full_text)
        if heure_match:
            header["heure"] = f"{heure_match.group(1)}h{heure_match.group(2)}"
            try:
                header["heure_obj"] = dt_time(int(heure_match.group(1)), int(heure_match.group(2)))
            except Exception:
                pass
        
        # Ville
        ville_match = re.search(r'Ville:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ\s\-]+)', full_text)
        if ville_match:
            # Prendre jusqu'au prochain mot-clé
            ville = ville_match.group(1).strip()
            ville = re.split(r'\s+(Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)', ville)[0]
            header["lieu"] = ville.strip()
        
        # Salle
        salle_match = re.search(r'Salle:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9\s\-\']+)', full_text, re.IGNORECASE)
        if salle_match:
            salle = salle_match.group(1).strip()
            salle = re.split(r'\s+(SENIOR|MASCULIN|FEMININ)', salle)[0]
            header["salle"] = salle.strip()
        
        # Genre et catégorie
        if "MASCULIN" in full_text.upper():
            header["genre"] = "MASCULIN"
        elif "FEMININ" in full_text.upper() or "FÉMININ" in full_text.upper():
            header["genre"] = "FEMININ"
        
        if "SENIOR" in full_text.upper():
            header["categorie"] = "SENIOR"
        
        # Saison (déduire de la date)
        if header.get("date_obj"):
            d = header["date_obj"]
            if d.month >= 9:
                header["saison"] = f"{d.year}-{d.year + 1}"
            else:
                header["saison"] = f"{d.year - 1}-{d.year}"
        
        return header
    
    def _parse_equipes(self, words: list) -> dict:
        """Parse les noms des équipes."""
        equipes = {"equipe_a": None, "equipe_b": None}
        
        # Les noms d'équipes sont en gros caractères (height >= 9) à Y ~ 60
        # Format: EQUIPE_A | EQUIPE_B sur la même ligne
        team_words = [w for w in words 
                      if 55 <= w['top'] <= 75 
                      and w.get('height', 0) >= 9]
        
        if not team_words:
            # Fallback: chercher dans la zone Y=60-80
            team_words = self._get_words_in_zone(words, 55, 80)
        
        if not team_words:
            return equipes
        
        # Trier par position X
        team_words.sort(key=lambda w: w['x0'])
        
        # Trouver le point de séparation entre les deux équipes
        # Généralement autour de X=420-450
        max_x = max(w['x1'] for w in words) if words else 800
        
        # Chercher un gap significatif entre les mots
        gap_threshold = 30
        best_gap_idx = None
        best_gap_size = 0
        
        for i in range(len(team_words) - 1):
            gap = team_words[i + 1]['x0'] - team_words[i]['x1']
            if gap > best_gap_size and gap > gap_threshold:
                best_gap_size = gap
                best_gap_idx = i
        
        if best_gap_idx is not None:
            # Équipe A: mots avant le gap
            team_a_parts = [w['text'] for w in team_words[:best_gap_idx + 1]]
            # Équipe B: mots après le gap
            team_b_parts = [w['text'] for w in team_words[best_gap_idx + 1:]]
        else:
            # Fallback: séparer au milieu
            mid_x = max_x / 2
            team_a_parts = [w['text'] for w in team_words if w['x0'] < mid_x]
            team_b_parts = [w['text'] for w in team_words if w['x0'] >= mid_x]
        
        # Nettoyer les noms (retirer chiffres isolés à la fin)
        if team_a_parts:
            # Retirer le "1" ou "2" final s'il existe
            if team_a_parts[-1].isdigit():
                team_a_parts = team_a_parts[:-1]
            equipes["equipe_a"] = ' '.join(team_a_parts)
        
        if team_b_parts:
            if team_b_parts[-1].isdigit():
                team_b_parts = team_b_parts[:-1]
            equipes["equipe_b"] = ' '.join(team_b_parts)
        
        return equipes
    
    def _parse_resultat(self, words: list, full_text: str) -> dict:
        """Parse le résultat du match."""
        resultat = {
            "vainqueur": None,
            "score_final": None,
            "duree_totale": None
        }
        
        # Chercher le vainqueur
        vainqueur_match = re.search(r'Vainqueur:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9\s\-]+?)\s+(\d)/(\d)', full_text)
        if vainqueur_match:
            resultat["vainqueur"] = vainqueur_match.group(1).strip()
            resultat["score_final"] = f"{vainqueur_match.group(2)}/{vainqueur_match.group(3)}"
        else:
            # Essayer séparément
            vainqueur_match = re.search(r'Vainqueur:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9\s\-]+)', full_text)
            if vainqueur_match:
                nom = vainqueur_match.group(1).strip()
                # Nettoyer les chiffres de score
                nom = re.sub(r'\s*\d+/\d+\s*$', '', nom)
                if nom and nom.lower() != 'xxxxx':
                    resultat["vainqueur"] = nom
            
            score_match = re.search(r'(\d)/(\d)', full_text)
            if score_match:
                resultat["score_final"] = f"{score_match.group(1)}/{score_match.group(2)}"
        
        # Durée totale
        duree_match = re.search(r"(\d+)'\s*$", full_text, re.MULTILINE)
        if not duree_match:
            duree_match = re.search(r'(\d+h\d+)', full_text)
        if duree_match:
            resultat["duree_totale"] = duree_match.group(1)
        
        return resultat
    
    def _parse_sets(self, words: list, tables: list) -> list[Set]:
        """Parse les scores des sets."""
        sets = []
        
        # Chercher dans la zone des résultats (Y > 420)
        result_words = self._get_words_in_zone(words, 420, 550)
        
        # Chercher les patterns de scores dans les tables RESULTATS
        for table in tables:
            for row in table:
                if not row:
                    continue
                # La ligne avec "Durée par Set" contient les headers
                if any(cell and 'Durée' in str(cell) for cell in row):
                    continue
                # Chercher lignes avec scores (nombres entre 0-30)
                scores = []
                for cell in row:
                    if cell and str(cell).isdigit():
                        val = int(cell)
                        if 0 <= val <= 30:
                            scores.append(val)
                # Si on a des paires de scores
                if len(scores) >= 2:
                    # Format typique: T R G P (total, rounds, games, points)
                    pass
        
        # Méthode alternative: chercher directement dans le texte
        # Format typique: ligne avec scores 25-20, 25-22, etc.
        all_text = ' '.join(w['text'] for w in words)
        
        # Pattern pour les scores de sets individuels dans la grille
        # Chercher dans la zone Y=450 les scores
        score_words = self._get_words_in_zone(words, 445, 490)
        
        # Grouper par lignes (Y similaire)
        lines = defaultdict(list)
        for w in score_words:
            y_key = round(w['top'] / 10) * 10
            lines[y_key].append(w)
        
        # Chercher les lignes avec les scores finaux par set
        set_scores = []
        for y in sorted(lines.keys()):
            line_words = sorted(lines[y], key=lambda w: w['x0'])
            line_texts = [w['text'] for w in line_words]
            
            # Chercher des paires (score_a, score_b)
            # Dans la grille RESULTATS, format: T R G P  duree  P G R T
            for i, text in enumerate(line_texts):
                if text.isdigit():
                    val = int(text)
                    if 15 <= val <= 30:  # Score de set valide
                        set_scores.append(val)
        
        # Les scores viennent par paires (equipe A, equipe B)
        # Mais il faut identifier l'ordre correct
        
        # Chercher dans les tables la grille RESULTATS
        for table in tables:
            # Chercher la table avec "RESULTATS"
            is_results = False
            for row in table:
                if row and any(cell and 'RESULTATS' in str(cell) for cell in row):
                    is_results = True
                    break
            
            if is_results:
                # Parser les scores de cette table
                for row in table:
                    if not row:
                        continue
                    # Ignorer les headers
                    if any(cell and str(cell) in ['T', 'R', 'G', 'P', 'Durée'] for cell in row[:5]):
                        # C'est possiblement une ligne de scores
                        numbers = []
                        for cell in row:
                            if cell and str(cell).isdigit():
                                numbers.append(int(cell))
                        
                        # Format attendu: [total_A, sets_A, games_A, pts_A, ..., pts_B, games_B, sets_B, total_B]
                        if len(numbers) >= 8:
                            # Les colonnes G (games/sets) sont à l'index 2 et -3
                            sets_a = numbers[2] if len(numbers) > 2 else 0
                            sets_b = numbers[-3] if len(numbers) > 2 else 0
                            
        # Si on n'a pas trouvé dans les tables, reconstruire depuis les scores individuels
        if not sets and set_scores:
            # Grouper les scores par sets
            # Le nombre de sets dépend du score final
            pass
        
        return sets
    
    def _parse_joueurs(self, words: list, tables: list) -> tuple[list[Joueur], list[Joueur]]:
        """Parse les joueurs des deux équipes."""
        joueurs_a = []
        joueurs_b = []
        
        # Chercher dans la zone joueurs (Y ~ 280-400)
        joueur_words = self._get_words_in_zone(words, 275, 410)
        
        # Regrouper par lignes
        lines = defaultdict(list)
        for w in joueur_words:
            y_key = round(w['top'] / 12) * 12
            lines[y_key].append(w)
        
        # Patterns pour parser les joueurs
        # Format: N° NOM PRENOM LICENCE
        licence_pattern = re.compile(r'^\d{6,7}$')
        
        max_x = max(w['x1'] for w in words) if words else 800
        mid_x = max_x / 2
        
        for y in sorted(lines.keys()):
            line_words = sorted(lines[y], key=lambda w: w['x0'])
            
            # Séparer gauche/droite
            left = [w for w in line_words if w['x0'] < mid_x]
            right = [w for w in line_words if w['x0'] >= mid_x]
            
            # Parser chaque côté
            for side_words, joueurs_list in [(left, joueurs_a), (right, joueurs_b)]:
                if not side_words:
                    continue
                
                texts = [w['text'] for w in side_words]
                
                # Chercher pattern: numéro (1-2 chiffres), nom, prénom, licence
                for i, text in enumerate(texts):
                    if text.isdigit() and 1 <= int(text) <= 30:
                        numero = int(text)
                        nom = texts[i+1] if i+1 < len(texts) else None
                        prenom = texts[i+2] if i+2 < len(texts) else None
                        licence = None
                        
                        # Chercher la licence (6-7 chiffres)
                        for j in range(i+1, min(i+5, len(texts))):
                            if licence_pattern.match(texts[j]):
                                licence = texts[j]
                                break
                        
                        if nom and not nom.isdigit() and licence:
                            joueur = Joueur(
                                numero=str(numero),
                                nom=nom,
                                prenom=prenom if prenom and not prenom.isdigit() and not licence_pattern.match(prenom) else "Inconnu",
                                licence=licence
                            )
                            joueurs_list.append(joueur)
                        break
        
        return joueurs_a, joueurs_b
    
    def _parse_arbitres(self, words: list, full_text: str) -> list[Arbitre]:
        """Parse les arbitres."""
        arbitres = []
        
        patterns = [
            (r'1er\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][a-zàâäéèêëïîôùûüç]+(?:\s+[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][a-zàâäéèêëïîôùûüç]+)?)', RoleArbitre.PREMIER),
            (r'2ème\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][a-zàâäéèêëïîôùûüç]+(?:\s+[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][a-zàâäéèêëïîôùûüç]+)?)', RoleArbitre.SECOND),
            (r'Marqueur\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][a-zàâäéèêëïîôùûüç]+(?:\s+[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][a-zàâäéèêëïîôùûüç]+)?)', RoleArbitre.MARQUEUR),
        ]
        
        for pattern, role in patterns:
            match = re.search(pattern, full_text)
            if match:
                nom = match.group(1).strip()
                if nom and nom.lower() not in ['signature', 'ligue', 'licence']:
                    arbitres.append(Arbitre(nom=nom, role=role))
        
        return arbitres
    
    def _build_match(
        self,
        header: dict,
        equipes: dict,
        resultat: dict,
        sets: list[Set],
        joueurs_a: list[Joueur],
        joueurs_b: list[Joueur],
        arbitres: list[Arbitre],
        pdf_path: Path
    ) -> Match:
        """Construit l'objet Match final."""
        
        # Créer les équipes
        equipe_a = Equipe(
            nom=equipes.get("equipe_a", ""),
            joueurs=joueurs_a
        )
        equipe_b = Equipe(
            nom=equipes.get("equipe_b", ""),
            joueurs=joueurs_b
        )
        
        # Calculer les sets gagnés
        sets_a = sum(1 for s in sets if s.score_a and s.score_b and s.score_a > s.score_b)
        sets_b = sum(1 for s in sets if s.score_a and s.score_b and s.score_b > s.score_a)
        
        # Si pas de sets mais score final disponible, parser le score
        if not sets and resultat.get("score_final"):
            try:
                parts = resultat["score_final"].split("/")
                sets_a = int(parts[0])
                sets_b = int(parts[1])
            except Exception:
                pass
        
        # Genre
        genre = None
        if header.get("genre"):
            try:
                genre = Genre(header["genre"])
            except ValueError:
                pass
        
        # Catégorie
        categorie = None
        if header.get("categorie"):
            try:
                categorie = Categorie(header["categorie"])
            except ValueError:
                pass
        
        return Match(
            code_match=header.get("code_match", ""),
            ligue=header.get("ligue"),
            competition=header.get("competition"),
            journee=header.get("journee"),
            saison=header.get("saison"),
            date=header.get("date_obj"),
            heure=header.get("heure_obj"),
            lieu=header.get("lieu"),
            salle=header.get("salle"),
            genre=genre,
            categorie=categorie,
            equipe_a=equipe_a,
            equipe_b=equipe_b,
            sets=sets,
            vainqueur_nom=resultat.get("vainqueur"),
            score_final=resultat.get("score_final"),
            sets_a=sets_a,
            sets_b=sets_b,
            duree_totale=resultat.get("duree_totale"),
            arbitres=arbitres,
            source_pdf=str(pdf_path),
            parsed_at=datetime.now()
        )
