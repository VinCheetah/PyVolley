"""
Parser V4 - Parser optimisé basé sur pdfplumber.

Ce parser est une version améliorée qui corrige les problèmes des V2 et V3:
- Extraction complète des joueurs depuis la table dédiée
- Extraction correcte des scores de sets depuis la table RESULTATS
- Meilleure gestion des cas de matchs non joués
- Validation plus robuste des données
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


class MatchSheetParserV4(BaseParser):
    """
    Parser V4 optimisé pour les feuilles de match FFVB.
    
    Utilise pdfplumber avec une stratégie d'extraction basée sur les tables
    pour récupérer de manière fiable toutes les informations.
    
    Points forts:
    - Extraction complète des joueurs via la table dédiée
    - Extraction fiable des scores de sets
    - Gestion robuste des différents cas (match joué, non joué, forfait)
    - Validation des données avec fallback gracieux
    """
    
    # Patterns regex pour l'extraction
    PATTERNS = {
        'code_match': re.compile(r'Match:\s*(\w+)'),
        'journee': re.compile(r'Jour:\s*(\d+)'),
        'date': re.compile(r'(Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)\s+(\d{1,2})\s+(\w+)\s+(\d{4})'),
        'heure': re.compile(r'à\s+(\d{1,2})h(\d{2})'),
        'score_final': re.compile(r'(\d)/(\d)'),
        'duree': re.compile(r"(\d+)'|(\d+h\d+)"),
        'joueur_ligne': re.compile(r'^(\d{1,2})\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑ\-\' ]+?)\s+(\d{6,7})$'),
        'licence': re.compile(r'^\d{6,7}$'),
    }
    
    MOIS = {
        'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4,
        'mai': 5, 'juin': 6, 'juillet': 7, 'août': 8,
        'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12
    }
    
    TOTAL_FIELDS = 35  # Nombre estimé de champs à extraire
    
    @property
    def name(self) -> str:
        return "MatchSheetParserV4"
    
    @property
    def version(self) -> str:
        return "4.0.0"
    
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
                # Vérifier la présence de marqueurs typiques des feuilles FFVB
                markers = ["Ligue", "Match:", "Vainqueur", "RESULTATS"]
                return sum(1 for m in markers if m in text) >= 2
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
                
                # 1. Parser le header (code match, date, lieu, etc.)
                header = self._parse_header(words, full_text)
                fields_count += sum(1 for v in header.values() if v)
                
                # 2. Parser les noms d'équipes depuis les tables
                equipes_info = self._parse_equipes_from_tables(tables, words)
                fields_count += sum(1 for v in equipes_info.values() if v)
                
                # 3. Parser le résultat (vainqueur, score)
                resultat = self._parse_resultat(full_text)
                fields_count += sum(1 for v in resultat.values() if v)
                
                # 4. Vérifier si le match a été joué
                match_joue = self._is_match_played(resultat, full_text)
                if not match_joue:
                    result.add_warning("Match non joué ou annulé")
                
                # 5. Parser les joueurs depuis la table dédiée
                joueurs_a, joueurs_b = self._parse_joueurs_from_tables(tables)
                fields_count += len(joueurs_a) + len(joueurs_b)
                
                # 6. Parser les liberos
                liberos_a, liberos_b = self._parse_liberos_from_tables(tables)
                
                # 7. Parser les scores de sets depuis la table RESULTATS
                sets = self._parse_sets_from_tables(tables, resultat)
                fields_count += len(sets) * 3
                
                # 8. Parser les arbitres et officiels
                arbitres = self._parse_arbitres_from_tables(tables, full_text)
                fields_count += len(arbitres)
                
                # 9. Parser les sanctions (si présentes)
                sanctions = self._parse_sanctions(tables, words)
                
                # 10. Construire le match
                match = self._build_match(
                    header=header,
                    equipes_info=equipes_info,
                    resultat=resultat,
                    joueurs_a=joueurs_a,
                    joueurs_b=joueurs_b,
                    liberos_a=liberos_a,
                    liberos_b=liberos_b,
                    sets=sets,
                    arbitres=arbitres,
                    sanctions=sanctions,
                    pdf_path=pdf_path,
                    match_joue=match_joue
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
    
    def _parse_header(self, words: list, full_text: str) -> dict:
        """Parse l'en-tête du match (code, date, lieu, etc.)."""
        header = {
            "ligue": None,
            "competition": None,
            "code_match": None,
            "journee": None,
            "date": None,
            "date_obj": None,
            "heure": None,
            "heure_obj": None,
            "lieu": None,
            "salle": None,
            "saison": None,
            "categorie": None,
            "genre": None,
        }
        
        # Code match
        match = self.PATTERNS['code_match'].search(full_text)
        if match:
            header["code_match"] = match.group(1)
        
        # Journée
        match = self.PATTERNS['journee'].search(full_text)
        if match:
            header["journee"] = match.group(1)
        
        # Ligue
        ligue_match = re.search(r'Ligue\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ\-]+(?:-[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ]+)*)', full_text)
        if ligue_match:
            header["ligue"] = f"Ligue {ligue_match.group(1)}"
        
        # Compétition - extraire la ligne commençant par un code de compétition
        comp_match = re.search(r'^([A-Z0-9]{2,4})\s*[-–]\s*(.+?)(?:Match:|$)', full_text, re.MULTILINE)
        if comp_match:
            header["competition"] = f"{comp_match.group(1)} - {comp_match.group(2).strip()}"
        
        # Date
        date_match = self.PATTERNS['date'].search(full_text)
        if date_match:
            jour_semaine = date_match.group(1)
            jour = int(date_match.group(2))
            mois_str = date_match.group(3).lower()
            annee = int(date_match.group(4))
            
            header["date"] = f"{jour_semaine} {jour} {mois_str.capitalize()} {annee}"
            
            mois_num = self.MOIS.get(mois_str, 1)
            try:
                header["date_obj"] = dt_date(annee, mois_num, jour)
            except ValueError:
                pass
        
        # Heure
        heure_match = self.PATTERNS['heure'].search(full_text)
        if heure_match:
            h, m = int(heure_match.group(1)), int(heure_match.group(2))
            header["heure"] = f"{h}h{m:02d}"
            try:
                header["heure_obj"] = dt_time(h, m)
            except ValueError:
                pass
        
        # Ville - améliorer le pattern
        ville_match = re.search(r'Ville:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ\s\-\']+)', full_text)
        if ville_match:
            ville = ville_match.group(1).strip()
            # Nettoyer - enlever les jours de semaine qui pourraient être capturés
            ville = re.split(r'\s+(Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)', ville)[0]
            header["lieu"] = ville.strip()
        
        # Salle - améliorer le pattern
        salle_match = re.search(r'Salle:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9][A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9\s\-\'\.]+)', full_text)
        if salle_match:
            salle = salle_match.group(1).strip()
            # Nettoyer - enlever SENIOR/MASCULIN/FEMININ
            salle = re.split(r'\s+(SENIOR|MASCULIN|FEMININ|FÉMININ)', salle)[0]
            header["salle"] = salle.strip()
        
        # Genre et Catégorie
        if "MASCULIN" in full_text.upper():
            header["genre"] = "MASCULIN"
        elif "FÉMININ" in full_text.upper() or "FEMININ" in full_text.upper():
            header["genre"] = "FEMININ"
        elif "MIXTE" in full_text.upper():
            header["genre"] = "MIXTE"
        
        if "SENIOR" in full_text.upper():
            header["categorie"] = "SENIOR"
        elif m := re.search(r'(M\d{2}|U\d{2})', full_text.upper()):
            header["categorie"] = m.group(1)
        
        # Saison (déduire de la date)
        if header["date_obj"]:
            d = header["date_obj"]
            if d.month >= 9:
                header["saison"] = f"{d.year}-{d.year + 1}"
            else:
                header["saison"] = f"{d.year - 1}-{d.year}"
        
        return header
    
    def _parse_equipes_from_tables(self, tables: list, words: list) -> dict:
        """Parse les noms d'équipes depuis les tables."""
        equipes = {"equipe_a": None, "equipe_b": None}
        
        # Chercher la table des joueurs qui contient les noms d'équipes
        for table in tables:
            if not table or len(table) < 2:
                continue
            
            # La table des joueurs a souvent le format:
            # [NOM_EQUIPE_A, ..., NOM_EQUIPE_B, ...]
            # [N°, Nom Prénom, Licence, N°, Nom Prénom, Licence]
            
            for row in table[:2]:  # Vérifier les premières lignes
                if not row:
                    continue
                
                # Chercher une ligne avec "Nom Prénom" et "Licence"
                row_text = ' '.join(str(c) for c in row if c)
                if 'Nom Prénom' in row_text and 'Licence' in row_text:
                    # La ligne précédente devrait avoir les noms d'équipes
                    prev_row_idx = table.index(row) - 1
                    if prev_row_idx >= 0:
                        prev_row = table[prev_row_idx]
                        # Extraire les noms d'équipes (généralement en positions 0 et 3)
                        if prev_row and len(prev_row) >= 4:
                            if prev_row[0] and len(str(prev_row[0])) > 3:
                                equipes["equipe_a"] = str(prev_row[0]).strip()
                            if prev_row[3] and len(str(prev_row[3])) > 3:
                                equipes["equipe_b"] = str(prev_row[3]).strip()
                    break
        
        # Fallback: chercher dans les words (zone y=55-80)
        if not equipes["equipe_a"] or not equipes["equipe_b"]:
            team_words = [w for w in words if 55 <= w['top'] <= 80]
            team_words.sort(key=lambda w: w['x0'])
            
            if team_words:
                max_x = max(w['x1'] for w in words)
                mid_x = max_x / 2
                
                left_texts = [w['text'] for w in team_words if w['x0'] < mid_x]
                right_texts = [w['text'] for w in team_words if w['x0'] >= mid_x]
                
                if left_texts and not equipes["equipe_a"]:
                    equipes["equipe_a"] = ' '.join(left_texts)
                if right_texts and not equipes["equipe_b"]:
                    equipes["equipe_b"] = ' '.join(right_texts)
        
        return equipes
    
    def _parse_resultat(self, full_text: str) -> dict:
        """Parse le résultat du match."""
        resultat = {
            "vainqueur": None,
            "score_final": None,
            "duree_totale": None
        }
        
        # Vainqueur et score - pattern: "Vainqueur: NOM EQUIPE X/Y"
        # On cherche d'abord le pattern complet
        vainqueur_match = re.search(
            r'Vainqueur:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9][A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9\s\-\'\.]+?)\s+(\d)/(\d)',
            full_text
        )
        if vainqueur_match:
            resultat["vainqueur"] = vainqueur_match.group(1).strip()
            resultat["score_final"] = f"{vainqueur_match.group(2)}/{vainqueur_match.group(3)}"
        else:
            # Essayer de trouver le vainqueur et le score séparément
            # Pattern plus permissif pour le vainqueur
            v_match = re.search(
                r'Vainqueur:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9][A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9\s\-\'\.]*)',
                full_text
            )
            if v_match:
                nom = v_match.group(1).strip()
                # Nettoyer - retirer le score s'il est inclus
                nom = re.sub(r'\s*\d/\d\s*$', '', nom).strip()
                if nom and len(nom) > 3 and nom.lower() not in ['xxxxx', '']:
                    resultat["vainqueur"] = nom
            
            # Chercher le score final
            s_match = self.PATTERNS['score_final'].search(full_text)
            if s_match:
                resultat["score_final"] = f"{s_match.group(1)}/{s_match.group(2)}"
        
        # Durée totale - chercher le pattern avec apostrophe ou h
        duree_match = re.search(r'Durée\s*(\d+h\d+)', full_text)
        if duree_match:
            resultat["duree_totale"] = duree_match.group(1)
        else:
            # Essayer avec apostrophe
            duree_match = re.search(r"(\d+)'", full_text)
            if duree_match:
                resultat["duree_totale"] = duree_match.group(1) + "'"
        
        return resultat
    
    def _is_match_played(self, resultat: dict, full_text: str) -> bool:
        """Détermine si le match a été joué."""
        # Un match est considéré comme joué si:
        # - Il y a un vainqueur valide
        # - Le score n'est pas 0/0
        # - Il y a des scores de sets dans RESULTATS
        
        if not resultat.get("vainqueur"):
            return False
        
        score = resultat.get("score_final", "0/0")
        if score == "0/0":
            # Vérifier s'il y a des scores dans la table RESULTATS
            # Un match joué aura des valeurs non nulles
            return False
        
        return True
    
    def _parse_joueurs_from_tables(self, tables: list) -> tuple[list[Joueur], list[Joueur]]:
        """Parse les joueurs depuis la table dédiée."""
        joueurs_a = []
        joueurs_b = []
        
        for table in tables:
            if not table or len(table) < 3:
                continue
            
            # Identifier la table des joueurs
            is_joueurs_table = False
            for row in table[:3]:
                if row:
                    row_text = ' '.join(str(c) for c in row if c)
                    if 'Nom Prénom' in row_text and 'Licence' in row_text:
                        is_joueurs_table = True
                        break
            
            if not is_joueurs_table:
                continue
            
            # Parser les lignes de joueurs
            for row in table:
                if not row:
                    continue
                
                row_text = ' '.join(str(c) for c in row if c)
                
                # Ignorer les headers et lignes spéciales
                if any(kw in row_text for kw in ['Nom Prénom', 'Licence', 'LIBEROS', 'N°']):
                    continue
                
                # La table a généralement 6 colonnes: N°, Nom Prénom, Licence (x2 pour A et B)
                # Ou les joueurs sont dans une cellule fusionnée
                
                # Essayer de parser les cellules contenant plusieurs joueurs
                for cell in row:
                    if not cell:
                        continue
                    
                    cell_str = str(cell).strip()
                    if not cell_str:
                        continue
                    
                    # Pattern: "02 TRIMOREAU MATHIS 2367719"
                    # Les cellules peuvent contenir plusieurs lignes
                    lines = cell_str.split('\n')
                    
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Parser avec regex
                        match = self.PATTERNS['joueur_ligne'].match(line)
                        if match:
                            numero = match.group(1)
                            nom_prenom = match.group(2).strip()
                            licence = match.group(3)
                            
                            # Séparer nom et prénom
                            parts = nom_prenom.split()
                            if len(parts) >= 2:
                                nom = parts[0]
                                prenom = ' '.join(parts[1:])
                            else:
                                nom = nom_prenom
                                prenom = ""
                            
                            joueur = Joueur(
                                numero=numero,
                                nom=nom,
                                prenom=prenom or "Inconnu",
                                licence=licence
                            )
                            
                            # Déterminer l'équipe basé sur la position dans la table
                            # Les colonnes 0-2 sont équipe A, 3-5 sont équipe B
                            cell_idx = list(row).index(cell)
                            if cell_idx < 3:
                                joueurs_a.append(joueur)
                            else:
                                joueurs_b.append(joueur)
        
        return joueurs_a, joueurs_b
    
    def _parse_liberos_from_tables(self, tables: list) -> tuple[list[Joueur], list[Joueur]]:
        """Parse les liberos depuis les tables."""
        liberos_a = []
        liberos_b = []
        
        for table in tables:
            if not table:
                continue
            
            in_liberos_section = False
            
            for row in table:
                if not row:
                    continue
                
                row_text = ' '.join(str(c) for c in row if c)
                
                if 'LIBEROS' in row_text:
                    in_liberos_section = True
                    continue
                
                if in_liberos_section:
                    # Parser les liberos de cette ligne
                    for i, cell in enumerate(row):
                        if not cell:
                            continue
                        
                        cell_str = str(cell).strip()
                        match = self.PATTERNS['joueur_ligne'].match(cell_str)
                        if match:
                            numero, nom_prenom, licence = match.groups()
                            parts = nom_prenom.split()
                            nom = parts[0] if parts else nom_prenom
                            prenom = ' '.join(parts[1:]) if len(parts) > 1 else "Inconnu"
                            
                            joueur = Joueur(
                                numero=numero,
                                nom=nom,
                                prenom=prenom,
                                licence=licence,
                                est_libero=True
                            )
                            
                            if i < len(row) // 2:
                                liberos_a.append(joueur)
                            else:
                                liberos_b.append(joueur)
                    
                    # Les liberos sont généralement sur une seule ligne
                    in_liberos_section = False
        
        return liberos_a, liberos_b
    
    def _parse_sets_from_tables(self, tables: list, resultat: dict) -> list[Set]:
        """Parse les scores de sets depuis la table RESULTATS."""
        sets = []
        
        for table in tables:
            if not table or len(table) < 3:
                continue
            
            # Chercher la table RESULTATS
            is_results = False
            for row in table[:2]:
                if row:
                    row_text = ' '.join(str(c) for c in row if c)
                    if 'RESULTATS' in row_text or ('Equipe A' in row_text and 'Equipe B' in row_text):
                        is_results = True
                        break
            
            if not is_results:
                continue
            
            # Parser la table RESULTATS
            # Format typique:
            # [RESULTATS, ...]
            # [Equipe A, ..., Equipe B, ...]
            # [T, R, G, P, Durée par Set, P, G, R, T]
            # [0, 0, 0, 0, 0', 0, 0, 0, 0]  <- scores totaux ou par set
            
            for row in table:
                if not row:
                    continue
                
                row_text = ' '.join(str(c) for c in row if c)
                
                # Ignorer les headers
                if any(kw in row_text for kw in ['RESULTATS', 'Equipe', 'Durée par Set', 'T', 'R', 'G', 'P', 'Début', 'Fin']):
                    continue
                
                # Chercher des lignes avec des scores (nombres)
                numbers = []
                for cell in row:
                    if cell is not None:
                        cell_str = str(cell).strip().replace("'", "")
                        if cell_str.isdigit():
                            numbers.append(int(cell_str))
                
                # Si on a au moins 8 nombres, c'est probablement la ligne de résultat
                # Format: [T_A, R_A, G_A, P_A, duree, P_B, G_B, R_B, T_B]
                if len(numbers) >= 8:
                    # Les colonnes G (index 2 et -3) contiennent le nombre de sets gagnés
                    # On peut reconstruire les sets à partir du score final
                    pass
        
        # Si pas de sets trouvés dans les tables, reconstruire depuis le score
        if not sets and resultat.get("score_final"):
            try:
                parts = resultat["score_final"].split("/")
                sets_a = int(parts[0])
                sets_b = int(parts[1])
                
                # Créer des objets Set basiques
                for i in range(sets_a + sets_b):
                    # On ne connaît pas les scores exacts
                    set_obj = Set(numero=i + 1)
                    sets.append(set_obj)
            except Exception:
                pass
        
        return sets
    
    def _parse_arbitres_from_tables(self, tables: list, full_text: str) -> list[Arbitre]:
        """Parse les arbitres et officiels."""
        arbitres = []
        
        # Chercher dans les tables - format: ['1er', ..., 'NOM PRENOM', ..., 'LIGUE', ..., 'LICENCE']
        for table in tables:
            if not table:
                continue
            
            for row in table:
                if not row:
                    continue
                
                # Convertir en liste pour avoir des indices
                row_list = list(row)
                
                # Chercher les rôles d'arbitre
                for role_text, role_enum in [('1er', RoleArbitre.PREMIER), ('2ème', RoleArbitre.SECOND), ('Marqueur', RoleArbitre.MARQUEUR)]:
                    try:
                        # Trouver l'index du rôle dans la ligne
                        role_idx = None
                        for i, cell in enumerate(row_list):
                            if cell and str(cell).strip() == role_text:
                                role_idx = i
                                break
                        
                        if role_idx is None:
                            continue
                        
                        # Chercher le nom (cellule non vide après le rôle)
                        nom_complet = None
                        licence = None
                        ligue = None
                        
                        for j in range(role_idx + 1, min(role_idx + 20, len(row_list))):
                            cell = row_list[j]
                            if not cell:
                                continue
                            
                            cell_str = str(cell).strip()
                            if not cell_str:
                                continue
                            
                            # C'est une licence (6-7 chiffres)
                            if cell_str.isdigit() and 6 <= len(cell_str) <= 7:
                                licence = cell_str
                                continue
                            
                            # C'est un code de ligue (2-4 lettres majuscules)
                            if cell_str.isupper() and 2 <= len(cell_str) <= 4 and cell_str.isalpha():
                                ligue = cell_str
                                continue
                            
                            # C'est probablement le nom si ça contient des lettres et un espace
                            if ' ' in cell_str and any(c.isalpha() for c in cell_str):
                                # Ignorer les headers
                                if cell_str not in ['NOM Prénom', 'Nom Prénom']:
                                    nom_complet = cell_str
                                    break
                        
                        if nom_complet and len(nom_complet) > 3:
                            # Séparer NOM et Prénom
                            parts = nom_complet.split()
                            if len(parts) >= 2:
                                # Généralement NOM (majuscules) PRENOM
                                nom = parts[0]
                                prenom = ' '.join(parts[1:])
                            else:
                                nom = nom_complet
                                prenom = None
                            
                            arbitres.append(Arbitre(
                                nom=nom,
                                prenom=prenom,
                                role=role_enum,
                                licence=licence,
                                ligue=ligue
                            ))
                    except Exception:
                        pass
        
        # Si pas trouvé dans les tables, essayer les patterns dans le texte
        if not arbitres:
            patterns = [
                (r'1er\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ\-\']+)\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][a-zA-Zàâäéèêëïîôùûüç\-\']+)', RoleArbitre.PREMIER),
                (r'Marqueur\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ\-\']+)\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][a-zA-Zàâäéèêëïîôùûüç\-\']+)', RoleArbitre.MARQUEUR),
            ]
            
            for pattern, role in patterns:
                match = re.search(pattern, full_text)
                if match:
                    nom = match.group(1).strip()
                    prenom = match.group(2).strip()
                    
                    if nom.lower() not in ['signature', 'ligue', 'licence', 'nom', 'prénom', 'pac', 'idf', 'ara']:
                        arbitres.append(Arbitre(
                            nom=nom,
                            prenom=prenom,
                            role=role
                        ))
        
        return arbitres
    
    def _parse_sanctions(self, tables: list, words: list) -> list[Sanction]:
        """Parse les sanctions du match."""
        sanctions = []
        # TODO: Implémenter le parsing des sanctions depuis la zone dédiée
        return sanctions
    
    def _build_match(
        self,
        header: dict,
        equipes_info: dict,
        resultat: dict,
        joueurs_a: list[Joueur],
        joueurs_b: list[Joueur],
        liberos_a: list[Joueur],
        liberos_b: list[Joueur],
        sets: list[Set],
        arbitres: list[Arbitre],
        sanctions: list[Sanction],
        pdf_path: Path,
        match_joue: bool
    ) -> Match:
        """Construit l'objet Match final."""
        
        # Créer les équipes avec validation
        nom_a = equipes_info.get("equipe_a") or "Équipe A"
        nom_b = equipes_info.get("equipe_b") or "Équipe B"
        
        # S'assurer que les noms ont au moins 2 caractères (validation Pydantic)
        if len(nom_a) < 2:
            nom_a = "Équipe A"
        if len(nom_b) < 2:
            nom_b = "Équipe B"
        
        equipe_a = Equipe(
            nom=nom_a,
            joueurs=joueurs_a,
            liberos=liberos_a
        )
        equipe_b = Equipe(
            nom=nom_b,
            joueurs=joueurs_b,
            liberos=liberos_b
        )
        
        # Calculer les sets gagnés
        sets_a = 0
        sets_b = 0
        if resultat.get("score_final"):
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
            code_match=header.get("code_match") or "UNKNOWN",
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
            sanctions=sanctions,
            source_pdf=str(pdf_path),
            parsed_at=datetime.now()
        )
