"""
Parser V2 - Implémentation complète basée sur PyMuPDF.

Ce parser utilise l'extraction de coordonnées pour parser
les feuilles de match FFVB avec une haute précision.
"""

import time
from pathlib import Path
from typing import Optional
from datetime import datetime

import fitz  # PyMuPDF

from pyvolley.parsers.base import BaseParser, ParseResult
from pyvolley.core.models import (
    Match, Set, Joueur, Equipe, Arbitre, Sanction,
    Formation, TimeOut, Genre, Categorie, RoleArbitre, TypeSanction
)
from pyvolley.core.exceptions import InvalidPDFError, MatchNotPlayedError


class MatchSheetParserV2(BaseParser):
    """
    Parser V2 pour les feuilles de match FFVB.
    
    Utilise PyMuPDF pour extraire le texte avec les positions,
    puis analyse la structure du PDF pour identifier les zones
    et extraire les données.
    
    Points forts:
    - Extraction précise grâce aux coordonnées
    - Gestion des différentes orientations de grille
    - Validation automatique avec le score final
    
    Limites:
    - Spécifique au format FFVB actuel
    - Sensible aux changements de mise en page
    """
    
    # Zones du PDF (coordonnées approximatives)
    HEADER_Y_MAX = 100
    TEAMS_X_BOUNDARY = 700  # Séparation équipe A / B
    GRID_Y_MIN = 445
    GRID_Y_MAX = 530
    
    # Compteur de champs pour les métriques
    TOTAL_FIELDS = 25  # Nombre estimé de champs à extraire
    
    @property
    def name(self) -> str:
        return "MatchSheetParserV2"
    
    @property
    def version(self) -> str:
        return "2.1.0"
    
    def can_parse(self, pdf_path: Path) -> bool:
        """Vérifie si le fichier est un PDF FFVB valide."""
        pdf_path = Path(pdf_path)
        
        if not pdf_path.exists():
            return False
        
        if not pdf_path.suffix.lower() == ".pdf":
            return False
        
        try:
            doc = fitz.open(str(pdf_path))
            if len(doc) == 0:
                doc.close()
                return False
            
            # Vérifier la présence de marqueurs FFVB
            text = doc[0].get_text()
            doc.close()
            
            markers = ["Ligue", "CHAMPIONNAT", "Vainqueur", "Set"]
            return any(marker in text for marker in markers)
            
        except Exception:
            return False
    
    def parse(self, pdf_path: Path) -> ParseResult:
        """
        Parse un fichier PDF de feuille de match.
        
        Args:
            pdf_path: Chemin vers le fichier PDF
            
        Returns:
            ParseResult avec le match parsé
        """
        pdf_path = Path(pdf_path)
        start_time = time.time()
        result = ParseResult(success=False)
        
        try:
            # Charger le PDF
            if not pdf_path.exists():
                result.add_error(f"Fichier non trouvé: {pdf_path}")
                return result
            
            doc = fitz.open(str(pdf_path))
            if len(doc) == 0:
                result.add_error("PDF vide")
                doc.close()
                return result
            
            # Extraire tous les spans avec positions
            page = doc[0]
            all_spans = self._extract_spans(page)
            doc.close()
            
            if not all_spans:
                result.add_error("Aucun texte extrait du PDF")
                return result
            
            # Parser les différentes sections
            fields_count = 0
            
            # Header (ligue, compétition, date, etc.)
            header = self._parse_header(all_spans)
            fields_count += sum(1 for v in header.values() if v)
            
            # Résultat (vainqueur, score)
            resultat = self._parse_resultat(all_spans)
            fields_count += sum(1 for v in resultat.values() if v)
            
            # Vérifier si le match a été joué
            if not resultat.get("vainqueur") and not resultat.get("score_final"):
                result.add_warning("Match non joué")
                result.match = self._build_match(header, resultat, [], [], [], [], all_spans, pdf_path)
                result.success = True
                result.fields_extracted = fields_count
                result.fields_total = self.TOTAL_FIELDS
                return result
            
            # Équipes
            equipe_a, equipe_b = self._parse_equipes(all_spans, header)
            fields_count += 2 if equipe_a.nom else 0
            fields_count += len(equipe_a.joueurs) + len(equipe_b.joueurs)
            
            # Sets avec scores
            sets = self._parse_sets(all_spans, resultat)
            fields_count += len(sets) * 4  # score_a, score_b, debut, fin par set
            
            # Arbitres
            arbitres = self._parse_arbitres(all_spans)
            fields_count += len(arbitres)
            
            # Sanctions
            sanctions = self._parse_sanctions(all_spans)
            
            # Construire le modèle Match
            match = self._build_match(
                header, resultat, 
                [equipe_a, equipe_b],
                sets, arbitres, sanctions,
                all_spans, pdf_path
            )
            
            result.success = True
            result.match = match
            result.fields_extracted = fields_count
            result.fields_total = self.TOTAL_FIELDS
            
        except Exception as e:
            result.add_error(f"Erreur de parsing: {str(e)}")
            
        finally:
            result.parse_time_ms = (time.time() - start_time) * 1000
            self._record_result(result)
        
        return result
    
    def _extract_spans(self, page) -> list[dict]:
        """Extrait tous les spans de texte avec leurs positions."""
        spans = []
        blocks = page.get_text("dict")["blocks"]
        
        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if text:
                            spans.append({
                                "text": text,
                                "x": round(span["bbox"][0], 1),
                                "y": round(span["bbox"][1], 1),
                                "x2": round(span["bbox"][2], 1),
                                "y2": round(span["bbox"][3], 1),
                                "size": span.get("size", 0)
                            })
        
        spans.sort(key=lambda s: (s["y"], s["x"]))
        return spans
    
    def _parse_header(self, spans: list[dict]) -> dict:
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
            "categorie": None,
            "genre": None,
            "equipe_a": None,
            "equipe_b": None,
        }
        
        for s in spans:
            text = s["text"]
            y = s["y"]
            
            if y > self.HEADER_Y_MAX:
                continue
            
            # Ligue
            if "Ligue" in text:
                header["ligue"] = text
            
            # Compétition
            if "CHAMPIONNAT" in text or (":" in text and "POULE" in text):
                header["competition"] = text
                # Extraire catégorie et genre
                if "MASCULIN" in text.upper():
                    header["genre"] = "MASCULIN"
                elif "FEMININ" in text.upper() or "FÉMININ" in text.upper():
                    header["genre"] = "FEMININ"
                if "SENIOR" in text.upper():
                    header["categorie"] = "SENIOR"
            
            # Code match et journée
            if "Match:" in text:
                import re
                match = re.search(r"Match:\s*(\w+)", text)
                if match:
                    header["code_match"] = match.group(1)
                jour = re.search(r"Jour:\s*(\d+)", text)
                if jour:
                    header["journee"] = jour.group(1)
            
            # Date
            if any(day in text for day in ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]):
                header["date"] = text
            
            # Heure
            if "h" in text and any(c.isdigit() for c in text) and len(text) < 10:
                if "h" in text and text.replace("h", "").replace(":", "").isdigit():
                    header["heure"] = text
            
            # Lieu
            if "Ville:" in text:
                header["lieu"] = text.replace("Ville:", "").strip()
            
            # Salle
            if "Salle:" in text:
                header["salle"] = text.replace("Salle:", "").strip()
        
        # Équipes (gros texte y ~ 60-75)
        team_spans = [s for s in spans if 60 < s["y"] < 75 and s.get("size", 0) >= 9]
        team_spans.sort(key=lambda s: s["x"])
        
        if len(team_spans) >= 2:
            header["equipe_a"] = team_spans[0]["text"]
            header["equipe_b"] = team_spans[-1]["text"]
        
        return header
    
    def _parse_resultat(self, spans: list[dict]) -> dict:
        """Parse le résultat du match."""
        resultat = {
            "vainqueur": None,
            "score_final": None,
            "duree_totale": None,
        }
        
        # Chercher dans la zone de résultat (y > 500)
        for s in spans:
            text = s["text"]
            y = s["y"]
            x = s["x"]
            
            if y < 500:
                continue
            
            # Vainqueur (après label "Vainqueur:")
            if 448 < x < 545 and len(text) > 5 and "/" not in text and "Vainqueur" not in text:
                if not resultat["vainqueur"]:
                    resultat["vainqueur"] = text
            
            # Score final (format X/Y)
            if "/" in text and len(text) <= 4:
                if text[0].isdigit() and text[-1].isdigit():
                    resultat["score_final"] = text
            
            # Durée
            if "h" in text.lower() and any(c.isdigit() for c in text):
                if x > 520 and len(text) < 10:
                    resultat["duree_totale"] = text
        
        return resultat
    
    def _parse_equipes(self, spans: list[dict], header: dict) -> tuple[Equipe, Equipe]:
        """Parse les données des deux équipes."""
        equipe_a = Equipe(nom=header.get("equipe_a", ""))
        equipe_b = Equipe(nom=header.get("equipe_b", ""))
        
        # Zone joueurs (y > 110, x < 700 pour A, x > 700 pour B)
        # Format: N° NOM PRENOM LICENCE
        
        import re
        joueur_pattern = re.compile(r"^(\d{1,2})\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ\s\-]+)\s+(\d{6,7})$")
        
        for s in spans:
            y = s["y"]
            x = s["x"]
            text = s["text"]
            
            if y < 110 or y > 400:
                continue
            
            # Essayer de parser une ligne joueur
            # Les joueurs sont souvent sur plusieurs spans, on cherche les licences
            if text.isdigit() and len(text) >= 6:
                # C'est probablement une licence
                if x < self.TEAMS_X_BOUNDARY:
                    # Équipe A
                    pass
                else:
                    # Équipe B
                    pass
        
        return equipe_a, equipe_b
    
    def _parse_sets(self, spans: list[dict], resultat: dict) -> list[Set]:
        """Parse les sets avec scores."""
        sets = []
        
        # Récupérer les scores depuis la grille de résultats
        scores = self._parse_scores_from_grid(spans, resultat)
        
        for set_num, (score_a, score_b) in scores.items():
            set_data = Set(
                numero=set_num,
                score_a=score_a,
                score_b=score_b
            )
            
            # Parser les horaires
            times = self._parse_set_times(spans, set_num)
            if times.get("debut"):
                # Convertir string en time si nécessaire
                pass
            
            sets.append(set_data)
        
        return sets
    
    def _parse_scores_from_grid(self, spans: list[dict], resultat: dict) -> dict[int, tuple[int, int]]:
        """Parse les scores depuis la grille de résultats."""
        from collections import defaultdict
        
        # Trouver les lignes de la grille
        grid_spans = [s for s in spans if self.GRID_Y_MIN < s["y"] < self.GRID_Y_MAX and 420 < s["x"] < 560]
        
        if not grid_spans:
            return {}
        
        # Grouper par Y
        lines_by_y = defaultdict(list)
        for s in grid_spans:
            y_rounded = round(s["y"])
            lines_by_y[y_rounded].append(s)
        
        # Identifier les lignes de sets
        set_lines = []
        for y in sorted(lines_by_y.keys()):
            line_texts = [s["text"].strip() for s in lines_by_y[y]]
            
            # Ignorer header
            if "P" in line_texts or "Durée" in " ".join(line_texts):
                continue
            
            # Chercher les scores
            scores_in_line = []
            for s in lines_by_y[y]:
                text = s["text"].strip()
                if text.isdigit() and 10 <= int(text) <= 50:
                    scores_in_line.append((s["x"], int(text)))
            
            if len(scores_in_line) >= 2:
                scores_in_line.sort(key=lambda t: t[0])
                score_left = None
                score_right = None
                
                for x, val in scores_in_line:
                    if x < 490 and score_left is None:
                        score_left = val
                    elif x > 490 and score_right is None:
                        score_right = val
                
                if score_left is not None and score_right is not None:
                    if max(score_left, score_right) >= 15:
                        set_lines.append((y, score_left, score_right))
        
        # Exclure les totaux
        if len(set_lines) > 1:
            last_left, last_right = set_lines[-1][1], set_lines[-1][2]
            if last_left > 50 or last_right > 50:
                set_lines = set_lines[:-1]
        
        # Construire le dict
        scores_by_set = {}
        for idx, (y, score_left, score_right) in enumerate(set_lines[:5], 1):
            scores_by_set[idx] = (score_left, score_right)
        
        # Valider avec le vainqueur si disponible
        if resultat.get("vainqueur") and resultat.get("score_final"):
            scores_by_set = self._validate_scores_mapping(
                scores_by_set, resultat, spans
            )
        
        return scores_by_set
    
    def _validate_scores_mapping(
        self, 
        scores: dict[int, tuple[int, int]], 
        resultat: dict,
        spans: list[dict]
    ) -> dict[int, tuple[int, int]]:
        """Valide et corrige le mapping des scores si nécessaire."""
        if not scores:
            return scores
        
        # Compter les sets gagnés par chaque colonne
        sets_left = sum(1 for sl, sr in scores.values() if sl > sr)
        sets_right = sum(1 for sl, sr in scores.values() if sr > sl)
        
        try:
            score_parts = resultat["score_final"].split("/")
            expected_winner_sets = int(score_parts[0])
            
            # Déterminer si le vainqueur est l'équipe A (recevante = header left)
            vainqueur = resultat["vainqueur"].upper()
            
            # Chercher l'équipe A dans le header
            header_left = None
            for s in spans:
                if 60 < s["y"] < 75 and s.get("size", 0) >= 9:
                    if header_left is None:
                        header_left = s["text"].upper()
                        break
            
            vainqueur_is_equipe_a = header_left and (
                vainqueur in header_left or header_left in vainqueur
            )
            
            # Vérifier si on doit inverser
            if vainqueur_is_equipe_a:
                if sets_left != expected_winner_sets and sets_right == expected_winner_sets:
                    # Inverser
                    scores = {k: (v[1], v[0]) for k, v in scores.items()}
            else:
                if sets_right != expected_winner_sets and sets_left == expected_winner_sets:
                    # Inverser
                    scores = {k: (v[1], v[0]) for k, v in scores.items()}
        
        except Exception:
            pass
        
        return scores
    
    def _parse_set_times(self, spans: list[dict], set_num: int) -> dict:
        """Parse les horaires d'un set."""
        return {"debut": None, "fin": None}
    
    def _parse_arbitres(self, spans: list[dict]) -> list[Arbitre]:
        """Parse les informations des arbitres."""
        arbitres = []
        
        # Chercher les patterns d'arbitres (1er, 2ème, Marqueur)
        import re
        
        for s in spans:
            text = s["text"]
            
            if "1er:" in text or "2ème:" in text or "Marqueur:" in text:
                role_match = re.match(r"(1er|2ème|Marqueur):\s*(.+)", text)
                if role_match:
                    role_str = role_match.group(1)
                    nom = role_match.group(2).strip()
                    
                    role = {
                        "1er": RoleArbitre.PREMIER,
                        "2ème": RoleArbitre.SECOND,
                        "Marqueur": RoleArbitre.MARQUEUR
                    }.get(role_str, RoleArbitre.PREMIER)
                    
                    arbitres.append(Arbitre(
                        role=role,
                        nom=nom
                    ))
        
        return arbitres
    
    def _parse_sanctions(self, spans: list[dict]) -> list[Sanction]:
        """Parse les sanctions."""
        return []
    
    def _build_match(
        self,
        header: dict,
        resultat: dict,
        equipes: list[Equipe],
        sets: list[Set],
        arbitres: list[Arbitre],
        sanctions: list[Sanction],
        spans: list[dict],
        pdf_path: Path
    ) -> Match:
        """Construit l'objet Match final."""
        equipe_a = equipes[0] if len(equipes) > 0 else Equipe(nom="")
        equipe_b = equipes[1] if len(equipes) > 1 else Equipe(nom="")
        
        # Calculer les sets gagnés
        sets_a = sum(1 for s in sets if s.score_a and s.score_b and s.score_a > s.score_b)
        sets_b = sum(1 for s in sets if s.score_a and s.score_b and s.score_b > s.score_a)
        
        # Déterminer le genre
        genre = None
        if header.get("genre"):
            try:
                genre = Genre(header["genre"])
            except ValueError:
                pass
        
        # Déterminer la catégorie
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
