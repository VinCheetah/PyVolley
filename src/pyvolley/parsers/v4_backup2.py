"""
Parser V4 - Parser optimisé basé sur pdfplumber avec extraction spatiale.

Ce parser est une version améliorée qui extrait de manière fiable et complète
toutes les informations des feuilles de match FFVB :

- Extraction complète des joueurs depuis la table dédiée
- Extraction correcte des scores de sets depuis la table RESULTATS
- Parsing détaillé de chaque set (formations, remplacements, timeouts, scores)
- Détection des libéros via positionnement spatial (section LIBEROS)
- Détection des officiels via positionnement spatial (section OFFICIELS avec EA/EB)
- Détection des capitaines (via table de signatures, best-effort)
- Parsing des sanctions (structure en place, généralement vide en numérique)
- Extraction des heures de début/fin par set
- Extraction du service initial par set

Architecture :
    Page 0 du PDF contient 5 tables principales :
      Table 0 (la + longue, ~44 rows) → Sets 1, 3, 5 + sanctions + arbitres
      Table 1 (~20 rows)             → Sets 2, 4
      Table 2 (~4 rows)              → Roster joueurs
      Table 3 (~12 rows)             → RESULTATS (scores, durées, totaux)
      Table 4 (~3 rows)              → SIGNATURES (capitaine N°, entraîneur)
    Chaque section de set occupe 10 rows dans sa table.
"""

import time
import re
from pathlib import Path
from typing import Optional
from datetime import datetime, date as dt_date, time as dt_time
from collections import defaultdict
from dataclasses import dataclass, field

import pdfplumber

from pyvolley.parsers.base import BaseParser, ParseResult
from pyvolley.core.models import (
    Match, Set, Joueur, Equipe, Arbitre, Sanction, Formation, TimeOut,
    Genre, Categorie, RoleArbitre, TypeSanction
)


# =============================================================================
# Dataclasses auxiliaires
# =============================================================================

@dataclass
class Changement:
    """Représente un changement de joueur pendant un set."""
    joueur_entrant: str
    joueur_sortant: str
    position: int = 0  # Position I-VI (1-6) où le remplacement intervient
    score_a: Optional[int] = None
    score_b: Optional[int] = None


@dataclass
class OfficielInfo:
    """Informations sur un officiel d'équipe."""
    role: str  # "EA" (Entraîneur A), "EB" (Entraîneur B), etc.
    nom: str
    prenom: str = ""
    licence: str = ""


@dataclass
class SetDetailedInfo:
    """Informations détaillées d'un set extraites du PDF.

    IMPORTANT : ``formation_left`` / ``formation_right`` stockent la
    formation telle qu'elle apparaît dans le tableau du PDF (gauche vs
    droite).  Le mapping vers equipe_a / equipe_b est fait plus tard
    dans ``_build_sets`` via le champ ``left_team_name``.
    """
    numero: int
    score_a: Optional[int] = None
    score_b: Optional[int] = None
    duree_minutes: Optional[int] = None
    heure_debut: Optional[str] = None
    heure_fin: Optional[str] = None
    service_initial_side: Optional[str] = None  # 'left' ou 'right' (qui sert en premier dans le tableau)
    left_team_name: Optional[str] = None   # nom (tronqué) de l'équipe à gauche du tableau
    right_team_name: Optional[str] = None  # nom (tronqué) de l'équipe à droite du tableau
    formation_left: Optional[Formation] = None
    formation_right: Optional[Formation] = None
    changements_left: list = field(default_factory=list)
    changements_right: list = field(default_factory=list)
    timeouts_left: list = field(default_factory=list)
    timeouts_right: list = field(default_factory=list)


# =============================================================================
# Parser principal
# =============================================================================

class MatchSheetParserV4(BaseParser):
    """
    Parser V4 optimisé pour les feuilles de match FFVB.

    Utilise pdfplumber avec une stratégie d'extraction combinant :
    - Tables pour les données structurées (sets, résultats, joueurs)
    - Mots avec coordonnées pour les données positionnelles (libéros, officiels)

    Chaque section de set (10 rows dans la table) :
    - Row +0 : En-tête SET avec noms d'équipes, heures, service (S/R)
    - Row +1 : Ordre de Service (positions I .. VI, grille de suivi)
    - Row +2 : Formation de Départ (numéros joueurs aux positions)
    - Row +3 : Remplaçants (N° entrant sous N° sortant) + « Joueur N° »
    - Row +4 : Score au moment du remplacement + « Score »
    - Row +5 : Score supplémentaire remplacement
    - Row +6 : Tours au service Ligne 1 (services 1,5)
    - Row +7 : Tours au service Ligne 2 (services 2,6) + marqueurs « T »
    - Row +8 : Tours au service Ligne 3 (services 3,7) + scores timeout
    - Row +9 : Tours au service Ligne 4 (services 4,8) + scores timeout
    """

    # ---- Patterns regex ----
    PATTERNS = {
        'code_match': re.compile(r'Match:\s*(\w+)'),
        'journee': re.compile(r'Jour:\s*(\d+)'),
        'date': re.compile(
            r'(Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)'
            r'\s+(\d{1,2})\s+(\w+)\s+(\d{4})'
        ),
        'heure': re.compile(r'à\s+(\d{1,2})h(\d{2})'),
        'score_final': re.compile(r'(\d)/(\d)'),
        'joueur_ligne': re.compile(
            r'^(\d{1,2})\s+'
            r'([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇÑŒÆ\-\' ]+?)\s+'
            r'(\d{6,7})$'
        ),
        'set_marker': re.compile(r'S\s*E\s*T\s*(\d)'),
        'time_in_header': re.compile(r'(Début|Fin):\s*(\d{1,2}:\d{2})'),
        'timeout_score': re.compile(r'^(\d{1,2}):(\d{1,2})$'),
    }

    MOIS = {
        'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4,
        'mai': 5, 'juin': 6, 'juillet': 7, 'août': 8,
        'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12
    }

    TOTAL_FIELDS = 35
    ROWS_PER_SET = 10

    # ---- Propriétés de l'interface ----

    @property
    def name(self) -> str:
        return "MatchSheetParserV4"

    @property
    def version(self) -> str:
        return "4.1.0"

    # =====================================================================
    # Point d'entrée
    # =====================================================================

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

                # Identifier les tables par rôle
                tidx = self._identify_tables(tables)
                fields_count = 0

                # 1. Header
                header = self._parse_header(words, full_text)
                fields_count += sum(1 for v in header.values() if v)

                # 2. Noms d'équipes
                equipes_info = self._parse_equipes(tables, tidx, words)
                fields_count += sum(1 for v in equipes_info.values() if v)

                # 3. Résultat global
                resultat = self._parse_resultat(full_text)
                fields_count += sum(1 for v in resultat.values() if v)

                # 4. Match joué ?
                match_joue = self._is_match_played(resultat)

                # 5. Joueurs depuis la table roster
                joueurs_a, joueurs_b = self._parse_joueurs(tables, tidx)
                fields_count += len(joueurs_a) + len(joueurs_b)

                # 6. Libéros via mots positionnels
                liberos_a, liberos_b = self._parse_liberos_from_words(words)
                self._mark_liberos(joueurs_a, liberos_a)
                self._mark_liberos(joueurs_b, liberos_b)

                # 7. Officiels via mots positionnels
                officiels_a, officiels_b = self._parse_officiels_from_words(words)

                # 8. Capitaines (best-effort via table signatures)
                cap_a, cap_b = self._parse_capitaines(tables, tidx)
                self._mark_capitaine(joueurs_a, cap_a)
                self._mark_capitaine(joueurs_b, cap_b)

                # 9. Détails des sets
                sets_detailed = self._parse_all_sets(tables, tidx)

                # 10. Scores et stats par set depuis RESULTATS
                resultats_data = self._parse_resultats_table(tables, tidx)

                # 11. Construire les objets Set finaux
                sets = self._build_sets(
                    sets_detailed, resultats_data, resultat,
                    equipes_info.get("equipe_a", ""),
                    equipes_info.get("equipe_b", ""),
                )
                fields_count += len(sets) * 5

                # 12. Arbitres
                arbitres = self._parse_arbitres(tables, tidx, full_text)
                fields_count += len(arbitres)

                # 13. Sanctions
                sanctions = self._parse_sanctions(tables, tidx)

                # 14. Match final
                match = self._build_match(
                    header=header,
                    equipes_info=equipes_info,
                    resultat=resultat,
                    joueurs_a=joueurs_a,
                    joueurs_b=joueurs_b,
                    liberos_a=liberos_a,
                    liberos_b=liberos_b,
                    officiels_a=officiels_a,
                    officiels_b=officiels_b,
                    sets=sets,
                    sets_detailed=sets_detailed,
                    arbitres=arbitres,
                    sanctions=sanctions,
                    pdf_path=pdf_path,
                    match_joue=match_joue,
                )

                result.success = True
                result.match = match
                result.fields_extracted = fields_count
                result.fields_total = self.TOTAL_FIELDS

                if not match_joue:
                    result.add_warning("Match non joué ou annulé")

        except Exception as e:
            result.add_error(f"Erreur de parsing: {e}")
            import traceback
            result.add_error(traceback.format_exc())

        finally:
            result.parse_time_ms = (time.time() - start_time) * 1000
            self._record_result(result)

        return result

    # =====================================================================
    # Identification des tables
    # =====================================================================

    def _identify_tables(self, tables: list) -> dict:
        """Identifie les 5 tables principales du PDF FFVB.

        Returns
        -------
        dict
            'main'      → Table des sets 1/3/5 + sanctions/arbitres
            'secondary' → Table des sets 2/4
            'players'   → Table du roster
            'results'   → Table RESULTATS
            'signatures'→ Table des signatures
        """
        idx: dict = {
            'main': None,
            'secondary': None,
            'players': None,
            'results': None,
            'signatures': None,
        }

        # Pré-classifier par contenu
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

        # Les deux tables de sets restantes sont les plus grandes
        remaining = [
            t for t in tables
            if t and t not in (
                idx['results'], idx['players'], idx['signatures']
            )
        ]
        # Trier par taille décroissante (rows × cols)
        remaining.sort(
            key=lambda t: len(t) * max((len(r) for r in t if r), default=0),
            reverse=True,
        )

        if len(remaining) >= 1:
            idx['main'] = remaining[0]
        if len(remaining) >= 2:
            idx['secondary'] = remaining[1]

        return idx

    # =====================================================================
    # Header
    # =====================================================================

    def _parse_header(self, words: list, full_text: str) -> dict:
        header: dict = {k: None for k in [
            "ligue", "competition", "code_match", "journee",
            "date", "date_obj", "heure", "heure_obj",
            "lieu", "salle", "saison", "categorie", "genre",
        ]}

        # Code match
        if m := self.PATTERNS['code_match'].search(full_text):
            header["code_match"] = m.group(1)

        # Journée
        if m := self.PATTERNS['journee'].search(full_text):
            header["journee"] = m.group(1)

        # Ligue
        if m := re.search(
            r'Ligue\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ\-]+(?:-[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ]+)*)',
            full_text,
        ):
            header["ligue"] = f"Ligue {m.group(1)}"

        # Compétition (ex: "EMA - Elite Masculine A Jour: 15")
        if m := re.search(
            r'^([A-Z0-9]{2,8})\s*[-–]\s*(.+?)(?:\s+Match:|\s+Jour:|\s*$)',
            full_text,
            re.MULTILINE,
        ):
            header["competition"] = f"{m.group(1)} - {m.group(2).strip()}"

        # Date
        if dm := self.PATTERNS['date'].search(full_text):
            jour_sem, jour_s, mois_s, annee_s = dm.groups()
            jour = int(jour_s)
            annee = int(annee_s)
            header["date"] = f"{jour_sem} {jour} {mois_s.capitalize()} {annee}"
            mois_num = self.MOIS.get(mois_s.lower(), 1)
            try:
                header["date_obj"] = dt_date(annee, mois_num, jour)
            except ValueError:
                pass

        # Heure
        if hm := self.PATTERNS['heure'].search(full_text):
            h, mn = int(hm.group(1)), int(hm.group(2))
            header["heure"] = f"{h}h{mn:02d}"
            try:
                header["heure_obj"] = dt_time(h, mn)
            except ValueError:
                pass

        # Ville
        if vm := re.search(
            r'Ville:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ][A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ\s\-\']+)',
            full_text,
        ):
            ville = vm.group(1).strip()
            ville = re.split(
                r'\s+(Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)',
                ville,
            )[0].strip()
            header["lieu"] = ville

        # Salle
        if sm := re.search(
            r'Salle:\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9][A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9\s\-\'\.]+)',
            full_text,
        ):
            salle = sm.group(1).strip()
            salle = re.split(r'\s+(SENIOR|MASCULIN|FEMININ|FÉMININ)', salle)[0].strip()
            header["salle"] = salle

        # Genre / Catégorie
        upper = full_text.upper()
        if "MASCULIN" in upper:
            header["genre"] = "MASCULIN"
        elif "FÉMININ" in upper or "FEMININ" in upper:
            header["genre"] = "FEMININ"
        elif "MIXTE" in upper:
            header["genre"] = "MIXTE"

        if "SENIOR" in upper:
            header["categorie"] = "SENIOR"
        elif cm := re.search(r'(M\d{2}|U\d{2})', upper):
            header["categorie"] = cm.group(1)

        # Saison
        d = header.get("date_obj")
        if d:
            if d.month >= 9:
                header["saison"] = f"{d.year}-{d.year + 1}"
            else:
                header["saison"] = f"{d.year - 1}-{d.year}"

        return header

    # =====================================================================
    # Équipes
    # =====================================================================

    def _parse_equipes(self, tables: list, tidx: dict, words: list) -> dict:
        eq = {"equipe_a": None, "equipe_b": None}

        # Via table joueurs
        tbl = tidx.get('players')
        if tbl and len(tbl) >= 2:
            # Row 0 contient normalement les noms d'équipes pleins
            first_row = tbl[0]
            if first_row:
                # Les noms sont typiquement dans les colonnes 0 et 3
                for i, cell in enumerate(first_row):
                    if cell:
                        cs = str(cell).strip()
                        if len(cs) > 3 and not any(
                            kw in cs for kw in ['N°', 'Nom', 'Licence', 'LIBEROS']
                        ):
                            if not eq["equipe_a"]:
                                eq["equipe_a"] = cs
                            elif not eq["equipe_b"]:
                                eq["equipe_b"] = cs

        # Fallback : mots dans la bande 55-80px (zone noms d'équipes en en-tête)
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
                    eq["equipe_a"] = left.strip()
                if right and not eq["equipe_b"]:
                    eq["equipe_b"] = right.strip()

        return eq

    # =====================================================================
    # Résultat global
    # =====================================================================

    def _parse_resultat(self, full_text: str) -> dict:
        result = {"vainqueur": None, "score_final": None, "duree_totale": None}

        if vm := re.search(
            r'Vainqueur:\s*'
            r'([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9][A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9\s\-\'\.]+?)'
            r'\s+(\d)/(\d)',
            full_text,
        ):
            result["vainqueur"] = vm.group(1).strip()
            result["score_final"] = f"{vm.group(2)}/{vm.group(3)}"
        else:
            if v2 := re.search(
                r'Vainqueur:\s*'
                r'([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9]'
                r'[A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ0-9\s\-\'\.]*)',
                full_text,
            ):
                nom = re.sub(r'\s*\d/\d\s*$', '', v2.group(1)).strip()
                if nom and len(nom) > 3:
                    result["vainqueur"] = nom
            if sm := self.PATTERNS['score_final'].search(full_text):
                result["score_final"] = f"{sm.group(1)}/{sm.group(2)}"

        if dm := re.search(r'Durée\s*(\d+h\d+)', full_text):
            result["duree_totale"] = dm.group(1)
        elif dm2 := re.search(r"Durée.*?(\d+)'", full_text):
            result["duree_totale"] = dm2.group(1) + "'"

        return result

    def _is_match_played(self, resultat: dict) -> bool:
        if not resultat.get("vainqueur"):
            return False
        return resultat.get("score_final", "0/0") != "0/0"

    # =====================================================================
    # Joueurs (Table roster)
    # =====================================================================

    def _parse_joueurs(
        self, tables: list, tidx: dict
    ) -> tuple[list[Joueur], list[Joueur]]:
        """Parse les joueurs depuis la table roster."""
        joueurs_a: list[Joueur] = []
        joueurs_b: list[Joueur] = []

        tbl = tidx.get('players')
        if not tbl:
            # Fallback : chercher dans toutes les tables
            for t in tables:
                if t and any(
                    'Nom Prénom' in ' '.join(str(c) for c in r if c)
                    for r in (t[:3] if len(t) >= 3 else t) if r
                ):
                    tbl = t
                    break
        if not tbl:
            return joueurs_a, joueurs_b

        for row in tbl:
            if not row:
                continue
            row_text = ' '.join(str(c) for c in row if c)
            if any(kw in row_text for kw in [
                'Nom Prénom', 'Licence', 'LIBEROS', 'OFFICIELS', 'N°'
            ]):
                continue

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
                    m = self.PATTERNS['joueur_ligne'].match(line)
                    if m:
                        numero, nom_prenom, licence = m.group(1), m.group(2).strip(), m.group(3)
                        parts = nom_prenom.split()
                        nom = parts[0] if parts else nom_prenom
                        prenom = ' '.join(parts[1:]) if len(parts) > 1 else "Inconnu"
                        joueur = Joueur(
                            numero=numero,
                            nom=nom,
                            prenom=prenom,
                            licence=licence,
                        )
                        if cell_idx < 3:
                            joueurs_a.append(joueur)
                        else:
                            joueurs_b.append(joueur)

        return joueurs_a, joueurs_b

    # =====================================================================
    # Libéros (positionnement spatial)
    # =====================================================================

    def _parse_liberos_from_words(
        self, words: list
    ) -> tuple[list[Joueur], list[Joueur]]:
        """Extrait les libéros via leur position spatiale sous le header LIBEROS.

        Les libéros sont situés dans la partie droite du PDF, sous la zone
        roster des joueurs, entre les headers « LIBEROS » et « OFFICIELS ».
        Team A occupe la moitié gauche (x < 700), Team B la moitié droite.
        """
        liberos_a: list[Joueur] = []
        liberos_b: list[Joueur] = []

        # Header LIBEROS (dans la zone droite x > 500)
        lib_header = next(
            (w for w in words if w['text'].upper() == 'LIBEROS' and w['x0'] > 500),
            None,
        )
        if not lib_header:
            return liberos_a, liberos_b

        # Header suivant (OFFICIELS) pour borner y
        off_header = next(
            (w for w in words if w['text'].upper() == 'OFFICIELS' and w['x0'] > 500),
            None,
        )
        y_start = lib_header['bottom']
        y_end = off_header['top'] if off_header else y_start + 30

        # Mots dans la zone libéros
        zone_words = [
            w for w in words
            if y_start - 2 <= w['top'] <= y_end and w['x0'] > 500
        ]
        zone_words.sort(key=lambda w: (w['top'], w['x0']))

        # Seuil x pour séparer les deux équipes
        x_thresh = 700

        # Regrouper par ligne (y ± 3px)
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
            numero, licence, name_parts = None, None, []
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
            return Joueur(
                numero=numero,
                nom=name_parts[0],
                prenom=' '.join(name_parts[1:]) or "Inconnu",
                licence=licence,
                est_libero=True,
            )

        for key in sorted(lines_a):
            j = _build_joueur(lines_a[key])
            if j:
                liberos_a.append(j)
        for key in sorted(lines_b):
            j = _build_joueur(lines_b[key])
            if j:
                liberos_b.append(j)

        return liberos_a, liberos_b

    @staticmethod
    def _mark_liberos(joueurs: list[Joueur], liberos: list[Joueur]) -> None:
        lib_nums = {l.numero for l in liberos}
        lib_ids = {(l.numero, l.licence) for l in liberos}
        for j in joueurs:
            if (j.numero, j.licence) in lib_ids or j.numero in lib_nums:
                j.est_libero = True

    # =====================================================================
    # Officiels (positionnement spatial)
    # =====================================================================

    def _parse_officiels_from_words(
        self, words: list
    ) -> tuple[list[OfficielInfo], list[OfficielInfo]]:
        """Extrait les officiels d'équipe sous le header OFFICIELS.

        Les rôles sont indiqués par un préfixe :
        - EA = Entraîneur (coach)
        - EB = Entraîneur adjoint ou second officiel

        La lettre finale (A/B) peut désigner l'équipe ou le rang, selon
        le contexte. On utilise la position x pour attribuer l'officiel
        à la bonne équipe (gauche = A, droite = B).
        """
        off_a: list[OfficielInfo] = []
        off_b: list[OfficielInfo] = []

        header = next(
            (w for w in words if w['text'].upper() == 'OFFICIELS' and w['x0'] > 500),
            None,
        )
        if not header:
            return off_a, off_b

        y_start = header['bottom'] - 2
        # Limite basse : SIGNATURES ou +40px
        sig = next(
            (w for w in words if w['text'].upper() in ('SIGNATURES', 'Capitaine') and w['x0'] > 500),
            None,
        )
        y_end = sig['top'] if sig else y_start + 40

        # Filtrer x > 570 pour exclure les données RESULTATS qui trainent
        # à x=500-555 (colonnes Set/P/G/R/T du tableau RESULTATS)
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

        def _build_off(line_words: list, side: str) -> Optional[OfficielInfo]:
            if not line_words:
                return None
            texts = [w['text'] for w in sorted(line_words, key=lambda w: w['x0'])]
            role, licence = None, None
            name_parts = []
            for t in texts:
                t_clean = t.strip()
                if not t_clean:
                    continue
                if t_clean.upper() in ('EA', 'EB', 'MA', 'MB', 'KA', 'KB'):
                    role = t_clean.upper()
                elif t_clean.isdigit() and len(t_clean) >= 6:
                    licence = t_clean
                elif t_clean.upper() not in ('OFFICIELS', 'SIGNATURES'):
                    name_parts.append(t_clean)
            if not role or not name_parts:
                return None
            return OfficielInfo(
                role=role,
                nom=name_parts[0],
                prenom=' '.join(name_parts[1:]) if len(name_parts) > 1 else "",
                licence=licence or "",
            )

        for key in sorted(lines_left):
            o = _build_off(lines_left[key], 'A')
            if o:
                off_a.append(o)
        for key in sorted(lines_right):
            o = _build_off(lines_right[key], 'B')
            if o:
                off_b.append(o)

        return off_a, off_b

    # =====================================================================
    # Capitaines (via table Signatures, best-effort)
    # =====================================================================

    def _parse_capitaines(
        self, tables: list, tidx: dict
    ) -> tuple[Optional[str], Optional[str]]:
        """Parse les numéros de capitaine depuis la table SIGNATURES.

        NOTE : Les cercles autour des numéros ne sont PAS présents
        dans les PDF numériques FFVB.  On se rabat sur la table de
        signatures qui contient « Capitaine N° ».
        """
        cap_a, cap_b = None, None

        tbl = tidx.get('signatures')
        sig_tables = [tbl] if tbl else tables

        for table in sig_tables:
            if not table:
                continue
            for i, row in enumerate(table):
                if not row:
                    continue
                row_text = ' '.join(str(c) for c in row if c)
                if 'Capitaine' not in row_text:
                    continue

                # La ligne suivante peut contenir les N° de capitaine
                if i + 1 < len(table):
                    nr = table[i + 1]
                    if nr:
                        mid = len(nr) // 2
                        for j, cell in enumerate(nr):
                            if cell:
                                cs = str(cell).strip()
                                if cs.isdigit() and len(cs) <= 2:
                                    if j < mid and not cap_a:
                                        cap_a = cs
                                    elif j >= mid and not cap_b:
                                        cap_b = cs

                # Ou bien les N° sont dans la même ligne
                # Pattern « Capitaine N° X … Capitaine N° Y »
                parts = re.findall(r'Capitaine\s+N°\s*(\d{1,2})', row_text)
                if len(parts) >= 2:
                    cap_a = cap_a or parts[0]
                    cap_b = cap_b or parts[1]
                elif len(parts) == 1 and not cap_a:
                    cap_a = parts[0]

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

    def _parse_all_sets(self, tables: list, tidx: dict) -> list[SetDetailedInfo]:
        sets: list[SetDetailedInfo] = []

        for key in ('main', 'secondary'):
            tbl = tidx.get(key)
            if not tbl:
                continue
            sections = self._find_set_sections(tbl)
            for set_num, start_row in sections:
                sd = self._parse_set_section(tbl, start_row, set_num)
                if sd:
                    sets.append(sd)

        sets.sort(key=lambda s: s.numero)
        return sets

    def _find_set_sections(self, table: list) -> list[tuple[int, int]]:
        """Trouve les sections de set via le marqueur S-E-T-n."""
        sections = []
        for i, row in enumerate(table):
            if not row:
                continue
            for cell in row:
                if not cell:
                    continue
                cs = str(cell).replace('\n', ' ').strip()
                if m := self.PATTERNS['set_marker'].search(cs):
                    sections.append((int(m.group(1)), i))
                    break
        return sections

    def _parse_set_section(
        self, table: list, start: int, set_num: int
    ) -> Optional[SetDetailedInfo]:
        sd = SetDetailedInfo(numero=set_num)

        if start + self.ROWS_PER_SET > len(table):
            return sd

        # Row +0 : header (heures, service)
        self._parse_set_header_row(table[start], sd, table)

        # Row +1 : trouver les colonnes de position (I..VI)
        pos_a, pos_b = self._find_position_columns(table[start + 1])

        # Row +2 : formations de départ (left / right, pas encore A / B)
        sd.formation_left = self._extract_formation(table[start + 2], pos_a)
        sd.formation_right = self._extract_formation(table[start + 2], pos_b)

        # Rows +3..+5 : remplacements
        self._parse_substitutions(table, start, pos_a, pos_b, sd)

        # Rows +6..+9 : tours au service + timeouts
        self._parse_service_rows(table, start, sd)

        return sd

    # -- set header --------------------------------------------------------

    def _parse_set_header_row(
        self, row: list, sd: SetDetailedInfo, table: list
    ) -> None:
        """Extrait heures début/fin, noms d'équipes et service initial.

        La cellule de gauche contient « TEAM_NAME Début: HH:MM S »
        et celle de droite « TEAM_NAME Fin: HH:MM R »  (ou inversé).
        """
        if not row:
            return

        info_cells: list[tuple[int, str]] = []

        for i, cell in enumerate(row):
            if not cell:
                continue
            cs = str(cell).strip()
            if len(cs) < 5:
                continue
            if self.PATTERNS['time_in_header'].search(cs):
                info_cells.append((i, cs))

        if not info_cells:
            return

        # Trier par colonne pour distinguer gauche / droite
        info_cells.sort(key=lambda x: x[0])
        n_cols = len(row)
        mid = n_cols // 2

        for col_i, text in info_cells:
            side = 'left' if col_i < mid else 'right'

            # Extraire le nom d'équipe (tout avant Début: ou Fin:)
            team_name = re.split(r'\s+(Début|Fin):', text)[0].strip()
            if side == 'left':
                sd.left_team_name = team_name
            else:
                sd.right_team_name = team_name

            if tm := self.PATTERNS['time_in_header'].search(text):
                if tm.group(1) == 'Début':
                    sd.heure_debut = tm.group(2)
                elif tm.group(1) == 'Fin':
                    sd.heure_fin = tm.group(2)

            # Service : S = service, R = réception
            if text.rstrip().endswith(' S'):
                sd.service_initial_side = side
            elif text.rstrip().endswith(' R'):
                sd.service_initial_side = 'right' if side == 'left' else 'left'

    # -- colonnes de position ----------------------------------------------

    def _find_position_columns(
        self, header_row: Optional[list]
    ) -> tuple[list[int], list[int]]:
        """Trouve les indices de colonnes pour I .. VI dans les deux moitiés.

        Utilise la détection de gap (plus grand écart de colonnes entre
        deux position-headers consécutifs) pour séparer gauche/droite,
        plutôt qu'un simple milieu qui peut mal tomber.
        """
        if not header_row:
            return [], []

        n = len(header_row)
        roman_map = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6}

        hits: list[tuple[int, int]] = []
        for i, cell in enumerate(header_row):
            if cell:
                cs = str(cell).strip()
                if cs in roman_map:
                    hits.append((i, roman_map[cs]))

        if len(hits) >= 12:
            # Trier par index de colonne
            hits.sort(key=lambda x: x[0])
            # Trouver le plus grand gap entre colonnes consécutives
            max_gap, split_idx = 0, 5
            for k in range(len(hits) - 1):
                gap = hits[k + 1][0] - hits[k][0]
                if gap > max_gap:
                    max_gap = gap
                    split_idx = k
            left = sorted(hits[:split_idx + 1], key=lambda x: x[1])
            right = sorted(hits[split_idx + 1:], key=lambda x: x[1])
            return [i for i, _ in left[:6]], [i for i, _ in right[:6]]

        # Fallback heuristique
        if n >= 40:
            return [13, 15, 18, 20, 22, 24], [31, 33, 35, 37, 39, 41]
        elif n >= 25:
            return [1, 3, 5, 7, 9, 11], [14, 16, 18, 20, 22, 24]
        return [], []

    # -- formations --------------------------------------------------------

    @staticmethod
    def _extract_formation(
        row: Optional[list], cols: list[int]
    ) -> Optional[Formation]:
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
            position_1=vals[0],
            position_2=vals[1],
            position_3=vals[2],
            position_4=vals[3],
            position_5=vals[4] if len(vals) > 4 else None,
            position_6=vals[5] if len(vals) > 5 else None,
        )

    # -- remplacements (rows +3..+5) ---------------------------------------

    def _parse_substitutions(
        self,
        table: list,
        start: int,
        pos_a: list[int],
        pos_b: list[int],
        sd: SetDetailedInfo,
    ) -> None:
        n = len(table)
        sub_row = table[start + 3] if start + 3 < n else None
        score_row = table[start + 4] if start + 4 < n else None
        score2_row = table[start + 5] if start + 5 < n else None

        if not sub_row:
            return

        for cols, changes, form in [
            (pos_a, sd.changements_left, sd.formation_left),
            (pos_b, sd.changements_right, sd.formation_right),
        ]:
            for pos_idx, col in enumerate(cols):
                if col >= len(sub_row) or not sub_row[col]:
                    continue
                entrant = str(sub_row[col]).strip()
                if not entrant or not entrant.isdigit():
                    continue

                # Le sortant est le joueur qui était à cette position
                sortant = ""
                if form:
                    form_list = form.as_list()
                    if pos_idx < len(form_list) and form_list[pos_idx]:
                        sortant = form_list[pos_idx]

                # Score au moment du remplacement
                sa, sb = None, None
                for s_row in (score_row, score2_row):
                    if not s_row or col >= len(s_row) or not s_row[col]:
                        continue
                    sm = self.PATTERNS['timeout_score'].match(str(s_row[col]).strip())
                    if sm:
                        sa, sb = int(sm.group(1)), int(sm.group(2))
                        break

                changes.append(Changement(
                    joueur_entrant=entrant,
                    joueur_sortant=sortant,
                    position=pos_idx + 1,
                    score_a=sa,
                    score_b=sb,
                ))

    # -- tours au service / timeouts (rows +6..+9) -------------------------

    def _parse_service_rows(
        self,
        table: list,
        start: int,
        sd: SetDetailedInfo,
    ) -> None:
        """Parse les 4 lignes de tours au service pour timeouts."""
        n = len(table)

        for offset in range(4):
            idx = start + 6 + offset
            if idx >= n:
                break
            row = table[idx]
            if not row:
                continue

            n_c = len(row)
            # Utiliser le gap des colonnes de position pour déterminer le mid
            # entre les deux équipes (même logique que _find_position_columns)
            # On utilise le milieu entre la dernière colonne left et la première right
            # En fallback, on utilise la moitié des colonnes
            if hasattr(sd, '_timeout_mid'):
                row_mid = sd._timeout_mid
            else:
                # Heuristique basée sur le nombre de colonnes
                row_mid = n_c * 55 // 100  # légèrement à droite du centre

            for i, cell in enumerate(row):
                if not cell:
                    continue
                cs = str(cell).strip()

                if cs == 'T':
                    side = 'left' if i < row_mid else 'right'

                    # Score du timeout : même colonne, lignes suivantes
                    sa, sb = None, None
                    for d in range(1, 3):
                        nxt = idx + d
                        if nxt >= n:
                            break
                        nr = table[nxt]
                        if not nr or i >= len(nr) or not nr[i]:
                            continue
                        sm = self.PATTERNS['timeout_score'].match(
                            str(nr[i]).strip()
                        )
                        if sm:
                            sa, sb = int(sm.group(1)), int(sm.group(2))
                            break

                    # Only add timeout if a score was actually found
                    if sa is not None:
                        to = TimeOut(score_a=sa, score_b=sb or 0)
                        if side == 'left':
                            sd.timeouts_left.append(to)
                        else:
                            sd.timeouts_right.append(to)

    # =====================================================================
    # RESULTATS table
    # =====================================================================

    def _parse_resultats_table(
        self, tables: list, tidx: dict
    ) -> list[dict]:
        """Parse scores et stats par set depuis la table RESULTATS.

        Structure typique (12 rows) :

        Row 0 : « RESULTATS »
        Row 1 : « Equipe A … Equipe B »
        Row 2 : T  R  G  P  | Durée par set |  P  G  R  T
        Row 3..7 : Sets 1..5
        Row 8 : Totaux
        Row 9-10 : Début / Fin / Durée
        Row 11 : « Vainqueur: NOM SCORE »

        La colonne 4 de la row 3 contient un texte multiline avec toutes
        les durées : « 1 24'\\n2 26'\\n3 28'\\n4 28'\\n5 17' ».
        """
        tbl = tidx.get('results')
        if not tbl:
            return []

        # Durées par set (parsées depuis la cellule multiline)
        durations: dict[int, int] = {}
        if len(tbl) > 3 and tbl[3] and len(tbl[3]) > 4 and tbl[3][4]:
            for dm in re.finditer(r'(\d)\s+(\d+)\'', str(tbl[3][4])):
                durations[int(dm.group(1))] = int(dm.group(2))

        data: list[dict] = []
        set_num = 0

        for row_idx in range(3, min(8, len(tbl))):
            row = tbl[row_idx]
            if not row:
                continue

            # Vérifier qu'on a des données numériques
            num_count = sum(
                1 for c in row
                if c is not None and str(c).strip().replace("'", "").isdigit()
            )
            if num_count < 3:
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

        return data

    @staticmethod
    def _safe_int(row: list, idx: int) -> Optional[int]:
        if idx >= len(row) or row[idx] is None:
            return None
        s = str(row[idx]).strip().replace("'", "")
        return int(s) if s.isdigit() else None

    # =====================================================================
    # Construction des objets Set
    # =====================================================================

    def _build_sets(
        self,
        detailed: list[SetDetailedInfo],
        resultats: list[dict],
        resultat: dict,
        nom_a: str,
        nom_b: str,
    ) -> list[Set]:
        """Construit les objets Set en mappant left/right → A/B **par set**.

        Chaque table de set peut avoir un ordre d'équipes différent
        (Table 0 et Table 1 ont souvent les équipes inversées).
        On utilise le ``left_team_name`` de chaque set pour déterminer
        la correspondance locale.
        """
        # Nombre de sets
        nb = 0
        if sc := resultat.get("score_final"):
            try:
                a, b = sc.split("/")
                nb = int(a) + int(b)
            except Exception:
                pass
        if not nb:
            nb = max(len(detailed), len(resultats), 0)

        sets: list[Set] = []
        for i in range(nb):
            sn = i + 1
            det = next((s for s in detailed if s.numero == sn), None)
            res = next((r for r in resultats if r.get('numero') == sn), None)

            score_a = res.get('points_a') if res else None
            score_b = res.get('points_b') if res else None

            duree = None
            if res and res.get('duree_minutes'):
                duree = res['duree_minutes']
            elif det and det.duree_minutes:
                duree = det.duree_minutes

            debut_t = self._parse_time(det.heure_debut) if det else None
            fin_t = self._parse_time(det.heure_fin) if det else None

            # --- Mapping left/right → A/B per set ---
            swap = False
            if det and det.left_team_name:
                swap = self._team_name_matches(det.left_team_name, nom_b)

            if det and not swap:
                form_a = det.formation_left
                form_b = det.formation_right
                to_a = det.timeouts_left
                to_b = det.timeouts_right
                srv_side = det.service_initial_side
                srv = 'A' if srv_side == 'left' else ('B' if srv_side == 'right' else None)
            elif det:
                # swap: left=B, right=A
                form_a = det.formation_right
                form_b = det.formation_left
                to_a = det.timeouts_right
                to_b = det.timeouts_left
                srv_side = det.service_initial_side
                srv = 'B' if srv_side == 'left' else ('A' if srv_side == 'right' else None)
            else:
                form_a, form_b = None, None
                to_a, to_b = [], []
                srv = None

            s = Set(
                numero=sn,
                score_a=score_a,
                score_b=score_b,
                debut=debut_t,
                fin=fin_t,
                duree_minutes=duree,
                service_initial=srv,
                formation_a=form_a,
                formation_b=form_b,
                timeouts_a=to_a,
                timeouts_b=to_b,
            )
            sets.append(s)

        return sets

    @staticmethod
    def _team_name_matches(truncated: str, full_name: str) -> bool:
        """Vérifie si un nom tronqué correspond à un nom complet d'équipe."""
        t = truncated.upper().strip()
        f = full_name.upper().strip()
        if not t or not f:
            return False
        # Correspondance par préfixe (les headers de set tronquent les noms)
        return f.startswith(t) or t.startswith(f[:15]) or t[:10] in f

    @staticmethod
    def _parse_time(val: Optional[str]) -> Optional[dt_time]:
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

    def _parse_arbitres(
        self, tables: list, tidx: dict, full_text: str
    ) -> list[Arbitre]:
        arbitres: list[Arbitre] = []

        role_map = {
            '1er': RoleArbitre.PREMIER,
            '2ème': RoleArbitre.SECOND,
            'Marqueur': RoleArbitre.MARQUEUR,
            'Marq.Ass.': RoleArbitre.MARQUEUR,
            'R.Salle': RoleArbitre.JUGE_LIGNE,
        }

        # Chercher dans la table principale (arbitres en fin de table)
        search_tables = [tidx['main']] if tidx.get('main') else tables
        for table in search_tables:
            if not table:
                continue
            for row in table:
                if not row:
                    continue
                for role_text, role_enum in role_map.items():
                    role_idx = None
                    for k, cell in enumerate(row):
                        if cell and str(cell).strip() == role_text:
                            role_idx = k
                            break
                    if role_idx is None:
                        continue

                    nom_complet, licence, ligue = None, None, None
                    for j in range(role_idx + 1, min(role_idx + 20, len(row))):
                        cell = row[j]
                        if not cell:
                            continue
                        cs = str(cell).strip()
                        if not cs:
                            continue
                        if cs.isdigit() and 6 <= len(cs) <= 7:
                            licence = cs
                        elif cs.isupper() and 2 <= len(cs) <= 4 and cs.isalpha():
                            ligue = cs
                        elif ' ' in cs and len(cs) > 3 and cs not in (
                            'NOM Prénom', 'Nom Prénom'
                        ):
                            nom_complet = cs
                            break

                    if nom_complet:
                        parts = nom_complet.split()
                        nom = parts[0]
                        prenom = ' '.join(parts[1:]) or None
                        if not any(
                            a.nom == nom and a.role == role_enum
                            for a in arbitres
                        ):
                            arbitres.append(Arbitre(
                                nom=nom,
                                prenom=prenom,
                                role=role_enum,
                                licence=licence,
                                ligue=ligue,
                            ))

        return arbitres

    # =====================================================================
    # Sanctions
    # =====================================================================

    def _parse_sanctions(self, tables: list, tidx: dict) -> list[Sanction]:
        """Parse les sanctions.

        NOTE : dans les PDF numériques FFVB la section sanctions est
        systématiquement vide (prévue pour annotation manuelle papier).
        Le code est néanmoins maintenu pour les rares cas éventuels.
        """
        sanctions: list[Sanction] = []

        tbl = tidx.get('main')
        if not tbl:
            return sanctions

        in_sanctions = False
        for row in tbl:
            if not row:
                continue
            rt = ' '.join(str(c) for c in row if c).upper()

            if 'SANCTIONS' in rt:
                in_sanctions = True
                continue

            if in_sanctions:
                # Quand on atteint la section arbitres, on arrête
                if any(kw in rt for kw in ['1ER', '2ÈME', 'MARQUEUR', 'ARBITRE']):
                    break

                mid = len(row) // 2
                for j, cell in enumerate(row):
                    if not cell:
                        continue
                    cs = str(cell).strip()
                    if not cs or len(cs) < 3:
                        continue

                    equipe = 'A' if j < mid else 'B'

                    # Chercher un numéro de joueur + type sanction
                    sm = re.search(
                        r'(\d{1,2})\s+(\d)\s+.*?(\d+)-(\d+)',
                        cs,
                    )
                    if sm:
                        sanctions.append(Sanction(
                            type=TypeSanction.AVERTISSEMENT,
                            set_numero=int(sm.group(2)),
                            equipe=equipe,
                            joueur_numero=sm.group(1),
                            score_a=int(sm.group(3)),
                            score_b=int(sm.group(4)),
                        ))

        return sanctions

    # =====================================================================
    # Construction Match final
    # =====================================================================

    def _build_match(
        self,
        header: dict,
        equipes_info: dict,
        resultat: dict,
        joueurs_a: list[Joueur],
        joueurs_b: list[Joueur],
        liberos_a: list[Joueur],
        liberos_b: list[Joueur],
        officiels_a: list[OfficielInfo],
        officiels_b: list[OfficielInfo],
        sets: list[Set],
        sets_detailed: list[SetDetailedInfo],
        arbitres: list[Arbitre],
        sanctions: list[Sanction],
        pdf_path: Path,
        match_joue: bool,
    ) -> Match:
        nom_a = equipes_info.get("equipe_a") or "Équipe A"
        nom_b = equipes_info.get("equipe_b") or "Équipe B"
        if len(nom_a) < 2:
            nom_a = "Équipe A"
        if len(nom_b) < 2:
            nom_b = "Équipe B"

        # ---- Le mapping left/right → A/B est déjà fait dans _build_sets ----

        # Officiels → entraîneur / assistant
        entr_a = self._officiel_name(officiels_a, 'EA')
        asst_a = self._officiel_name(officiels_a, 'EB')
        entr_b = self._officiel_name(officiels_b, 'EA')
        asst_b = self._officiel_name(officiels_b, 'EB')

        equipe_a = Equipe(
            nom=nom_a,
            joueurs=joueurs_a,
            liberos=liberos_a,
            entraineur=entr_a,
            assistant=asst_a,
        )
        equipe_b = Equipe(
            nom=nom_b,
            joueurs=joueurs_b,
            liberos=liberos_b,
            entraineur=entr_b,
            assistant=asst_b,
        )

        sets_a, sets_b = 0, 0
        if sc := resultat.get("score_final"):
            try:
                a, b = sc.split("/")
                sets_a, sets_b = int(a), int(b)
            except Exception:
                pass

        genre = self._try_enum(Genre, header.get("genre"))
        categorie = self._try_enum(Categorie, header.get("categorie"))

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
            parsed_at=datetime.now(),
        )

    @staticmethod
    def _officiel_name(officials: list[OfficielInfo], role: str) -> Optional[str]:
        for o in officials:
            if o.role == role:
                return f"{o.nom} {o.prenom}".strip() or None
        return None

    @staticmethod
    def _detect_team_swap(
        sets_detailed: list[SetDetailedInfo],
        nom_a: str,
        nom_b: str,
    ) -> bool:
        """Détermine si left/right dans les set tables doit être inversé.

        Retourne True si le côté gauche du tableau correspond à equipe_b
        (et donc il faut swap pour que formation_a = equipe_a).
        """
        for sd in sets_detailed:
            left = sd.left_team_name
            if not left:
                continue

            left_u = left.upper()
            nom_a_u = nom_a.upper()
            nom_b_u = nom_b.upper()

            # Comparer : le nom_left commence-t-il par le même préfixe qu'un
            # des noms d'équipe ? (les noms dans les headers sont tronqués)
            if nom_a_u.startswith(left_u) or left_u.startswith(nom_a_u[:15]):
                return False  # left = A, pas de swap
            if nom_b_u.startswith(left_u) or left_u.startswith(nom_b_u[:15]):
                return True   # left = B, swap nécessaire

            # Check via substring matching
            if left_u[:10] in nom_a_u:
                return False
            if left_u[:10] in nom_b_u:
                return True

        return False  # par défaut, pas de swap

    @staticmethod
    def _try_enum(enum_cls, val):
        if not val:
            return None
        try:
            return enum_cls(val)
        except (ValueError, KeyError):
            return None
