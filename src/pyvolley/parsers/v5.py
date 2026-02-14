"""
Parser V5 - Parser robuste et exhaustif pour les feuilles de match FFVB.

Améliorations par rapport à V4 :
- Parsing basé sur les lignes de texte pour le header (plus fiable)
- Extraction complète de tous les arbitres avec licence et ligue
- Correction de la troncature des noms de ville et salle
- Correction du mapping des timeouts (gauche/droite → A/B)
- Stockage des changements de joueurs dans les sets
- Extraction des officiels d'équipe (EA, EB, MA, MB, KA, KB)
- Extraction des remarques et demandes non fondées
- Meilleure séparation nom/prénom des joueurs
- Nettoyage des noms d'équipe
- Détection et signalement des sanctions
- Extraction de la progression de service (tours au service)

Architecture du PDF FFVB (page unique) :
  5 tables principales :
    Table 0 (main, ~44 rows)  : Sets 1,3,5 + sanctions + arbitres
    Table 1 (secondary, ~20 rows) : Sets 2,4
    Table 2 (players, ~4 rows)    : Roster joueurs
    Table 3 (results, ~11 rows)   : RESULTATS (scores, durées)
    Table 4 (signatures, ~3 rows) : SIGNATURES

  Header (texte libre) :
    Ligne 1 : Compétition, code match, journée
    Ligne 2 : Ville, date, heure
    Ligne 3 : Salle, genre, catégorie
    Ligne 4 : Organisation, noms d'équipe
"""

import logging
import time
import re
from pathlib import Path
from typing import Optional
from datetime import datetime, date as dt_date, time as dt_time
from collections import defaultdict

import pdfplumber

from pyvolley.parsers.base import BaseParser, ParseResult
from pyvolley.core.models import (
    Match, Set, SetTeamData, Joueur, Equipe, Arbitre, Sanction, Formation, TimeOut,
    Changement, Officiel,
    Genre, Categorie, RoleArbitre, TypeSanction,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constantes
# =============================================================================

MOIS_MAP = {
    'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4,
    'mai': 5, 'juin': 6, 'juillet': 7, 'août': 8,
    'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12,
}

JOURS_SEMAINE = ('Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche')

ROLE_ARBITRE_MAP = {
    '1er': RoleArbitre.PREMIER,
    '2ème': RoleArbitre.SECOND,
    '2éme': RoleArbitre.SECOND,
    'Marqueur': RoleArbitre.MARQUEUR,
    'MarqueurAZAR': RoleArbitre.MARQUEUR,  # pdfplumber sometimes merges
    'Marq.Ass.': RoleArbitre.MARQUEUR_ASSISTANT,
    'R.Salle': RoleArbitre.RESPONSABLE_SALLE,
}

ROWS_PER_SET = 10


# =============================================================================
# Parser V5
# =============================================================================

class MatchSheetParserV5(BaseParser):
    """
    Parser V5 – extraction exhaustive et robuste des feuilles de match FFVB.

    Approche :
    1. Texte plein ligne par ligne → infos header/logistique
    2. Tables structurées → joueurs, résultats, sets, arbitres
    3. Mots positionnels → libéros, officiels, capitaines
    """

    @property
    def name(self) -> str:
        return "MatchSheetParserV5"

    @property
    def version(self) -> str:
        return "5.0.0"

    # =====================================================================
    # Point d'entrée
    # =====================================================================

    def can_parse(self, pdf_path: Path) -> bool:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
            return False
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                if not pdf.pages:
                    return False
                text = pdf.pages[0].extract_text() or ""
                markers = ["Match:", "Vainqueur", "RESULTATS", "SET"]
                return sum(1 for m in markers if m in text) >= 2
        except Exception:
            return False

    def parse(self, pdf_path: Path) -> ParseResult:
        pdf_path = Path(pdf_path)
        start = time.time()
        result = ParseResult(success=False)

        try:
            if not pdf_path.exists():
                result.add_error(f"Fichier non trouvé: {pdf_path}")
                return result

            with pdfplumber.open(str(pdf_path)) as pdf:
                if not pdf.pages:
                    result.add_error("PDF vide")
                    return result

                page = pdf.pages[0]
                full_text = page.extract_text() or ""
                words = page.extract_words()
                tables = page.extract_tables()
                images = page.images
                chars = page.chars

                if not full_text.strip():
                    result.add_error("Aucun texte extrait du PDF")
                    return result

                lines = full_text.split('\n')
                tidx = self._identify_tables(tables)
                fields_count = 0

                # ── Phase 1 : Informations générales (toujours disponibles) ──

                # 1. Header (lignes de texte)
                header = self._parse_header(lines)
                fields_count += sum(1 for v in header.values() if v)

                # 2. Noms d'équipe
                equipes_info = self._parse_equipes(tidx, words, lines)
                fields_count += sum(1 for v in equipes_info.values() if v)

                # ── Phase 2 : Personnes (joueurs, officiels, arbitres) ──

                # 3. Joueurs
                joueurs_a, joueurs_b = self._parse_joueurs(tidx)
                fields_count += len(joueurs_a) + len(joueurs_b)

                # 4. Libéros
                liberos_a, liberos_b = self._parse_liberos(words)
                self._mark_liberos(joueurs_a, liberos_a)
                self._mark_liberos(joueurs_b, liberos_b)

                # 5. Officiels d'équipe
                off_a, off_b = self._parse_officiels(words)

                # 6. Capitaines (3 méthodes, fallback successif)
                cap_a, cap_b = self._detect_capitaines(images, chars, words)
                if not cap_a or not cap_b:
                    cap_a2, cap_b2 = self._capitaines_from_signatures(tidx)
                    cap_a = cap_a or cap_a2
                    cap_b = cap_b or cap_b2
                if not cap_a or not cap_b:
                    cap_a3, cap_b3 = self._capitaines_from_chars(chars, words)
                    cap_a = cap_a or cap_a3
                    cap_b = cap_b or cap_b3
                self._mark_capitaine(joueurs_a, cap_a)
                self._mark_capitaine(joueurs_b, cap_b)

                # 7. Arbitres
                arbitres = self._parse_arbitres(tidx, full_text)
                fields_count += len(arbitres)

                # ── Phase 3 : Résultats & détection match joué ──

                # 8. Résultat global (vainqueur, score, durée)
                resultat = self._parse_resultat(lines, tidx)
                fields_count += sum(1 for v in resultat.values() if v)

                match_joue = self._is_match_played(resultat)
                has_detailed_score = self._has_detailed_scores(resultat)
                saison_str = header.get("saison")
                saison_year = self._saison_year(saison_str)
                # Avant 2024-2025, les feuilles n'ont pas de détails de sets
                is_modern = saison_year is not None and saison_year >= 2024

                # 9. Table RESULTATS (scores par set)
                res_data, duree_from_table = self._parse_resultats_table(tidx)
                if duree_from_table and not resultat.get("duree_totale"):
                    resultat["duree_totale"] = duree_from_table

                # Déterminer si des détails de sets sont renseignés
                has_set_scores = any(
                    (r.get('points_a') or 0) > 0 or (r.get('points_b') or 0) > 0
                    for r in res_data
                )

                # ── Phase 4 : Détails des sets (coûteux, sauté si inutile) ──
                # On parse les sections SET uniquement si la feuille contient
                # des données réelles (score non nul ou points par set).
                sets_detailed: list[dict] = []
                if has_detailed_score or has_set_scores:
                    sets_detailed = self._parse_all_sets(tidx)
                else:
                    logger.debug(
                        "Pas de données de sets détaillées – parsing des "
                        "sections SET ignoré : %s", pdf_path.name,
                    )

                # 10. Construire les Sets
                sets, set_warnings = self._build_sets(
                    sets_detailed, res_data, resultat,
                    equipes_info.get("equipe_a", ""),
                    equipes_info.get("equipe_b", ""),
                )
                for w in set_warnings:
                    result.add_warning(w)
                fields_count += len(sets) * 5

                # ── Phase 5 : Sanctions, remarques ──

                # 11. Sanctions
                sanctions, sanc_warnings = self._parse_sanctions(tidx)
                for w in sanc_warnings:
                    result.add_warning(w)

                # 12. Remarques / Demande non fondée
                remarques = self._parse_remarques(tidx)
                demande_nf = self._parse_demande_non_fondee(tidx)

                # ── Phase 6 : Construction du Match ──

                match = self._build_match(
                    header=header,
                    equipes_info=equipes_info,
                    resultat=resultat,
                    joueurs_a=joueurs_a, joueurs_b=joueurs_b,
                    liberos_a=liberos_a, liberos_b=liberos_b,
                    off_a=off_a, off_b=off_b,
                    sets=sets,
                    arbitres=arbitres,
                    sanctions=sanctions,
                    remarques=remarques,
                    demande_nf=demande_nf,
                    pdf_path=pdf_path,
                    match_joue=match_joue,
                )

                result.success = True
                result.match = match
                result.fields_extracted = min(fields_count, 40)
                result.fields_total = 40

                # ── Warnings contextuels ──
                if not match_joue:
                    result.add_warning("Match non joué ou annulé (aucun vainqueur)")
                elif match_joue and not has_detailed_score and is_modern:
                    # Saison >= 2024 : on s'attend à des scores détaillés
                    result.add_warning(
                        "Match joué mais scores de sets absents "
                        "(attendus pour saison >= 2024-2025)"
                    )

                result.warnings.extend(self._validate(match, is_modern=is_modern))

        except Exception as e:
            result.add_error(f"Erreur de parsing: {e}")
            import traceback
            result.add_error(traceback.format_exc())
        finally:
            result.parse_time_ms = (time.time() - start) * 1000
            self._record_result(result)

        return result

    # =====================================================================
    # Identification des tables
    # =====================================================================

    def _identify_tables(self, tables: list) -> dict:
        """Identifie les 5 tables du PDF FFVB par contenu."""
        idx = {
            'main': None, 'secondary': None,
            'players': None, 'results': None, 'signatures': None,
        }

        for table in tables:
            if not table or len(table) < 2:
                continue
            sample = ' '.join(
                str(c) for row in table[:4] if row for c in row if c
            )
            if 'RESULTATS' in sample:
                idx['results'] = table
            elif 'Nom Prénom' in sample and 'Licence' in sample:
                idx['players'] = table
            elif 'SIGNATURES' in sample:
                idx['signatures'] = table

        remaining = [
            t for t in tables
            if t and t not in (idx['results'], idx['players'], idx['signatures'])
        ]
        remaining.sort(
            key=lambda t: len(t) * max((len(r) for r in t if r), default=0),
            reverse=True,
        )
        if remaining:
            idx['main'] = remaining[0]
        if len(remaining) >= 2:
            idx['secondary'] = remaining[1]

        return idx

    # =====================================================================
    # Header – parsing basé sur les lignes
    # =====================================================================

    def _parse_header(self, lines: list[str]) -> dict:
        """Parse le header depuis les premières lignes du texte.

        Lignes typiques :
          [0] "EMA - ELITE MASCULINE - POULE A Match: EMA001 - Jour: 01"
          [1] "Ville: SAINT MARTIN D'HÈRES Samedi 20 Septembre 2025 à 20h30"
          [2] "Salle: CSU - GRAND GYMNASE SENIOR | MASCULIN"
          [3] "Compétitions Nationales SENIORS GRENOBLE V.UNIVERSITE CLUB GPSO ACBB"
        """
        header: dict = {
            "competition": None, "code_match": None, "journee": None,
            "date": None, "date_obj": None, "heure": None, "heure_obj": None,
            "lieu": None, "salle": None, "genre": None, "categorie": None,
            "saison": None, "ligue": None, "organisation": None,
        }

        for line in lines[:8]:
            line = line.strip()

            # Match code & journée (can appear on any of the first lines)
            if 'Match:' in line:
                if m := re.search(r'Match:\s*(\w+)', line):
                    header["code_match"] = m.group(1)
                if m := re.search(r'Jour:\s*(\d+)', line):
                    header["journee"] = m.group(1)
                # Competition = everything before "Match:"
                comp_part = line.split('Match:')[0].strip().rstrip('-').strip()
                if comp_part:
                    header["competition"] = comp_part

            # Ville & Date & Heure
            if 'Ville:' in line:
                header.update(self._parse_ville_date_line(line))

            # Salle & Genre/Catégorie
            if 'Salle:' in line:
                header.update(self._parse_salle_line(line))

            # Organisation / Ligue
            if 'Compétitions' in line:
                header["organisation"] = "Compétitions Nationales"
            if m := re.search(r'Ligue\s+(\w[\w\s-]*?)(?:\s+Match:|\s*$)', line):
                ligue_name = m.group(1).strip()
                if len(ligue_name) > 1:
                    header["ligue"] = f"Ligue {ligue_name}"
                    header["organisation"] = f"Ligue {ligue_name}"

        # Saison depuis la date
        if d := header.get("date_obj"):
            header["saison"] = (
                f"{d.year}-{d.year + 1}" if d.month >= 8
                else f"{d.year - 1}-{d.year}"
            )

        return header

    def _parse_ville_date_line(self, line: str) -> dict:
        """Parse une ligne de type :
        'Ville: SAINT MARTIN D'HÈRES Samedi 20 Septembre 2025 à 20h30'
        """
        info: dict = {}

        # Extraire la ville : entre "Ville:" et le jour de la semaine
        if m := re.search(
            r'Ville:\s*(.+?)\s+(?:' + '|'.join(JOURS_SEMAINE) + r')\s',
            line,
        ):
            info["lieu"] = m.group(1).strip()

        # Date
        if dm := re.search(
            r'(' + '|'.join(JOURS_SEMAINE) + r')\s+(\d{1,2})\s+(\w+)\s+(\d{4})',
            line,
        ):
            jour_sem, jour_s, mois_s, annee_s = dm.groups()
            jour = int(jour_s)
            annee = int(annee_s)
            info["date"] = f"{jour_sem} {jour} {mois_s.capitalize()} {annee}"
            mois_num = MOIS_MAP.get(mois_s.lower(), 1)
            try:
                info["date_obj"] = dt_date(annee, mois_num, jour)
            except ValueError:
                pass

        # Heure
        if hm := re.search(r'à\s+(\d{1,2})h(\d{2})', line):
            h, mn = int(hm.group(1)), int(hm.group(2))
            info["heure"] = f"{h}h{mn:02d}"
            try:
                info["heure_obj"] = dt_time(h, mn)
            except ValueError:
                pass

        return info

    def _parse_salle_line(self, line: str) -> dict:
        """Parse une ligne de type :
        'Salle: CSU - GRAND GYMNASE SENIOR | MASCULIN'
        """
        info: dict = {}

        # Salle : entre "Salle:" et SENIOR/MASCULIN/FÉMININ/MIXTE ou fin
        if m := re.search(
            r'Salle:\s*(.+?)(?:\s+(?:SENIOR|MASCULIN|FÉMININ|FEMININ|MIXTE|M\d{2}|U\d{2})|\s*$)',
            line,
        ):
            info["salle"] = m.group(1).strip()

        # Genre
        upper = line.upper()
        if 'MASCULIN' in upper:
            info["genre"] = "MASCULIN"
        elif 'FÉMININ' in upper or 'FEMININ' in upper:
            info["genre"] = "FEMININ"
        elif 'MIXTE' in upper:
            info["genre"] = "MIXTE"

        # Catégorie
        if 'SENIOR' in upper:
            info["categorie"] = "SENIOR"
        elif cm := re.search(r'\b(M\d{2}|U\d{2})\b', upper):
            info["categorie"] = cm.group(1)

        return info

    # =====================================================================
    # Noms d'équipe
    # =====================================================================

    def _parse_equipes(self, tidx: dict, words: list, lines: list[str]) -> dict:
        """Extrait les noms d'équipe depuis la table joueurs ou le header."""
        eq = {"equipe_a": None, "equipe_b": None}

        # Méthode 1 : Table joueurs (row 0)
        tbl = tidx.get('players')
        if tbl and tbl[0]:
            row0 = tbl[0]
            # Typically 6 columns: [TeamA, None, None, TeamB, None, None]
            names = []
            for cell in row0:
                if cell:
                    cs = str(cell).strip()
                    if len(cs) > 3 and not any(
                        kw in cs for kw in ['N°', 'Nom', 'Licence', 'LIBEROS']
                    ):
                        names.append(cs)
            if len(names) >= 2:
                eq["equipe_a"] = names[0]
                eq["equipe_b"] = names[1]
            elif len(names) == 1:
                eq["equipe_a"] = names[0]

        # Méthode 2 : Ligne "Compétitions Nationales SENIORS {Team A} {Team B}"
        # Difficile à parser car pas de délimiteur entre les noms d'équipe
        # On utilise la table joueurs comme source primaire

        # Nettoyage des noms d'équipe
        for key in ("equipe_a", "equipe_b"):
            if eq[key]:
                # Supprimer un caractère isolé en début de nom (artefact
                # de cellule adjacente, ex: "L ISSY..." → "ISSY...")
                eq[key] = re.sub(
                    r'^[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ]\s+(?=[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ])',
                    '', eq[key],
                )
                eq[key] = self._clean_team_name(eq[key])

        # Méthode 3 fallback : mots positionnels dans la bande 55-80px
        if not eq["equipe_a"] or not eq["equipe_b"]:
            team_words = sorted(
                [w for w in words if 55 <= w['top'] <= 80],
                key=lambda w: w['x0'],
            )
            if team_words:
                max_x = max(w['x1'] for w in words)
                mid = max_x / 2
                left = ' '.join(w['text'] for w in team_words if w['x0'] < mid)
                right = ' '.join(w['text'] for w in team_words if w['x0'] >= mid)
                if left and not eq["equipe_a"]:
                    eq["equipe_a"] = self._clean_team_name(left.strip())
                if right and not eq["equipe_b"]:
                    eq["equipe_b"] = self._clean_team_name(right.strip())

        return eq

    @staticmethod
    def _clean_team_name(name: str) -> str:
        """Nettoie un nom d'équipe en supprimant les artefacts de parsing."""
        # Supprimer les espaces multiples
        name = re.sub(r'\s+', ' ', name).strip()
        # Supprimer une seule lettre isolée en fin de nom (troncature PDF)
        # Ex: "VOLLEY CLUB HYERES/PIERREFEU L" → "VOLLEY CLUB HYERES/PIERREFEU"
        # Mais garder "VB", "AS", etc. (2+ chars = acronyme légitime)
        name = re.sub(r'\s+[A-Z]$', '', name)
        return name.strip()

    @staticmethod
    def _extract_club_info(team_name: str) -> tuple[str, Optional[int]]:
        """Extrait le nom du club et le numéro d'équipe depuis le nom d'équipe.

        Les noms d'équipe FFVB suivent le pattern :
          "NOM DU CLUB"  ou  "NOM DU CLUB 2"  (numéro d'équipe en fin)

        Exemples :
          "GRENOBLE V.UNIVERSITE CLUB" → ("GRENOBLE V.UNIVERSITE CLUB", None)
          "PARIS UC 2" → ("PARIS UC", 2)
          "NANTES REZE METROPOLE VB 3" → ("NANTES REZE METROPOLE VB", 3)
          "AS CANNES VB" → ("AS CANNES VB", None)
          "STADE POITEVIN VB" → ("STADE POITEVIN VB", None)

        Returns:
            Tuple (club_name, team_number) – team_number is None if no suffix.
        """
        if not team_name:
            return team_name, None

        name = team_name.strip()

        # Chercher un numéro d'équipe en fin de nom : " 2", " 3", etc.
        # On ne touche pas à " 1" car les équipes premières ne portent généralement pas de numéro
        m = re.match(r'^(.+?)\s+(\d)$', name)
        if m:
            club_name = m.group(1).strip()
            num = int(m.group(2))
            return club_name, num

        return name, None

    # =====================================================================
    # Résultat global
    # =====================================================================

    def _parse_resultat(self, lines: list[str], tidx: dict) -> dict:
        result = {"vainqueur": None, "score_final": None, "duree_totale": None}

        # Chercher dans le texte
        full_text = '\n'.join(lines)
        if vm := re.search(
            r'Vainqueur:\s*'
            r'([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ0-9][A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ0-9\s\-\'\.\/\(\)]+?)'
            r'\s+(\d)/(\d)',
            full_text,
        ):
            result["vainqueur"] = self._normalize_name(vm.group(1).strip())
            result["score_final"] = f"{vm.group(2)}/{vm.group(3)}"
        else:
            if v2 := re.search(
                r'Vainqueur:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ0-9][^\n]*)',
                full_text,
            ):
                raw = v2.group(1).strip()
                if sm := re.search(r'(\d)/(\d)\s*$', raw):
                    result["score_final"] = f"{sm.group(1)}/{sm.group(2)}"
                    result["vainqueur"] = self._normalize_name(raw[:sm.start()].strip())
                elif len(raw) > 3:
                    result["vainqueur"] = self._normalize_name(raw)

        # Aussi chercher dans la table RESULTATS (dernière ligne)
        tbl = tidx.get('results')
        if tbl and not result["vainqueur"]:
            for row in reversed(tbl):
                if not row:
                    continue
                rt = ' '.join(str(c) for c in row if c)
                if 'Vainqueur' in rt:
                    if vm := re.search(
                        r'Vainqueur:\s*(.+?)\s+(\d)/(\d)',
                        rt,
                    ):
                        result["vainqueur"] = self._normalize_name(vm.group(1).strip())
                        result["score_final"] = f"{vm.group(2)}/{vm.group(3)}"
                    break

        # Nettoyer les noms tronqués (supprimer une lettre isolée en fin)
        if result["vainqueur"]:
            result["vainqueur"] = self._clean_team_name(result["vainqueur"])

        # Durée
        if dm := re.search(r'Durée\s*(\d+h\d+)', full_text):
            result["duree_totale"] = dm.group(1)
        elif dm := re.search(r"Durée.*?(\d+)'", full_text):
            result["duree_totale"] = dm.group(1) + "'"

        return result

    @staticmethod
    def _is_match_played(resultat: dict) -> bool:
        """Un match est considéré comme joué dès qu'un vainqueur est renseigné.

        Avant 2024-2025, les feuilles n'ont pas de score détaillé (souvent
        0/0) mais le vainqueur apparaît quand même → match joué.
        """
        return bool(resultat.get("vainqueur"))

    @staticmethod
    def _has_detailed_scores(resultat: dict) -> bool:
        """True si la feuille contient un score de sets non nul (ex: 3/1)."""
        sf = resultat.get("score_final", "0/0")
        if not sf:
            return False
        try:
            a, b = sf.split("/")
            return int(a) + int(b) > 0
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _saison_year(saison: Optional[str]) -> Optional[int]:
        """Extrait l'année de début d'une saison ('2024-2025' → 2024)."""
        if not saison:
            return None
        try:
            return int(saison.split("-")[0])
        except (ValueError, IndexError):
            return None

    # =====================================================================
    # Joueurs (table roster)
    # =====================================================================

    def _parse_joueurs(self, tidx: dict) -> tuple[list[Joueur], list[Joueur]]:
        """Parse les joueurs depuis la table dédiée.

        Structure typique :
          Row 0: [Team A name, None, None, Team B name, None, None]
          Row 1: [N°, Nom Prénom, Licence, N°, Nom Prénom, Licence]
          Row 2: [multiline player data, ...]
          Row 3: [LIBEROS, ...]
        """
        joueurs_a: list[Joueur] = []
        joueurs_b: list[Joueur] = []

        tbl = tidx.get('players')
        if not tbl:
            return joueurs_a, joueurs_b

        # Pattern : "NN NOM PRENOM LICENCE" where NN=1-2 digits, LICENCE=6-7 digits
        pat = re.compile(
            r'^(\d{1,2})\s+'
            r'([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ\-\' ]+?)\s+'
            r'(\d{6,7})$'
        )

        for row in tbl:
            if not row:
                continue
            row_text = ' '.join(str(c) for c in row if c)
            if any(kw in row_text for kw in [
                'Nom Prénom', 'Licence', 'LIBEROS', 'OFFICIELS', 'N°',
            ]):
                continue

            mid = len(row) // 2

            for cell_idx, cell in enumerate(row):
                if not cell:
                    continue
                cs = str(cell).strip()
                if not cs:
                    continue

                for line in cs.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    m = pat.match(line)
                    if m:
                        numero = m.group(1)
                        nom_prenom = m.group(2).strip()
                        licence = m.group(3)

                        nom, prenom = self._split_nom_prenom(nom_prenom)

                        joueur = Joueur(
                            numero=numero,
                            nom=nom,
                            prenom=prenom,
                            licence=licence,
                        )
                        if cell_idx < mid:
                            joueurs_a.append(joueur)
                        else:
                            joueurs_b.append(joueur)

        return joueurs_a, joueurs_b

    @staticmethod
    def _split_nom_prenom(nom_prenom: str) -> tuple[str, str]:
        """Sépare intelligemment le nom et le prénom.

        Heuristique : le nom de famille est composé des mots qui sont
        entièrement en majuscules, le prénom des mots qui suivent et qui
        ont des minuscules ou sont en title case.

        Exemples :
          "HUMBERT RIDET DYLAN" → ("HUMBERT RIDET", "DYLAN")
          "THE OWONA IVAN" → ("THE OWONA", "IVAN")
          "CHONÉ TANGUY" → ("CHONÉ", "TANGUY")
          "VAN DEN ESHOF DAMIEN" → ("VAN DEN ESHOF", "DAMIEN")
          "LE GARS PAUL" → ("LE GARS", "PAUL")
        """
        parts = nom_prenom.split()
        if len(parts) <= 1:
            return nom_prenom, "Inconnu"

        # Dans les PDFs FFVB, tout est en majuscules.
        # Convention : le dernier "mot" (ou les derniers mots) est le prénom.
        # On considère que le prénom est le(s) dernier(s) mot(s) après le nom.
        # Heuristique simple : le nom est tout sauf le dernier mot.
        # Pour les prénoms composés (ex: "JEAN PIERRE"), c'est ambiguë,
        # mais en pratique les prénoms composés sont rares dans les PDFs FFVB
        # et le format est NOM PRENOM (un seul prénom en général).

        # Meilleure heuristique pour tout-en-majuscules :
        # Prendre le dernier mot comme prénom, le reste comme nom.
        nom = ' '.join(parts[:-1])
        prenom = parts[-1]
        return nom, prenom

    # =====================================================================
    # Libéros (positionnement spatial)
    # =====================================================================

    def _parse_liberos(self, words: list) -> tuple[list[Joueur], list[Joueur]]:
        """Extrait les libéros depuis la section LIBEROS du PDF."""
        liberos_a: list[Joueur] = []
        liberos_b: list[Joueur] = []

        lib_header = next(
            (w for w in words if w['text'].upper() == 'LIBEROS' and w['x0'] > 500),
            None,
        )
        if not lib_header:
            return liberos_a, liberos_b

        off_header = next(
            (w for w in words if w['text'].upper() == 'OFFICIELS' and w['x0'] > 500),
            None,
        )
        y_start = lib_header['bottom']
        y_end = off_header['top'] if off_header else y_start + 35

        zone_words = [
            w for w in words
            if y_start - 2 <= w['top'] <= y_end and w['x0'] > 500
        ]
        zone_words.sort(key=lambda w: (w['top'], w['x0']))

        # Séparation gauche/droite par x
        x_thresh = 700
        lines_a: dict[int, list] = defaultdict(list)
        lines_b: dict[int, list] = defaultdict(list)
        for w in zone_words:
            key = round(w['top'] / 3) * 3
            if w['x0'] < x_thresh:
                lines_a[key].append(w)
            else:
                lines_b[key].append(w)

        def _build_joueur(line_words: list) -> Optional[Joueur]:
            if not line_words:
                return None
            texts = [w['text'] for w in sorted(line_words, key=lambda w: w['x0'])]
            numero, licence = None, None
            name_parts = []
            for t in texts:
                t = t.strip()
                if not t:
                    continue
                if t.isdigit() and len(t) <= 2 and numero is None:
                    numero = t
                elif t.isdigit() and len(t) >= 6:
                    licence = t
                elif t.upper() not in ('LIBEROS',):
                    name_parts.append(t)
            if not numero or not licence or not name_parts:
                return None
            nom, prenom = self._split_nom_prenom(' '.join(name_parts))
            return Joueur(
                numero=numero, nom=nom, prenom=prenom,
                licence=licence, est_libero=True,
            )

        for key in sorted(lines_a):
            if j := _build_joueur(lines_a[key]):
                liberos_a.append(j)
        for key in sorted(lines_b):
            if j := _build_joueur(lines_b[key]):
                liberos_b.append(j)

        return liberos_a, liberos_b

    @staticmethod
    def _mark_liberos(joueurs: list[Joueur], liberos: list[Joueur]) -> None:
        lib_ids = {(lib.numero, lib.licence) for lib in liberos}
        lib_nums = {lib.numero for lib in liberos}
        for j in joueurs:
            if (j.numero, j.licence) in lib_ids or j.numero in lib_nums:
                j.est_libero = True

    # =====================================================================
    # Officiels d'équipe (positionnement spatial)
    # =====================================================================

    def _parse_officiels(self, words: list) -> tuple[list[Officiel], list[Officiel]]:
        """Extrait les officiels d'équipe sous la section OFFICIELS."""
        off_a: list[Officiel] = []
        off_b: list[Officiel] = []

        header = next(
            (w for w in words if w['text'].upper() == 'OFFICIELS' and w['x0'] > 500),
            None,
        )
        if not header:
            return off_a, off_b

        y_start = header['bottom'] - 2
        sig = next(
            (w for w in words
             if w['text'].upper() in ('SIGNATURES', 'Capitaine')
             and w['x0'] > 500),
            None,
        )
        y_end = sig['top'] if sig else y_start + 50

        # Zone : x > 570 pour exclure les colonnes RESULTATS
        zone_words = [
            w for w in words
            if y_start <= w['top'] <= y_end and w['x0'] > 570
        ]
        zone_words.sort(key=lambda w: (w['top'], w['x0']))

        x_thresh = 700
        lines_left: dict[int, list] = defaultdict(list)
        lines_right: dict[int, list] = defaultdict(list)
        for w in zone_words:
            key = round(w['top'] / 3) * 3
            if w['x0'] < x_thresh:
                lines_left[key].append(w)
            else:
                lines_right[key].append(w)

        def _build_off(line_words: list) -> Optional[Officiel]:
            if not line_words:
                return None
            texts = [w['text'] for w in sorted(line_words, key=lambda w: w['x0'])]
            role, licence = None, None
            name_parts = []
            for t in texts:
                tc = t.strip()
                if not tc:
                    continue
                if tc.upper() in ('EA', 'EB', 'MA', 'MB', 'KA', 'KB'):
                    role = tc.upper()
                elif tc.isdigit() and len(tc) >= 4:
                    licence = tc
                elif tc.upper() not in ('OFFICIELS', 'SIGNATURES'):
                    name_parts.append(tc)
            if not role or not name_parts:
                return None
            nom, prenom = MatchSheetParserV5._split_nom_prenom(' '.join(name_parts))
            return Officiel(
                role=role, nom=nom, prenom=prenom, licence=licence,
            )

        for key in sorted(lines_left):
            if o := _build_off(lines_left[key]):
                off_a.append(o)
        for key in sorted(lines_right):
            if o := _build_off(lines_right[key]):
                off_b.append(o)

        return off_a, off_b

    # =====================================================================
    # Capitaines
    # =====================================================================

    def _detect_capitaines(
        self, images: list, chars: list, words: list,
    ) -> tuple[Optional[str], Optional[str]]:
        """Détecte les capitaines via les cercles-images dans le roster.

        Le cercle-image encadre le numéro du capitaine, mais il est souvent
        positionné entre deux lignes de joueurs. On regroupe les chiffres
        proches par ligne (Y), puis on sélectionne la ligne la plus proche
        du centre vertical du cercle.
        """
        cap_a: Optional[str] = None
        cap_b: Optional[str] = None

        # Bornes Y du roster
        n_headers = [w for w in words if w['text'] == 'N°' and w['x0'] > 500]
        roster_y_start = min(w['top'] for w in n_headers) if n_headers else 270
        lib_headers = [
            w for w in words
            if w['text'].upper() == 'LIBEROS' and w['x0'] > 500
        ]
        roster_y_end = min(w['top'] for w in lib_headers) if lib_headers else 400

        # Cercles-images marquant le capitaine (critères élargis pour robustesse)
        captain_imgs = [
            img for img in images
            if img['x0'] > 550
            and roster_y_start - 5 < img['top'] < roster_y_end + 5
            and 5 < img['x1'] - img['x0'] < 22
            and 5 < img['bottom'] - img['top'] < 22
        ]

        x_split = 680
        for img in captain_imgs:
            side = 'A' if img['x0'] < x_split else 'B'
            img_center_y = (img['top'] + img['bottom']) / 2

            # Le cercle encadre le numéro du capitaine : les chiffres sont
            # à l'intérieur des bornes X de l'image (avec petite tolérance).
            # On utilise une tolérance serrée en X pour éviter de capter
            # les chiffres de licence de la colonne adjacente.
            nearby_digits = [
                c for c in chars
                if abs(c['top'] - img_center_y) < 12
                and c['text'].isdigit()
                and img['x0'] - 3 < c['x0'] < img['x1'] + 3
            ]

            if not nearby_digits:
                continue

            # Grouper par ligne Y (tolérance 3px)
            rows: dict[int, list] = defaultdict(list)
            for c in nearby_digits:
                row_key = round(c['top'] / 3) * 3
                rows[row_key].append(c)

            # Sélectionner la ligne la plus proche du centre du cercle
            best_key = min(rows.keys(), key=lambda k: abs(k - img_center_y))
            best_row = sorted(rows[best_key], key=lambda c: c['x0'])

            num = ''.join(c['text'] for c in best_row[:2])
            if num:
                if side == 'A' and not cap_a:
                    cap_a = num
                elif side == 'B' and not cap_b:
                    cap_b = num

        return cap_a, cap_b

    def _capitaines_from_signatures(self, tidx: dict) -> tuple[Optional[str], Optional[str]]:
        """Fallback : parse les capitaines depuis SIGNATURES."""
        cap_a, cap_b = None, None
        tbl = tidx.get('signatures')
        if not tbl:
            return cap_a, cap_b

        for i, row in enumerate(tbl):
            if not row:
                continue
            rt = ' '.join(str(c) for c in row if c)
            if 'Capitaine' not in rt:
                continue

            parts = re.findall(r'Capitaine\s+N°\s*(\d{1,2})', rt)
            if len(parts) >= 2:
                cap_a, cap_b = parts[0], parts[1]
            elif len(parts) == 1:
                cap_a = parts[0]

            # Ligne suivante peut contenir les numéros
            if i + 1 < len(tbl) and tbl[i + 1]:
                nr = tbl[i + 1]
                mid = len(nr) // 2
                for j, cell in enumerate(nr):
                    if cell:
                        cs = str(cell).strip()
                        if cs.isdigit() and len(cs) <= 2:
                            if j < mid and not cap_a:
                                cap_a = cs
                            elif j >= mid and not cap_b:
                                cap_b = cs

        return cap_a, cap_b

    def _capitaines_from_chars(
        self, chars: list, words: list,
    ) -> tuple[Optional[str], Optional[str]]:
        """Fallback 3 : détecte les capitaines via des marqueurs 'C' ou '©'
        dans la zone du roster (caractères spéciaux utilisés dans certains PDFs).
        """
        cap_a: Optional[str] = None
        cap_b: Optional[str] = None

        # Bornes Y du roster
        n_headers = [w for w in words if w['text'] == 'N°' and w['x0'] > 500]
        roster_y_start = min(w['top'] for w in n_headers) if n_headers else 270
        lib_headers = [
            w for w in words
            if w['text'].upper() == 'LIBEROS' and w['x0'] > 500
        ]
        roster_y_end = min(w['top'] for w in lib_headers) if lib_headers else 400

        # Chercher les caractères marqueurs de capitaine dans la zone roster
        # Marqueurs possibles : 'C', '©', 'Ⓒ', '✪', '★'
        captain_markers = {'C', '©', 'Ⓒ', '✪', '★'}
        marker_chars = [
            c for c in chars
            if c['text'] in captain_markers
            and c['x0'] > 550
            and roster_y_start - 5 < c['top'] < roster_y_end + 5
        ]

        x_split = 680
        for mc in marker_chars:
            side = 'A' if mc['x0'] < x_split else 'B'
            # Chercher les chiffres proches du marqueur (même ligne)
            digit_chars = sorted(
                [c for c in chars
                 if abs(c['top'] - mc['top']) < 6
                 and c['text'].isdigit()
                 and mc['x0'] - 20 < c['x0'] < mc['x0'] + 20
                 and c is not mc],
                key=lambda c: c['x0'],
            )
            num = ''.join(c['text'] for c in digit_chars[:2])
            if num:
                if side == 'A' and not cap_a:
                    cap_a = num
                elif side == 'B' and not cap_b:
                    cap_b = num

        return cap_a, cap_b

    @staticmethod
    def _mark_capitaine(joueurs: list[Joueur], cap_num: Optional[str]) -> None:
        if not cap_num:
            return
        for j in joueurs:
            if j.numero == cap_num or j.numero == cap_num.lstrip('0'):
                j.est_capitaine = True
                break

    # =====================================================================
    # Parsing détaillé des sets
    # =====================================================================

    def _parse_all_sets(self, tidx: dict) -> list[dict]:
        """Parse tous les sets depuis les tables main et secondary.

        Architecture FFVB :
            - Table main  : Sets 1, 3, 5  (positions ~0, ~10, ~20)
            - Table secondary : Sets 2, 4  (positions ~0, ~10)

        Certains vieux PDFs (pré-2024) ont un bug d'extraction où le chiffre
        '5' est lu comme '1' par pdfplumber.  On corrige via la position
        ordinale dans chaque table.
        """
        EXPECTED_MAIN = {0: 1, 1: 3, 2: 5}       # ordinal → set number
        EXPECTED_SEC  = {0: 2, 1: 4}

        sets = []
        for key, expected_map in [('main', EXPECTED_MAIN), ('secondary', EXPECTED_SEC)]:
            tbl = tidx.get(key)
            if not tbl:
                continue
            sections = self._find_set_sections(tbl)
            # Sort by start row to get ordinal position
            sections.sort(key=lambda x: x[1])
            for ordinal, (raw_num, start_row) in enumerate(sections):
                # Use expected number from position if available, otherwise
                # trust the raw extraction.
                set_num = expected_map.get(ordinal, raw_num)
                if raw_num != set_num:
                    logger.debug(
                        "SET number corrected: raw=%d → expected=%d "
                        "(table=%s, ordinal=%d, row=%d)",
                        raw_num, set_num, key, ordinal, start_row,
                    )
                sd = self._parse_set_section(tbl, start_row, set_num)
                if sd:
                    sets.append(sd)
        sets.sort(key=lambda s: s['numero'])
        return sets

    @staticmethod
    def _find_set_sections(table: list) -> list[tuple[int, int]]:
        pat = re.compile(r'S\s*E\s*T\s*(\d)')
        sections = []
        for i, row in enumerate(table):
            if not row:
                continue
            for cell in row:
                if not cell:
                    continue
                cs = str(cell).replace('\n', ' ').strip()
                if m := pat.search(cs):
                    sections.append((int(m.group(1)), i))
                    break
        return sections

    def _parse_set_section(self, table: list, start: int, set_num: int) -> Optional[dict]:
        """Parse une section de set (10 lignes dans la table).

        Rows :
          +0 : Header (noms d'équipe, heures, service S/R)
          +1 : Positions (I II III IV V VI)
          +2 : Formation de départ (numéros)
          +3 : Remplaçants (Joueur N°)
          +4 : Score au remplacement
          +5 : Score supplémentaire
          +6-9 : Tours au service + Timeouts
        """
        sd = {
            'numero': set_num,
            'heure_debut': None, 'heure_fin': None,
            'service_initial_side': None,
            'left_team_name': None, 'right_team_name': None,
            'formation_left': None, 'formation_right': None,
            'changements_left': [], 'changements_right': [],
            'timeouts_left': [], 'timeouts_right': [],
            'services_left': {}, 'services_right': {},
        }

        if start + ROWS_PER_SET > len(table):
            return sd

        n_cols = len(table[start]) if table[start] else 0

        # Row +0 : Header
        self._parse_set_header(table[start], sd, n_cols)

        # Row +1 : Position columns
        pos_left, pos_right = self._find_position_columns(table[start + 1], n_cols)

        # Row +2 : Formations
        sd['formation_left'] = self._extract_formation(table[start + 2], pos_left)
        sd['formation_right'] = self._extract_formation(table[start + 2], pos_right)

        # Rows +3..+5 : Substitutions
        self._parse_substitutions(table, start, pos_left, pos_right, sd)

        # Rows +6..+9 : Service & timeouts
        self._parse_service_timeouts(table, start, pos_left, pos_right, sd, n_cols)

        return sd

    def _parse_set_header(self, row: list, sd: dict, n_cols: int) -> None:
        """Parse le header du set pour extraire heures, noms, service."""
        if not row:
            return

        time_pat = re.compile(r'(Début|Fin):\s*(\d{1,2}:\d{2})')
        time_partial = re.compile(r'(Début|Fin):\s*(\d{1,2}):?')
        mid = n_cols // 2

        for i, cell in enumerate(row):
            if not cell:
                continue
            cs = str(cell).strip()
            if len(cs) < 5 or ('Début' not in cs and 'Fin' not in cs):
                continue

            side = 'left' if i < mid else 'right'

            # Nom d'équipe (avant "Début" ou "Fin")
            name = re.split(r'\s+(?:Début|Fin):', cs)[0].strip()
            if name:
                if side == 'left':
                    sd['left_team_name'] = name
                else:
                    sd['right_team_name'] = name

            # Heure complète
            if tm := time_pat.search(cs):
                if tm.group(1) == 'Début':
                    sd['heure_debut'] = tm.group(2)
                else:
                    sd['heure_fin'] = tm.group(2)
            elif tp := time_partial.search(cs):
                partial = tp.group(2).rstrip(':')
                completed = self._complete_time(row, i, partial)
                if completed:
                    if tp.group(1) == 'Début':
                        sd['heure_debut'] = completed
                    else:
                        sd['heure_fin'] = completed

            # Service
            stripped = cs.rstrip()
            if stripped.endswith(' S'):
                sd['service_initial_side'] = side
            elif stripped.endswith(' R'):
                sd['service_initial_side'] = 'right' if side == 'left' else 'left'

    @staticmethod
    def _complete_time(row: list, col_i: int, partial: str) -> Optional[str]:
        for off in range(1, 4):
            j = col_i + off
            if j < len(row) and row[j]:
                cs = str(row[j]).strip()
                if m := re.match(r'^(\d{1,2})\b', cs):
                    return f"{partial}:{m.group(1).zfill(2)}"
        return None

    def _find_position_columns(
        self, header_row: Optional[list], n_cols: int,
    ) -> tuple[list[int], list[int]]:
        """Trouve les colonnes I..VI pour gauche et droite."""
        if not header_row:
            return [], []

        roman_map = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6}
        hits: list[tuple[int, int]] = []
        for i, cell in enumerate(header_row):
            if cell and str(cell).strip() in roman_map:
                hits.append((i, roman_map[str(cell).strip()]))

        if len(hits) >= 12:
            hits.sort(key=lambda x: x[0])
            # Trouver le plus grand gap pour séparer gauche/droite
            max_gap, split_idx = 0, 5
            for k in range(len(hits) - 1):
                gap = hits[k + 1][0] - hits[k][0]
                if gap > max_gap:
                    max_gap, split_idx = gap, k

            left = sorted(hits[:split_idx + 1], key=lambda x: x[1])
            right = sorted(hits[split_idx + 1:], key=lambda x: x[1])
            return [i for i, _ in left[:6]], [i for i, _ in right[:6]]

        # Fallback heuristique selon la taille de la table
        if n_cols >= 40:
            return [13, 15, 18, 20, 22, 24], [31, 33, 35, 37, 39, 41]
        elif n_cols >= 25:
            return [1, 3, 5, 7, 9, 11], [14, 16, 18, 20, 22, 24]
        return [], []

    @staticmethod
    def _extract_formation(row: Optional[list], cols: list[int]) -> Optional[Formation]:
        if not row or len(cols) < 6:
            return None
        vals: list[Optional[str]] = []
        for c in cols:
            if c < len(row) and row[c]:
                v = str(row[c]).strip()
                vals.append(v if v.isdigit() and len(v) <= 2 else None)
            else:
                vals.append(None)
        if sum(1 for v in vals if v) < 4:
            return None
        return Formation(
            position_1=vals[0], position_2=vals[1], position_3=vals[2],
            position_4=vals[3], position_5=vals[4] if len(vals) > 4 else None,
            position_6=vals[5] if len(vals) > 5 else None,
        )

    def _parse_substitutions(
        self, table: list, start: int,
        pos_left: list[int], pos_right: list[int], sd: dict,
    ) -> None:
        """Parse les remplacements (rows +3 à +5).

        Un changement lie deux joueurs pour tout le set.
        - Row +3 : numéro du remplaçant (entrant)
        - Row +4 : score du changement ALLER (entrant entre, sortant sort)
        - Row +5 : score du changement RETOUR (sortant revient, entrant sort)
        Si row +5 a un score, cela signifie un changement aller-retour.

        Les scores dans les cellules sont au format demandeur:adversaire.
        On les convertit systématiquement en (left_score, right_score).
        """
        n = len(table)
        sub_row = table[start + 3] if start + 3 < n else None
        score_row_aller = table[start + 4] if start + 4 < n else None
        score_row_retour = table[start + 5] if start + 5 < n else None
        score_pat = re.compile(r'^(\d{1,2}):(\d{1,2})$')

        if not sub_row:
            return

        for cols, changes, form, is_right in [
            (pos_left, sd['changements_left'], sd['formation_left'], False),
            (pos_right, sd['changements_right'], sd['formation_right'], True),
        ]:
            for pos_idx, col in enumerate(cols):
                if col >= len(sub_row) or not sub_row[col]:
                    continue
                entrant = str(sub_row[col]).strip()
                if not entrant or not entrant.isdigit():
                    continue

                sortant = None
                if form:
                    form_list = form.as_list()
                    if pos_idx < len(form_list) and form_list[pos_idx]:
                        sortant = form_list[pos_idx]

                # Changement ALLER : entrant remplace sortant
                sa_aller, sb_aller = None, None
                if score_row_aller and col < len(score_row_aller) and score_row_aller[col]:
                    sm = score_pat.match(str(score_row_aller[col]).strip())
                    if sm:
                        sa_aller, sb_aller = int(sm.group(1)), int(sm.group(2))
                        # Cell = demandeur:adversaire → convertir en left:right
                        if is_right:
                            sa_aller, sb_aller = sb_aller, sa_aller

                changes.append({
                    'joueur_entrant': entrant,
                    'joueur_sortant': sortant,
                    'position': pos_idx + 1,
                    'score_left': sa_aller,
                    'score_right': sb_aller,
                })

                # Changement RETOUR : sortant revient pour entrant
                if score_row_retour and col < len(score_row_retour) and score_row_retour[col]:
                    sm = score_pat.match(str(score_row_retour[col]).strip())
                    if sm:
                        sa_ret, sb_ret = int(sm.group(1)), int(sm.group(2))
                        if is_right:
                            sa_ret, sb_ret = sb_ret, sa_ret
                        changes.append({
                            'joueur_entrant': sortant or entrant,
                            'joueur_sortant': entrant,
                            'position': pos_idx + 1,
                            'score_left': sa_ret,
                            'score_right': sb_ret,
                        })

    def _parse_service_timeouts(
        self, table: list, start: int,
        pos_left: list[int], pos_right: list[int],
        sd: dict, n_cols: int,
    ) -> None:
        """Parse les tours au service, scores de service et timeouts (rows +6 à +9).

        - Colonnes position (pos_left / pos_right) : score de l'équipe
          au moment où le joueur en cette position prend le service.
          L'équipe au service a un '0' en position I (sert en premier),
          l'équipe en réception a un 'X' (servira après rotation).
        - Le 'T' indique un timeout (colonne juste après les positions).
          Les scores de timeout sont en format demandeur:adversaire
          et sont convertis en (left_score, right_score).
        """
        n = len(table)
        timeout_pat = re.compile(r'^(\d{1,2}):(\d{1,2})$')

        # Frontière gauche/droite
        if pos_right:
            mid_col = pos_right[0]
        elif pos_left:
            mid_col = pos_left[-1] + 3
        else:
            mid_col = n_cols // 2

        pos_left_set = set(pos_left)
        pos_right_set = set(pos_right)

        for offset in range(4):
            idx = start + 6 + offset
            if idx >= n:
                break
            row = table[idx]
            if not row:
                continue

            # Extraire les scores de service depuis les colonnes de position
            for pos_idx, col in enumerate(pos_left):
                if col < len(row) and row[col]:
                    val = str(row[col]).strip()
                    if val.isdigit():
                        pos_num = pos_idx + 1
                        sd['services_left'].setdefault(pos_num, []).append(int(val))

            for pos_idx, col in enumerate(pos_right):
                if col < len(row) and row[col]:
                    val = str(row[col]).strip()
                    if val.isdigit():
                        pos_num = pos_idx + 1
                        sd['services_right'].setdefault(pos_num, []).append(int(val))

            # Timeouts : chercher les 'T' hors des colonnes de position
            for i, cell in enumerate(row):
                if not cell or i in pos_left_set or i in pos_right_set:
                    continue
                cs = str(cell).strip()

                if cs == 'T':
                    side = 'left' if i < mid_col else 'right'

                    # Chercher les scores de timeout dans les lignes suivantes.
                    # Il peut y avoir 2 timeouts par set (1 score par ligne).
                    for d in range(1, 4):
                        nxt = idx + d
                        if nxt >= n or nxt >= start + ROWS_PER_SET:
                            break
                        nr = table[nxt]
                        if not nr or i >= len(nr) or not nr[i]:
                            continue
                        sm = timeout_pat.match(str(nr[i]).strip())
                        if sm:
                            sa, sb = int(sm.group(1)), int(sm.group(2))
                            # Cell = demandeur:adversaire → convertir en left:right
                            if side == 'right':
                                sa, sb = sb, sa
                            if side == 'left':
                                sd['timeouts_left'].append({'score_left': sa, 'score_right': sb})
                            else:
                                sd['timeouts_right'].append({'score_left': sa, 'score_right': sb})

    # =====================================================================
    # Table RESULTATS
    # =====================================================================

    def _parse_resultats_table(self, tidx: dict) -> tuple[list[dict], Optional[str]]:
        """Parse la table RESULTATS pour les scores/stats par set.

        Structure :
          Row 0 : RESULTATS
          Row 1 : Equipe A / Equipe B
          Row 2 : T R G P | Durée par Set | P G R T
          Row 3-7 : Sets (+ ligne totaux)
          Row 8 : Début / Fin / Durée labels
          Row 9 : Heures
          Row 10 : Vainqueur
        """
        tbl = tidx.get('results')
        if not tbl:
            return [], None

        # Durées par set
        durations: dict[int, int] = {}
        for row in tbl:
            if not row or len(row) <= 4 or not row[4]:
                continue
            for dm in re.finditer(r'(\d)\s+(\d+)\'', str(row[4])):
                durations[int(dm.group(1))] = int(dm.group(2))
            if durations:
                break

        # Durée totale
        duree_totale: Optional[str] = None
        for i, row in enumerate(tbl):
            if not row:
                continue
            rt = ' '.join(str(c) for c in row if c)
            if 'Début' in rt and 'Fin' in rt and 'Durée' in rt:
                if i + 1 < len(tbl) and tbl[i + 1]:
                    for cell in tbl[i + 1]:
                        if not cell:
                            continue
                        cs = str(cell).strip()
                        if re.match(r'^\d+h\d+$', cs):
                            duree_totale = cs
                            break
                        if re.match(r"^\d+'$", cs):
                            duree_totale = cs
                            break
                break

        # Données par set
        data: list[dict] = []
        set_num = 0
        for row_idx in range(3, min(8, len(tbl))):
            row = tbl[row_idx]
            if not row:
                continue

            # Compter les valeurs numériques
            nums = []
            for c in row:
                if c is not None:
                    s = str(c).strip().replace("'", "")
                    if s.isdigit():
                        nums.append(int(s))
            if len(nums) < 3:
                continue
            # Exclure la ligne totaux
            if any(v > 50 for v in nums):
                continue

            set_num += 1
            d = {
                'numero': set_num,
                'timeouts_a': self._safe_int(row, 0),
                'remplacements_a': self._safe_int(row, 1),
                'sets_gagnes_a': self._safe_int(row, 2),
                'points_a': self._safe_int(row, 3),
                'duree_minutes': durations.get(set_num),
                'points_b': self._safe_int(row, 6),
                'sets_gagnes_b': self._safe_int(row, 7),
                'remplacements_b': self._safe_int(row, 8),
                'timeouts_b': self._safe_int(row, 9),
            }
            data.append(d)

        return data, duree_totale

    @staticmethod
    def _safe_int(row: list, idx: int) -> Optional[int]:
        if idx >= len(row) or row[idx] is None:
            return None
        s = str(row[idx]).strip().replace("'", "")
        return int(s) if s.isdigit() else None

    # =====================================================================
    # Construction des Sets (avec cross-validation)
    # =====================================================================

    def _build_sets(
        self, detailed: list[dict], resultats: list[dict],
        resultat: dict, nom_a: str, nom_b: str,
    ) -> tuple[list[Set], list[str]]:
        """Construit les Sets avec mapping left/right → A/B."""
        warnings: list[str] = []

        nb = 0
        if sc := resultat.get("score_final"):
            try:
                a, b = sc.split("/")
                nb = int(a) + int(b)
            except Exception:
                pass
        if not nb:
            nb = max(len(detailed), len(resultats), 0)

        # Détecter si la table RESULTATS a les équipes inversées par rapport
        # à l'assignation equipe_a / equipe_b du parser.
        # C'est un phénomène courant dans les PDFs FFVB (~40% des fichiers) :
        # "Equipe A" dans la table RESULTATS ne correspond pas toujours à
        # l'equipe_a du parser (extraite de la table joueurs).
        # On compare les sets gagnés (colonne G) avec le vainqueur.
        results_swap = False
        vainqueur = resultat.get("vainqueur", "")
        if vainqueur and resultats:
            b_wins = self._team_matches(vainqueur, nom_b)
            a_wins = self._team_matches(vainqueur, nom_a)
            total_ga = sum(r.get('sets_gagnes_a', 0) or 0 for r in resultats)
            total_gb = sum(r.get('sets_gagnes_b', 0) or 0 for r in resultats)
            if b_wins and not a_wins and total_ga > total_gb:
                # B a gagné le match mais "Equipe A" de la table a plus de
                # victoires → la table est inversée par rapport au parser.
                results_swap = True
                logger.debug(
                    "Colonnes RESULTATS inversées (corrigé automatiquement) : "
                    "vainqueur '%s' = equipe_b, G table: A=%d B=%d",
                    vainqueur, total_ga, total_gb,
                )
            elif a_wins and not b_wins and total_gb > total_ga:
                # A a gagné le match mais "Equipe B" de la table a plus de
                # victoires → la table est inversée par rapport au parser.
                results_swap = True
                logger.debug(
                    "Colonnes RESULTATS inversées (corrigé automatiquement) : "
                    "vainqueur '%s' = equipe_a, G table: A=%d B=%d",
                    vainqueur, total_ga, total_gb,
                )
            elif not a_wins and not b_wins:
                # Le vainqueur ne correspond à aucune équipe → erreur de matching
                warnings.append(
                    f"Vainqueur '{vainqueur}' ne correspond ni à "
                    f"'{nom_a}' ni à '{nom_b}'"
                )

        sets: list[Set] = []
        for i in range(nb):
            sn = i + 1
            det = next((s for s in detailed if s['numero'] == sn), None)
            res = next((r for r in resultats if r.get('numero') == sn), None)

            # Scores from RESULTATS (référence)
            # Si results_swap, inverser points_a et points_b
            if not results_swap:
                score_a = res.get('points_a') if res else None
                score_b = res.get('points_b') if res else None
            else:
                score_a = res.get('points_b') if res else None
                score_b = res.get('points_a') if res else None

            # Durée
            duree = None
            if res and res.get('duree_minutes'):
                duree = res['duree_minutes']

            # Heures
            debut_t = self._parse_time_str(det.get('heure_debut') if det else None)
            fin_t = self._parse_time_str(det.get('heure_fin') if det else None)

            # Mapping left/right → A/B
            swap = False
            if det and det.get('left_team_name'):
                swap = self._team_matches(det['left_team_name'], nom_b)

            if det:
                if not swap:
                    form_a = det['formation_left']
                    form_b = det['formation_right']
                    to_a_raw = det['timeouts_left']
                    to_b_raw = det['timeouts_right']
                    ch_a = det['changements_left']
                    ch_b = det['changements_right']
                    srv_a = det.get('services_left', {})
                    srv_b = det.get('services_right', {})
                    srv_side = det.get('service_initial_side')
                    srv = 'A' if srv_side == 'left' else ('B' if srv_side == 'right' else None)
                else:
                    form_a = det['formation_right']
                    form_b = det['formation_left']
                    to_a_raw = det['timeouts_right']
                    to_b_raw = det['timeouts_left']
                    ch_a = det['changements_right']
                    ch_b = det['changements_left']
                    srv_a = det.get('services_right', {})
                    srv_b = det.get('services_left', {})
                    srv_side = det.get('service_initial_side')
                    srv = 'B' if srv_side == 'left' else ('A' if srv_side == 'right' else None)
            else:
                form_a, form_b = None, None
                to_a_raw, to_b_raw = [], []
                ch_a, ch_b = [], []
                srv_a, srv_b = {}, {}
                srv = None
                if score_a is None and score_b is None:
                    warnings.append(f"Set {sn}: aucune donnée de score")

            # Mapper les scores intermédiaires (left, right) vers (A, B).
            # Tous les scores intermédiaires sont stockés en (left_score, right_score).
            # Si swap : left=B, right=A → on inverse.
            def _map_scores(sl: Optional[int], sr: Optional[int]) -> tuple:
                if not swap:
                    return sl, sr
                return sr, sl

            # Convertir les changements en objets Changement
            changements_a = [
                Changement(
                    joueur_entrant=c['joueur_entrant'],
                    joueur_sortant=c.get('joueur_sortant'),
                    position=c.get('position'),
                    score_a=_map_scores(c.get('score_left'), c.get('score_right'))[0],
                    score_b=_map_scores(c.get('score_left'), c.get('score_right'))[1],
                ) for c in ch_a
            ]
            changements_b = [
                Changement(
                    joueur_entrant=c['joueur_entrant'],
                    joueur_sortant=c.get('joueur_sortant'),
                    position=c.get('position'),
                    score_a=_map_scores(c.get('score_left'), c.get('score_right'))[0],
                    score_b=_map_scores(c.get('score_left'), c.get('score_right'))[1],
                ) for c in ch_b
            ]

            # Convertir les timeouts (dicts) en objets TimeOut
            timeouts_a = [
                TimeOut(
                    score_a=_map_scores(d.get('score_left'), d.get('score_right'))[0],
                    score_b=_map_scores(d.get('score_left'), d.get('score_right'))[1],
                ) for d in to_a_raw
            ]
            timeouts_b = [
                TimeOut(
                    score_a=_map_scores(d.get('score_left'), d.get('score_right'))[0],
                    score_b=_map_scores(d.get('score_left'), d.get('score_right'))[1],
                ) for d in to_b_raw
            ]

            s = Set(
                numero=sn,
                score_a=score_a, score_b=score_b,
                debut=debut_t, fin=fin_t,
                duree_minutes=duree,
                service_initial=srv,
                formation_a=form_a,
                formation_b=form_b,
                timeouts_a=timeouts_a,
                timeouts_b=timeouts_b,
                equipe_a=SetTeamData(
                    formation=form_a,
                    timeouts=timeouts_a,
                    changements=changements_a,
                    services=srv_a,
                ),
                equipe_b=SetTeamData(
                    formation=form_b,
                    timeouts=timeouts_b,
                    changements=changements_b,
                    services=srv_b,
                ),
            )
            sets.append(s)

        return sets, warnings

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalise un nom en supprimant les artefacts d'extraction PDF.

        Certains vieux PDFs insèrent un espace après la 1ère lettre du nom :
        'M AROMME CANTELEU' → 'MAROMME CANTELEU'
        'A UBAGNE CARNOUX'  → 'AUBAGNE CARNOUX'
        """
        name = name.strip()
        # Pattern : une seule lettre majuscule suivie d'un espace puis d'un
        # mot qui commence par une majuscule (artefact d'extraction)
        name = re.sub(r'^([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ])\s+(?=[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ])', r'\1', name)
        return re.sub(r'\s+', ' ', name).strip()

    @staticmethod
    def _team_matches(truncated: str, full_name: str) -> bool:
        """Compare un nom d'équipe (potentiellement tronqué / artefacté) avec le nom complet."""
        t = MatchSheetParserV5._normalize_name(truncated).upper()
        f = MatchSheetParserV5._normalize_name(full_name).upper()
        if not t or not f:
            return False
        # Comparaison directe et par préfixe
        if f.startswith(t) or t.startswith(f[:15]) or t[:10] in f:
            return True
        # Comparaison sans espaces (gère les artefacts résiduels)
        t_compact = t.replace(' ', '').replace('-', '').replace('.', '')
        f_compact = f.replace(' ', '').replace('-', '').replace('.', '')
        return f_compact.startswith(t_compact[:12]) or t_compact[:12] in f_compact

    @staticmethod
    def _parse_time_str(val: Optional[str]) -> Optional[dt_time]:
        if not val:
            return None
        try:
            parts = val.split(':')
            return dt_time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return None

    # =====================================================================
    # Arbitres
    # =====================================================================

    def _parse_arbitres(self, tidx: dict, full_text: str) -> list[Arbitre]:
        """Parse les arbitres depuis la table main.

        Les arbitres se trouvent dans les lignes après "Arbitres" avec
        les colonnes : Role | NOM Prénom | Ligue | Licence
        """
        arbitres: list[Arbitre] = []

        tbl = tidx.get('main')
        if not tbl:
            return arbitres

        in_arbitre_section = False

        for row in tbl:
            if not row:
                continue
            rt = ' '.join(str(c) for c in row if c)

            # Détecter la section arbitres
            if 'Arbitres' in rt and 'NOM' in rt:
                in_arbitre_section = True
                continue

            if not in_arbitre_section:
                continue

            # Fin de section
            if 'Capitaines' in rt or 'Juges' in rt and 'Lignes' in rt:
                if 'Juges' in rt:
                    # Pas d'arbitre juges de ligne dans ces PDFs mais on note
                    pass
                continue

            # Chercher un rôle d'arbitre dans la ligne
            role_found = None
            role_col = None
            for k, cell in enumerate(row):
                if not cell:
                    continue
                cs = str(cell).strip()
                # Gestion du cas où pdfplumber fusionne le role avec le nom
                # Ex: "MarqueurAZAR NICOLAS" → role=Marqueur, nom="AZAR NICOLAS"
                for role_text, role_enum in ROLE_ARBITRE_MAP.items():
                    if cs == role_text:
                        role_found = role_enum
                        role_col = k
                        break
                    if cs.startswith(role_text) and len(cs) > len(role_text):
                        role_found = role_enum
                        role_col = k
                        # Le reste est le début du nom
                        break
                if role_found:
                    break

            if not role_found:
                continue

            # Chercher nom, ligue, licence dans le reste de la ligne
            nom_complet = None
            licence = None
            ligue = None

            for j in range(len(row)):
                if j == role_col:
                    # Vérifier si le nom est fusionné avec le rôle
                    cs = str(row[j]).strip() if row[j] else ""
                    for rt_text in ROLE_ARBITRE_MAP:
                        if cs.startswith(rt_text) and len(cs) > len(rt_text):
                            # Nom fusionné
                            remaining = cs[len(rt_text):].strip()
                            if remaining and ' ' in remaining:
                                nom_complet = remaining
                            break
                    continue

                if not row[j]:
                    continue
                cs = str(row[j]).strip()
                if not cs:
                    continue

                # Licence : 4-7 chiffres (certaines anciennes licences < 6 chiffres)
                if cs.isdigit() and 4 <= len(cs) <= 7:
                    licence = cs
                # Ligue : 2-4 lettres majuscules
                elif cs.isalpha() and cs.isupper() and 2 <= len(cs) <= 4:
                    ligue = cs
                # Nom complet : contient un espace, > 3 chars
                elif ' ' in cs and len(cs) > 3 and cs not in ('NOM Prénom', 'Nom Prénom'):
                    nom_complet = cs

            if nom_complet:
                nom, prenom = self._split_nom_prenom(nom_complet)
                if not any(a.nom == nom and a.role == role_found for a in arbitres):
                    arbitres.append(Arbitre(
                        nom=nom, prenom=prenom,
                        role=role_found,
                        licence=licence,
                        ligue=ligue,
                    ))

        return arbitres

    # =====================================================================
    # Sanctions
    # =====================================================================

    def _parse_sanctions(self, tidx: dict) -> tuple[list[Sanction], list[str]]:
        """Parse les sanctions. Signale toute sanction détectée."""
        sanctions: list[Sanction] = []
        warnings: list[str] = []

        tbl = tidx.get('main')
        if not tbl:
            return sanctions, warnings

        in_sanctions = False
        raw_data: list[str] = []

        type_map = {
            'A': TypeSanction.AVERTISSEMENT,
            'P': TypeSanction.PENALITE,
            'E': TypeSanction.EXPULSION,
            'D': TypeSanction.DISQUALIFICATION,
        }

        for row in tbl:
            if not row:
                continue
            rt = ' '.join(str(c) for c in row if c).upper()

            if 'SANCTIONS' in rt and ('DEMANDE' in rt or 'EQU' in rt):
                in_sanctions = True
                continue

            if in_sanctions:
                if any(kw in rt for kw in ['1ER', '2ÈME', 'MARQUEUR', 'ARBITRE', 'APPROBATION']):
                    break

                mid = len(row) // 2
                has_content = False
                for cell in row:
                    if not cell:
                        continue
                    cs = str(cell).strip()
                    if cs and len(cs) >= 2 and cs.upper() not in (
                        'A', 'P', 'E', 'D', 'A/B', 'EQU.A EQU.B', 'SET', 'SCORE',
                    ):
                        has_content = True
                        break

                if has_content:
                    row_data = ' | '.join(
                        str(c).strip() for c in row if c and str(c).strip()
                    )
                    raw_data.append(row_data)

                    # Tenter de parser la sanction
                    equipe = 'A'
                    for j, cell in enumerate(row):
                        if not cell:
                            continue
                        cs = str(cell).strip()
                        if not cs or len(cs) < 2:
                            continue
                        if j >= mid:
                            equipe = 'B'

                        # Format : "N° Set Score" ou variations
                        sm = re.search(r'(\d{1,2})\s+(\d)\s+.*?(\d+)[-:](\d+)', cs)
                        if sm:
                            sanctions.append(Sanction(
                                type=TypeSanction.AVERTISSEMENT,
                                set_numero=int(sm.group(2)),
                                equipe=equipe,
                                joueur_numero=sm.group(1),
                                score_a=int(sm.group(3)),
                                score_b=int(sm.group(4)),
                            ))

        if raw_data:
            warnings.append(
                f"⚠️ SANCTIONS DÉTECTÉES : {'; '.join(raw_data)}. "
                f"Vérifiez le PDF manuellement."
            )

        return sanctions, warnings

    # =====================================================================
    # Remarques / Demande non fondée
    # =====================================================================

    def _parse_remarques(self, tidx: dict) -> Optional[str]:
        """Extrait les remarques depuis la table main."""
        tbl = tidx.get('main')
        if not tbl:
            return None

        in_remarques = False
        content = []

        for row in tbl:
            if not row:
                continue
            rt = ' '.join(str(c) for c in row if c)
            if 'REMARQUES' in rt:
                in_remarques = True
                # Extraire le contenu après REMARQUES sur la même ligne
                parts = rt.split('REMARQUES')
                if len(parts) > 1:
                    rem = parts[1].strip()
                    # Exclure les artefacts de la section sanctions
                    if rem and not re.match(r'^[APED\s|/]+$', rem) and len(rem) > 3:
                        content.append(rem)
                continue
            if in_remarques:
                if any(kw in rt for kw in [
                    'SANCTIONS', 'APPROBATION', 'Arbitres', 'EQU.A',
                    'A/B', 'Set', 'Score',
                ]):
                    break
                cleaned = rt.strip()
                # Exclure les lignes de la section sanctions qui se mélangent
                if (cleaned and len(cleaned) > 3
                    and not re.match(r'^[APED\s|/]+$', cleaned)
                    and cleaned not in ('EQU.A EQU.B',)):
                    content.append(cleaned)

        return ' '.join(content).strip() or None

    def _parse_demande_non_fondee(self, tidx: dict) -> Optional[str]:
        """Extrait la demande non fondée depuis la table main."""
        tbl = tidx.get('main')
        if not tbl:
            return None

        for row in tbl:
            if not row:
                continue
            rt = ' '.join(str(c) for c in row if c)
            if 'DEMANDE NON FONDEE' in rt:
                # Le contenu est sur la même ligne ou la suivante
                parts = rt.split('DEMANDE NON FONDEE')
                if len(parts) > 1:
                    rem = parts[1].replace('REMARQUES', '').strip()
                    if rem:
                        return rem
        return None

    # =====================================================================
    # Validation
    # =====================================================================

    def _validate(self, match: Match, *, is_modern: bool = True) -> list[str]:
        """Valide la cohérence des données parsées.

        Args:
            match: Le match parsé.
            is_modern: True si la saison est >= 2024-2025 (détails attendus).
        """
        warnings: list[str] = []

        # ── Informations générales obligatoires ──
        if not match.code_match or match.code_match == "UNKNOWN":
            warnings.append("Code match manquant ou non détecté")
        if not match.date:
            warnings.append("Date du match manquante")
        if not match.saison:
            warnings.append("Saison non déterminée")
        if not match.competition:
            warnings.append("Nom de compétition manquant")

        # ── Équipes ──
        for label, eq in [('A', match.equipe_a), ('B', match.equipe_b)]:
            if not eq:
                warnings.append(f"Équipe {label} non détectée")
                continue
            if not eq.nom or eq.nom in ("Équipe A", "Équipe B"):
                warnings.append(f"Nom d'équipe {label} manquant ou générique")
            if not eq.joueurs:
                warnings.append(f"Aucun joueur pour l'équipe {label}")
                continue
            if not any(j.est_capitaine for j in eq.joueurs):
                warnings.append(f"Aucun capitaine détecté pour l'équipe {label} ({eq.nom})")
            # Note : l'absence de libéro est normale (pas obligatoire).
            for j in eq.joueurs:
                if j.est_capitaine and j.est_libero:
                    warnings.append(
                        f"Joueur #{j.numero} ({j.nom}) de l'équipe {label} "
                        f"est capitaine ET libéro"
                    )
                if not j.licence:
                    warnings.append(
                        f"Licence manquante pour joueur #{j.numero} "
                        f"({j.nom}) de l'équipe {label}"
                    )

        # ── Arbitres ──
        if not match.arbitres:
            warnings.append("Aucun arbitre détecté")

        # ── Cohérence des scores (seulement si le match est joué) ──
        if match.match_joue:
            # Vainqueur vs équipes
            if match.vainqueur_nom and match.equipe_a and match.equipe_b:
                va = self._team_matches(match.vainqueur_nom, match.equipe_a.nom)
                vb = self._team_matches(match.vainqueur_nom, match.equipe_b.nom)
                if not va and not vb:
                    warnings.append(
                        f"Vainqueur '{match.vainqueur_nom}' ne correspond ni à "
                        f"'{match.equipe_a.nom}' ni à '{match.equipe_b.nom}'"
                    )

            if match.has_details and match.score_final and match.sets:
                try:
                    sa, sb = match.score_final.split('/')
                    expected_sets = int(sa) + int(sb)
                    if len(match.sets) != expected_sets:
                        warnings.append(
                            f"Score final {match.score_final} implique {expected_sets} sets, "
                            f"mais {len(match.sets)} sets parsés"
                        )
                except Exception:
                    pass

                # Déterminer le format du match : best-of-3 ou best-of-5
                # En best-of-3 (2 sets gagnants), le set décisif (3) va en 15 pts.
                # En best-of-5 (3 sets gagnants), le set décisif (5) va en 15 pts.
                winning_sets = max(match.sets_a, match.sets_b)
                if winning_sets == 2:
                    deciding_set = 3  # best-of-3
                else:
                    deciding_set = 5  # best-of-5 (par défaut)

                # Vérifier scores individuels des sets
                for s in match.sets:
                    if s.score_a is None or s.score_b is None:
                        warnings.append(
                            f"Set {s.numero}: score manquant "
                            f"({s.score_a}-{s.score_b})"
                        )
                    elif s.score_a == 0 and s.score_b == 0:
                        warnings.append(
                            f"Set {s.numero}: score 0-0 (probablement non renseigné)"
                        )
                    elif s.numero == deciding_set:
                        # Set décisif (set 3 ou set 5) : doit aller à 15
                        if max(s.score_a, s.score_b) < 15:
                            warnings.append(
                                f"Set {s.numero}: score {s.score_a}-{s.score_b} "
                                f"n'atteint pas 15 points"
                            )
                    else:
                        # Sets normaux : doivent aller à 25
                        if max(s.score_a, s.score_b) < 25:
                            warnings.append(
                                f"Set {s.numero}: score {s.score_a}-{s.score_b} "
                                f"n'atteint pas 25 points"
                            )

                # Score final vs sets effectivement gagnés
                if match.sets_a + match.sets_b > 0:
                    computed_a = sum(
                        1 for s in match.sets
                        if s.score_a is not None and s.score_b is not None
                        and s.score_a > s.score_b
                    )
                    computed_b = sum(
                        1 for s in match.sets
                        if s.score_a is not None and s.score_b is not None
                        and s.score_b > s.score_a
                    )
                    if computed_a + computed_b > 0:
                        if computed_a != match.sets_a or computed_b != match.sets_b:
                            warnings.append(
                                f"Incohérence score: final {match.sets_a}/{match.sets_b} "
                                f"vs calculé {computed_a}/{computed_b} depuis scores de sets"
                            )

        return warnings

    # =====================================================================
    # Construction du Match
    # =====================================================================

    def _build_match(
        self, *, header: dict, equipes_info: dict, resultat: dict,
        joueurs_a: list, joueurs_b: list,
        liberos_a: list, liberos_b: list,
        off_a: list[Officiel], off_b: list[Officiel],
        sets: list[Set], arbitres: list[Arbitre],
        sanctions: list[Sanction],
        remarques: Optional[str], demande_nf: Optional[str],
        pdf_path: Path, match_joue: bool,
    ) -> Match:

        nom_a = equipes_info.get("equipe_a") or "Équipe A"
        nom_b = equipes_info.get("equipe_b") or "Équipe B"

        # Extraire les informations du club depuis le nom d'équipe
        club_nom_a, num_equipe_a = self._extract_club_info(nom_a)
        club_nom_b, num_equipe_b = self._extract_club_info(nom_b)

        # Fusionner libéros dans la liste des joueurs (évite la duplication)
        all_joueurs_a = self._merge_liberos(joueurs_a, liberos_a)
        all_joueurs_b = self._merge_liberos(joueurs_b, liberos_b)

        equipe_a = Equipe(
            nom=nom_a,
            club_nom=club_nom_a,
            numero_equipe=num_equipe_a,
            joueurs=all_joueurs_a,
            officiels=off_a,
        )
        equipe_b = Equipe(
            nom=nom_b,
            club_nom=club_nom_b,
            numero_equipe=num_equipe_b,
            joueurs=all_joueurs_b,
            officiels=off_b,
        )

        sets_a, sets_b = 0, 0
        computed_a = sum(
            1 for s in sets
            if s.score_a is not None and s.score_b is not None
            and s.score_a > s.score_b
        )
        computed_b = sum(
            1 for s in sets
            if s.score_a is not None and s.score_b is not None
            and s.score_b > s.score_a
        )
        if computed_a + computed_b > 0:
            sets_a, sets_b = computed_a, computed_b
        elif sc := resultat.get("score_final"):
            try:
                a, b = sc.split("/")
                sets_a, sets_b = int(a), int(b)
            except Exception:
                pass

        genre = self._try_enum(Genre, header.get("genre"))
        categorie = self._try_enum(Categorie, header.get("categorie"))

        # Remarques enrichies
        all_remarks = []
        if remarques:
            all_remarks.append(remarques)
        if demande_nf:
            all_remarks.append(f"Demande non fondée: {demande_nf}")
        full_remarks = ' | '.join(all_remarks) if all_remarks else None

        # Extraire le code de compétition/poule depuis le code match
        # Ex: "EMA001" → "EMA", "PMAA001" → "PMAA"
        code_match = header.get("code_match") or "UNKNOWN"
        competition_code = self._extract_competition_code(code_match)

        # Déterminer les flags de statut du match
        has_details = any(
            s.score_a is not None and s.score_b is not None
            and (s.score_a > 0 or s.score_b > 0)
            for s in sets
        )

        # score_source : "pdf" si on a des scores détaillés, sinon None
        # (sera complété plus tard par "online" via score_completion)
        score_source: Optional[str] = None
        if has_details:
            score_source = "pdf"
        elif match_joue and (sets_a + sets_b > 0):
            # Vainqueur + score global extrait depuis la feuille
            score_source = "pdf"

        return Match(
            code_match=code_match,
            ligue=header.get("ligue"),
            competition=header.get("competition"),
            competition_code=competition_code,
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
            score_final=f"{sets_a}/{sets_b}" if sets_a + sets_b > 0 else resultat.get("score_final"),
            sets_a=sets_a,
            sets_b=sets_b,
            duree_totale=resultat.get("duree_totale"),
            match_joue=match_joue,
            has_details=has_details,
            score_source=score_source,
            arbitres=arbitres,
            sanctions=sanctions,
            remarques=full_remarks,
            source_pdf=str(pdf_path),
            parsed_at=datetime.now(),
        )

    @staticmethod
    def _merge_liberos(joueurs: list[Joueur], liberos: list[Joueur]) -> list[Joueur]:
        """Fusionne les libéros dans la liste des joueurs, sans doublons."""
        existing_ids = {(j.numero, j.licence) for j in joueurs}
        merged = list(joueurs)
        for lib in liberos:
            if (lib.numero, lib.licence) not in existing_ids:
                lib.est_libero = True
                merged.append(lib)
        return merged

    @staticmethod
    def _officiel_name(officials: list[Officiel], role: str) -> Optional[str]:
        for o in officials:
            if o.role == role:
                return f"{o.nom} {o.prenom}".strip() if o.prenom else o.nom
        return None

    @staticmethod
    def _try_enum(enum_cls, val):
        if not val:
            return None
        try:
            return enum_cls(val)
        except (ValueError, KeyError):
            return None

    @staticmethod
    def _extract_competition_code(code_match: str) -> Optional[str]:
        """Extrait le code de compétition/poule depuis le code match.

        Les codes match FFVB suivent le pattern : CODE_POULE + NUMERO_MATCH.
        Le numéro de match est toujours constitué de chiffres en fin de chaîne.

        Exemples :
          "EMA001"   → "EMA"
          "PMAA001"  → "PMAA"
          "1FA012"   → "1FA"
          "PFAH001"  → "PFAH"
          "UNKNOWN"  → None
        """
        if not code_match or code_match == "UNKNOWN":
            return None
        # Le code match = code_poule + numéro (que des chiffres à la fin)
        m = re.match(r'^([A-Za-z0-9]+?)(\d{2,})$', code_match)
        if m:
            return m.group(1)
        return None
