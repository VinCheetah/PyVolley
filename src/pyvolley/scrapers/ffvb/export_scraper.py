"""
Scraper basé sur l'export CSV de la FFVB (``vbspo_calendrier_export.php``).

C'est la source principale de données du pipeline Phase 1. Une seule requête
HTTP par entité retourne toutes les données structurées (40 colonnes) :
- Code match, journée, date, heure, salle
- Équipes avec numéro de club FFVB (identification fiable)
- Scores par set + total points
- Arbitres avec licence, ligue et comité départemental
- Juges de ligne, marqueurs
- Vainqueur, forfait

Format de l'export (vérifié empiriquement 2026-03-06) :
- Encodage : latin-1 (ISO-8859-1)
- Séparateur : point-virgule (``;``)
- Première ligne : en-têtes (40 colonnes)
- Dates au format ``YYYY-MM-DD``
- Scores par set dans une colonne unique ``Score`` : ``25-18,16-25,25-20``
- Score sets dans la colonne ``Set`` : `` 3/1`` (avec espace initial)
- Forfait indiqué par ``P`` dans le score sets : ``3/P`` ou ``P/3``
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlencode, urljoin

from pyvolley.scrapers.http_client import HttpClient
from pyvolley.scrapers.ffvb.plausibility import (
    ScrapePlausibilityEngine,
    summarize_scrape_issues,
)
from pyvolley.shared.match_status import (
    compute_match_played,
    normalize_score_sets,
    score_sets_indicates_played,
)

logger = logging.getLogger(__name__)

# =====================================================================
# Colonnes de l'export CSV (indices zéro-based, séparateur ;)
# Vérifiées empiriquement le 2026-03-06 sur ABCCS saison 2025/2026
# =====================================================================
COL_ENTITE = 0        # Entité
COL_JOURNEE = 1       # Jo
COL_MATCH = 2         # Match (code match, ex: "2FA002", "EMA051")
COL_DATE = 3          # Date (YYYY-MM-DD)
COL_HEURE = 4         # Heure (HH:MM)
COL_EQA_NO = 5        # EQA_no (N° club A, ex: "0132380")
COL_EQA_NOM = 6       # EQA_nom (Équipe A)
COL_EQB_NO = 7        # EQB_no (N° club B)
COL_EQB_NOM = 8       # EQB_nom (Équipe B)
COL_SET = 9           # Set  (" 3/1", " 0/3", " 3/P", "")
COL_SCORE = 10        # Score ("25-18,16-25,25-20" — scores détaillés par set)
COL_TOTAL = 11        # Total ("75-53" — total points)
COL_SALLE = 12        # Salle
COL_ARB1_LIC = 13     # Arb1_Lic
COL_ARB1_NOM = 14     # Arb1_Nom
COL_ARB1_LR = 15      # Arb1_LR (ligue régionale)
COL_ARB1_CD = 16      # Arb1_CD (comité départemental)
COL_ARB2_LIC = 17     # Arb2_Lic
COL_ARB2_NOM = 18     # Arb2_Nom
COL_ARB2_LR = 19      # Arb2_LR
COL_ARB2_CD = 20      # Arb2_CD
COL_JDL1_LIC = 21     # Jdl1_Lic
COL_JDL1_NOM = 22     # Jdl1_Nom
COL_JDL2_LIC = 23     # Jdl2_Lic
COL_JDL2_NOM = 24     # Jdl2_Nom
COL_JDL3_LIC = 25     # Jdl3_Lic
COL_JDL3_NOM = 26     # Jdl3_Nom
COL_JDL4_LIC = 27     # Jdl4_Lic
COL_JDL4_NOM = 28     # Jdl4_Nom
COL_MRQ1_LIC = 29     # Mrq1_Lic
COL_MRQ1_NOM = 30     # Mrq1_Nom
COL_MRQ2_LIC = 31     # Mrq2_Lic
COL_MRQ2_NOM = 32     # Mrq2_Nom
COL_SUP_LIC = 33      # Sup_Lic
COL_SUP_NOM = 34      # Sup_Nom
COL_SLNV_LIC = 35     # Slnv_Lic
COL_SLNV_NOM = 36     # Slnv_Nom
COL_VID_LIC = 37      # Vid_Lic
COL_VID_NOM = 38       # Vid_Nom
# Colonne 39 : vide (trailing ;)

MIN_COLUMNS = 13  # Minimum requis pour un export valide (jusqu'à Salle)

# Timeout plus long pour l'export CSV (le serveur peut mettre > 45s)
EXPORT_TIMEOUT = 90


@dataclass
class ArbitreInfo:
    """Informations sur un arbitre depuis l'export CSV."""
    licence: str
    nom: str
    ligue: Optional[str] = None
    comite_departemental: Optional[str] = None


@dataclass
class ExportMatchInfo:
    """Match enrichi extrait de l'export CSV FFVB.

    Contient toutes les métadonnées disponibles dès la Phase 1
    (avant le parsing PDF).
    """
    code_match: str
    entite_code: str
    entite_nom: Optional[str] = None  # Nom de l'entité (enrichi)
    entite_type: Optional[str] = None  # Type d'entité (enrichi)
    poule_code: str = ""  # Déduit du code_match (ex: "PMA" de "PMAA001")
    poule_code_ffvb: Optional[str] = None  # Code FFVB résolu (ex: "DSF" pour "DSFA")
    saison: str = ""
    journee: Optional[str] = None

    # Équipes (avec codes club FFVB)
    equipe_a_nom: Optional[str] = None
    equipe_b_nom: Optional[str] = None
    club_a_code_ffvb: Optional[str] = None  # "0590005"
    club_b_code_ffvb: Optional[str] = None

    # Résultat
    sets: list[tuple[int, int]] = field(default_factory=list)
    score_sets: Optional[str] = None  # "3/1"
    vainqueur: Optional[str] = None  # Nom de l'équipe gagnante
    forfait: bool = False
    match_joue: bool = False

    # Métadonnées
    date_match: Optional[date] = None
    heure: Optional[str] = None
    salle: Optional[str] = None

    # Arbitrage
    arbitres: list[ArbitreInfo] = field(default_factory=list)

    # Officiels de table
    juges_de_ligne: list[str] = field(default_factory=list)
    marqueurs: list[str] = field(default_factory=list)

    # URL de la feuille de match (construite automatiquement)
    feuille_match_url: Optional[str] = None

    # Contrôles de plausibilité appliqués au niveau scraper
    plausibility_issues: list[dict[str, object]] = field(default_factory=list)
    plausibility_summary: dict[str, object] = field(default_factory=dict)

    # Phase aller/retour
    phase_aller_retour: Optional[str] = None     # "ALLER", "RETOUR", None

    # ── Métadonnées de compétition (enrichies par competition_info) ──
    competition_nom: Optional[str] = None       # "ELITE MASCULINE - POULE A"
    competition_groupe: Optional[str] = None     # "ELITE MASCULINE" (heading parent)
    genre: Optional[str] = None                  # "MASCULIN", "FEMININ", "MIXTE"
    categorie_age: Optional[str] = None          # "SENIOR", "M18", "M15", "M13", ...
    niveau: Optional[str] = None                 # "ELITE", "NATIONALE", "REGIONALE", ...
    division: Optional[str] = None               # "1", "2", "3"
    division_code: Optional[str] = None          # Code division jeune (CMX, JFX, BMX...)
    type_competition: Optional[str] = None       # "CHAMPIONNAT", "COUPE", "TOURNOI"
    phase: Optional[str] = None                  # "POULE", "PLAY_OFF", "BARRAGE", ...
    poule_lettre: Optional[str] = None           # "A", "B", "C", ...

    @property
    def sets_equipe_a(self) -> int:
        """Nombre de sets gagnés par l'équipe A."""
        return sum(1 for sa, sb in self.sets if sa > sb)

    @property
    def sets_equipe_b(self) -> int:
        """Nombre de sets gagnés par l'équipe B."""
        return sum(1 for sa, sb in self.sets if sb > sa)


def _extract_poule_code(code_match: str) -> str:
    """Extrait le code de poule du code match.

    Le code match est de la forme ``XXXNNN`` où :
    - XXX = code poule (2-4 caractères alphanumériques)
    - NNN = numéro de match (3 chiffres)

    La stratégie : on sépare le préfixe alphanumérique du suffixe
    numérique de 3 chiffres. On ne peut PAS utiliser un quantificateur
    lazy car les codes peuvent contenir des chiffres (ex. "CX1001"
    doit donner "CX1", pas "CX").

    Exemples :
      - "PMAA001" → "PMAA"  (4 lettres + 001)
      - "EMA051"  → "EMA"   (3 lettres + 051)
      - "1FA008"  → "1FA"   (1 chiffre + 2 lettres + 008)
      - "SN1A003" → "SN1A"  (2 lettres + 1 chiffre + 1 lettre + 003)
      - "CX1001"  → "CX1"   (2 lettres + 1 chiffre + 001)
      - "BG5006"  → "BG5"   (2 lettres + 1 chiffre + 006)
    """
    # Séparer le suffixe numérique (exactement 3 chiffres en fin de match code)
    match = re.match(r'^(.+?)(\d{3})$', code_match)
    if match:
        return match.group(1)
    # Fallback: prendre les 3 premiers caractères
    return code_match[:3] if len(code_match) >= 3 else code_match


def normalize_poule_code(poule_code: str) -> tuple[str, Optional[str]]:
    """Normalise un code de poule en supprimant le suffixe aller/retour.

    Certaines compétitions ajoutent un 'A' (aller) ou 'R' (retour) à la fin
    du code de poule de 3 lettres. Cela ne représente PAS une poule différente
    mais simplement une phase de la même compétition.

    Exemples :
      - "DSFA" → ("DSF", "ALLER")
      - "DSFR" → ("DSF", "RETOUR")
      - "PRMA" → Ambigu : pourrait être Poule A ou phase aller.
                 On réserve la normalisation aux codes de 4+ lettres
                 dont le suffixe A/R ne fait pas partie du code de base.
      - "EMA"  → ("EMA", None)  — pas de suffixe
      - "EFA"  → ("EFA", None)  — le A fait partie du code (Poule A)

    La détection se fait par heuristique :
    - Code de 4+ caractères
    - Dernière lettre = A ou R
    - L'avant-dernière lettre N'EST PAS M ou F (sinon c'est genre + poule_lettre)

    Returns:
        Tuple (code_base, phase) où phase est "ALLER", "RETOUR" ou None.
    """
    if not poule_code or len(poule_code) < 4:
        return poule_code, None

    upper = poule_code.upper()
    last = upper[-1]
    before_last = upper[-2]

    # Si le dernier caractère est A ou R et l'avant-dernier N'EST PAS
    # M ou F (qui indiquerait genre + lettre de poule), c'est une phase
    if last in ('A', 'R') and before_last not in ('M', 'F'):
        # Vérifier qu'il ne s'agit pas d'un code comme SN1A (compétition à poule unique)
        # Heuristique : le code de base doit avoir >= 3 caractères
        base = upper[:-1]
        if len(base) >= 3:
            phase = "ALLER" if last == 'A' else "RETOUR"
            return base, phase

    return poule_code, None


def is_empty_match(equipe_a_nom: Optional[str], equipe_b_nom: Optional[str],
                   code_match: str) -> bool:
    """Détermine si un match est un placeholder vide (xxxxx).

    Ces entrées représentent une absence de match et ne doivent pas
    être importées ni affichées.

    Returns:
        True si le match est un placeholder vide.
    """
    placeholder = {"xxxxx", "xxxxx ", " xxxxx", "xxxx", "xxx"}

    if equipe_a_nom and equipe_a_nom.strip().lower() in placeholder:
        return True
    if equipe_b_nom and equipe_b_nom.strip().lower() in placeholder:
        return True

    # Les deux équipes manquantes = match vide
    if not equipe_a_nom and not equipe_b_nom:
        return True

    return False


def _parse_set_score(score_str: str) -> Optional[tuple[int, int]]:
    """Parse un score de set ``25-18`` ou ``25/18`` en tuple ``(25, 18)``."""
    if not score_str or not score_str.strip():
        return None
    s = score_str.strip()
    # Séparer par - ou /
    for sep in ("-", "/"):
        parts = s.split(sep)
        if len(parts) == 2:
            try:
                return (int(parts[0]), int(parts[1]))
            except ValueError:
                continue
    return None


def _parse_sets_from_score_column(score_str: str) -> list[tuple[int, int]]:
    """Parse la colonne Score ``25-18,16-25,25-20`` en liste de tuples.

    Le format est : scores de chaque set séparés par des virgules,
    chaque score au format ``a-b``.
    """
    if not score_str or not score_str.strip():
        return []
    sets: list[tuple[int, int]] = []
    for part in score_str.strip().split(","):
        parsed = _parse_set_score(part)
        if parsed:
            sets.append(parsed)
    return sets


def _parse_set_result(set_str: str) -> Optional[tuple[str, str]]:
    """Parse la colonne Set `` 3/1`` ou `` 3/P`` en tuple de chaînes.

    Retourne ``("3", "1")`` ou ``("3", "P")``, ou None si vide.
    """
    if not set_str or not set_str.strip():
        return None
    s = set_str.strip()
    parts = s.split("/")
    if len(parts) == 2:
        return (parts[0].strip(), parts[1].strip())
    return None


def _is_played_set_result(set_result: Optional[tuple[str, str]]) -> bool:
    """Détermine si un score sets issu de la colonne Set signifie match joué.

    Cas non joués à ignorer : ``0/0`` (ou format équivalent) sans forfait.
    """
    if not set_result:
        return False

    canonical = normalize_score_sets(f"{set_result[0]}/{set_result[1]}")
    return score_sets_indicates_played(canonical)


def _parse_date(date_str: str) -> Optional[date]:
    """Parse une date ``JJ/MM/AAAA`` ou ``JJ-MM-AAAA``."""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def _clean_str(value: str) -> Optional[str]:
    """Nettoie une chaîne (strip + None si vide)."""
    if not value:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def build_export_url(
    base_url: str,
    entite_code: str,
    saison: str,
    *,
    poule: Optional[str] = None,
) -> str:
    """Construit l'URL de l'export CSV pour une entité."""
    params = {
        "saison": saison,
        "codent": entite_code,
        "calend": "COMPLET",
    }
    if poule:
        params["poule"] = poule
    return urljoin(base_url, f"vbspo_calendrier_export.php?{urlencode(params)}")


def build_feuille_match_url(
    base_url: str,
    entite_code: str,
    code_match: str,
    saison: str,
) -> str:
    """Construit l'URL de la feuille de match PDF."""
    params = {
        "saison": saison,
        "codent": entite_code,
        "codmatch": code_match,
    }
    return urljoin(base_url, f"ffvolley_fdme.php?{urlencode(params)}")


def fetch_export(
    client: HttpClient,
    base_url: str,
    entite_code: str,
    saison: str,
    *,
    poule: Optional[str] = None,
) -> list[ExportMatchInfo]:
    """Télécharge et parse l'export CSV complet d'une entité.

    Args:
        client: Client HTTP configuré (rate limiting, retry, etc.)
        base_url: URL de base FFVB (ex: ``https://www.ffvbbeach.org/ffvbapp/resu/``)
        entite_code: Code de l'entité (ex: ``ABCCS``)
        saison: Saison au format ``YYYY/YYYY`` (ex: ``2025/2026``)
        poule: Code de poule optionnel (si None → toutes les poules)

    Returns:
        Liste de ``ExportMatchInfo`` (un par match trouvé dans l'export)
    """
    url = build_export_url(base_url, entite_code, saison, poule=poule)

    logger.info("Téléchargement export CSV: %s (saison=%s)", entite_code, saison)

    # Utiliser un timeout plus long pour les exports CSV volumineux
    # (le serveur FFVB peut mettre > 45s à générer la réponse)
    saved_timeout = client.timeout
    try:
        client._timeout = max(saved_timeout, EXPORT_TIMEOUT)
        response = client.get(url)
    except Exception as e:
        logger.error("Erreur téléchargement export %s: %s", entite_code, e)
        return []
    finally:
        client._timeout = saved_timeout

    matches = parse_export_csv(response.content, entite_code, saison, base_url)

    # Filtrage client si un code poule a été demandé
    # (le serveur FFVB ignore parfois les paramètres poule invalides)
    if poule:
        matches = [m for m in matches if m.poule_code == poule]

    return matches


def parse_export_csv(
    content_bytes: bytes,
    entite_code: str,
    saison: str,
    base_url: str,
) -> list[ExportMatchInfo]:
    """Parse le contenu brut d'un export CSV FFVB.

    Séparé de ``fetch_export`` pour faciliter les tests unitaires
    avec des données locales.

    Args:
        content_bytes: Contenu brut de la réponse HTTP
        entite_code: Code de l'entité
        saison: Saison au format ``YYYY/YYYY``
        base_url: URL de base FFVB (pour construire les URLs des feuilles)

    Returns:
        Liste de ``ExportMatchInfo``
    """
    # Décodage — l'export est en latin-1
    try:
        content = content_bytes.decode("latin-1")
    except (UnicodeDecodeError, AttributeError):
        try:
            content = content_bytes.decode("utf-8")
        except Exception:
            logger.error("Impossible de décoder l'export pour %s", entite_code)
            return []

    if not content.strip():
        logger.warning("Export vide pour %s (saison %s)", entite_code, saison)
        return []

    # Parse CSV (séparé par points-virgules)
    reader = csv.reader(io.StringIO(content), delimiter=";")
    matches: list[ExportMatchInfo] = []
    plausibility_engine = ScrapePlausibilityEngine()
    skipped_short_rows = 0
    skipped_missing_code = 0
    skipped_placeholders = 0

    header_skipped = False
    for row_idx, row in enumerate(reader):
        # Ignorer la première ligne (en-têtes)
        if not header_skipped:
            header_skipped = True
            continue

        if len(row) < MIN_COLUMNS:
            skipped_short_rows += 1
            continue

        code_match = _clean_str(row[COL_MATCH])
        if not code_match:
            skipped_missing_code += 1
            continue

        # Poule déduite du code match
        poule_code = _extract_poule_code(code_match)

        # Aller/Retour : normaliser le code de poule
        poule_code_base, phase_ar = normalize_poule_code(poule_code)

        # Équipes
        equipe_a_nom = _clean_str(row[COL_EQA_NOM])
        equipe_b_nom = _clean_str(row[COL_EQB_NOM])

        # Filtrer les matchs vides / placeholders (xxxxx)
        if is_empty_match(equipe_a_nom, equipe_b_nom, code_match):
            logger.debug(
                "Match vide ignoré: %s (%s vs %s)",
                code_match, equipe_a_nom, equipe_b_nom,
            )
            skipped_placeholders += 1
            continue

        club_a_code = _clean_str(row[COL_EQA_NO])
        club_b_code = _clean_str(row[COL_EQB_NO])

        # Score sets depuis la colonne Set (" 3/1", " P/3", etc.)
        set_result = _parse_set_result(row[COL_SET]) if COL_SET < len(row) else None

        # Scores détaillés par set depuis la colonne Score ("25-18,16-25,25-20")
        sets: list[tuple[int, int]] = []
        if COL_SCORE < len(row):
            sets = _parse_sets_from_score_column(row[COL_SCORE])

        # Score total sets (ex: "3/1", "0/3")
        score_sets: Optional[str] = None
        if set_result:
            score_sets = f"{set_result[0]}/{set_result[1]}"

        # Date et heure
        date_match = _parse_date(row[COL_DATE]) if COL_DATE < len(row) else None
        heure = _clean_str(row[COL_HEURE]) if COL_HEURE < len(row) else None

        # Salle
        salle = _clean_str(row[COL_SALLE]) if COL_SALLE < len(row) else None

        # Journée
        journee = _clean_str(row[COL_JOURNEE]) if COL_JOURNEE < len(row) else None

        # Arbitres
        arbitres: list[ArbitreInfo] = []
        for lic_col, nom_col, lr_col, cd_col in [
            (COL_ARB1_LIC, COL_ARB1_NOM, COL_ARB1_LR, COL_ARB1_CD),
            (COL_ARB2_LIC, COL_ARB2_NOM, COL_ARB2_LR, COL_ARB2_CD),
        ]:
            if nom_col < len(row):
                arb_nom = _clean_str(row[nom_col])
                arb_lic = _clean_str(row[lic_col]) if lic_col < len(row) else None
                # Filtrer les licences/noms "0" (placeholder FFVB pour vide)
                if arb_lic == "0":
                    arb_lic = None
                if arb_nom == "0":
                    arb_nom = None
                if arb_nom or arb_lic:
                    arbitres.append(ArbitreInfo(
                        licence=arb_lic or "",
                        nom=arb_nom or "",
                        ligue=_clean_str(row[lr_col]) if lr_col < len(row) else None,
                        comite_departemental=_clean_str(row[cd_col]) if cd_col < len(row) else None,
                    ))

        # Juges de ligne (paires licence/nom : colonnes 21-28)
        juges = []
        for jl_nom_col in (COL_JDL1_NOM, COL_JDL2_NOM, COL_JDL3_NOM, COL_JDL4_NOM):
            if jl_nom_col < len(row):
                jl = _clean_str(row[jl_nom_col])
                if jl:
                    juges.append(jl)

        # Marqueurs (paires licence/nom : colonnes 29-32)
        marqueurs = []
        for mrq_nom_col in (COL_MRQ1_NOM, COL_MRQ2_NOM):
            if mrq_nom_col < len(row):
                mrq = _clean_str(row[mrq_nom_col])
                if mrq:
                    marqueurs.append(mrq)

        # Forfait — indiqué par "P" dans la colonne Set : "3/P" ou "P/3"
        forfait = False
        if set_result:
            a, b = set_result
            if a.upper() == "P" or b.upper() == "P":
                forfait = True

        # Déterminer si le match est joué
        sets_have_scores = any((score_a + score_b) > 0 for score_a, score_b in sets)
        has_set_result = _is_played_set_result(set_result)
        score_sets = normalize_score_sets(
            score_sets,
            replace_forfeit_with_zero=forfait,
        )
        match_joue = compute_match_played(
            score_sets=score_sets,
            sets=sets,
            forfait=forfait,
            has_set_scores=sets_have_scores,
        )

        # Score sets nettoyé pour les forfaits
        if score_sets and not match_joue:
            # Cas FFVB fréquent sur matchs à venir: "0/0"
            score_sets = None

        # Vainqueur
        vainqueur = None
        if sets and not forfait:
            sa = sum(1 for a, b in sets if a > b)
            sb = sum(1 for a, b in sets if b > a)
            if sa > sb and equipe_a_nom:
                vainqueur = equipe_a_nom
            elif sb > sa and equipe_b_nom:
                vainqueur = equipe_b_nom
        elif forfait and set_result:
            # Pour les forfaits, le vainqueur est l'équipe qui a des sets
            a, b = set_result
            if a.upper() == "P" and equipe_b_nom:
                vainqueur = equipe_b_nom
            elif b.upper() == "P" and equipe_a_nom:
                vainqueur = equipe_a_nom

        # URL feuille de match
        feuille_url = build_feuille_match_url(
            base_url, entite_code, code_match, saison
        )

        match_info = ExportMatchInfo(
            code_match=code_match,
            entite_code=entite_code,
            poule_code=poule_code,
            poule_code_ffvb=poule_code_base if phase_ar else None,
            saison=saison,
            journee=journee,
            equipe_a_nom=equipe_a_nom,
            equipe_b_nom=equipe_b_nom,
            club_a_code_ffvb=club_a_code,
            club_b_code_ffvb=club_b_code,
            sets=sets,
            score_sets=score_sets,
            vainqueur=vainqueur,
            forfait=forfait,
            match_joue=match_joue,
            date_match=date_match,
            heure=heure,
            salle=salle,
            arbitres=arbitres,
            juges_de_ligne=juges,
            marqueurs=marqueurs,
            feuille_match_url=feuille_url,
            phase_aller_retour=phase_ar,
        )

        plausibility_issues = plausibility_engine.apply(match_info)
        if plausibility_issues:
            match_info.plausibility_issues = [
                issue.to_dict() for issue in plausibility_issues
            ]
            match_info.plausibility_summary = summarize_scrape_issues(
                plausibility_issues
            )

        matches.append(match_info)

    logger.info(
        "Export %s: %d matchs trouvés (%d joués, %d forfaits, %d poules uniques, "
        "%d lignes courtes ignorées, %d sans code, %d placeholders)",
        entite_code,
        len(matches),
        sum(1 for m in matches if m.match_joue),
        sum(1 for m in matches if m.forfait),
        len({m.poule_code for m in matches}),
        skipped_short_rows,
        skipped_missing_code,
        skipped_placeholders,
    )

    return matches


def get_unique_poules(matches: list[ExportMatchInfo]) -> dict[str, list[ExportMatchInfo]]:
    """Regroupe les matchs par code de poule.

    Returns:
        Dict ``{poule_code: [matchs]}`` trié par code de poule.
    """
    poules: dict[str, list[ExportMatchInfo]] = {}
    for m in matches:
        poules.setdefault(m.poule_code, []).append(m)
    return dict(sorted(poules.items()))


def get_unique_clubs(matches: list[ExportMatchInfo]) -> set[str]:
    """Extrait les codes club FFVB uniques de tous les matchs.

    Returns:
        Set de codes club non-vides.
    """
    clubs: set[str] = set()
    for m in matches:
        if m.club_a_code_ffvb:
            clubs.add(m.club_a_code_ffvb)
        if m.club_b_code_ffvb:
            clubs.add(m.club_b_code_ffvb)
    return clubs


def enrich_matches_with_competition_info(
    matches: list[ExportMatchInfo],
    client: HttpClient,
    base_url: str,
    entite_code: str,
    saison: str,
) -> list[ExportMatchInfo]:
    """Enrichit les matchs avec les métadonnées de compétition.

    Scrape la page d'accueil FFVB (``vbspo_home.php``) pour construire
    l'index de toutes les compétitions de l'entité, puis l'utilise pour
    enrichir chaque match avec : genre, catégorie, niveau, division,
    nom de compétition, etc.

    Les matchs dont le code de poule n'est pas trouvé dans l'index sont
    enrichis par analyse du code seul (fallback ``enrich_competition_meta_from_code``).

    Args:
        matches: Liste de matchs à enrichir (modifiés in-place).
        client: Client HTTP.
        base_url: URL de base FFVB.
        entite_code: Code de l'entité.
        saison: Saison au format "YYYY/YYYY".

    Returns:
        La même liste de matchs (enrichis in-place).
    """
    from pyvolley.scrapers.ffvb.competition_info import (
        build_competition_index,
        enrich_competition_meta_from_code,
    )

    # Construire l'index des compétitions (ou le récupérer du cache)
    index = build_competition_index(client, base_url, entite_code, saison)

    enriched = 0
    prefix_enriched = 0
    fallback = 0

    for match in matches:
        # Enrichir les infos entité
        if not match.entite_nom and index.entite_nom != entite_code:
            match.entite_nom = index.entite_nom
        if not match.entite_type and index.entite_type != "autre":
            match.entite_type = index.entite_type

        meta = index.get(match.poule_code)

        # Si pas trouvé, essayer le code de base (sans suffixe aller/retour).
        # Le CSV produit des codes 4+ lettres (ex: DSFA, DSFR, PRMA, JFAA)
        # alors que l'index FFVB utilise des codes 3 lettres (DSF, PRM, JFA).
        # Le suffixe A/R représente la phase aller/retour.
        resolved_base_code = None
        if not meta and match.poule_code_ffvb:
            # Utiliser directement le code base déjà normalisé
            meta = index.get(match.poule_code_ffvb)
            if meta:
                resolved_base_code = match.poule_code_ffvb

        if not meta and len(match.poule_code) >= 4:
            for prefix_len in range(len(match.poule_code) - 1, 1, -1):
                prefix = match.poule_code[:prefix_len]
                meta = index.get(prefix)
                if meta:
                    resolved_base_code = prefix
                    break

        if meta:
            match.competition_nom = meta.nom_complet
            match.competition_groupe = meta.categorie_groupe
            match.genre = meta.genre
            match.categorie_age = meta.categorie_age
            match.niveau = meta.niveau
            match.division = meta.division
            match.type_competition = meta.type_competition
            match.phase = meta.phase
            match.poule_lettre = meta.poule_lettre
            if resolved_base_code:
                match.poule_code_ffvb = resolved_base_code
                prefix_enriched += 1
            else:
                match.poule_code_ffvb = match.poule_code
                enriched += 1
        else:
            # Fallback : enrichir à partir du code seul
            fb_meta = enrich_competition_meta_from_code(
                match.poule_code,
                entite_type=index.entite_type,
            )
            match.genre = fb_meta.genre
            match.categorie_age = fb_meta.categorie_age
            match.niveau = fb_meta.niveau
            match.division = fb_meta.division
            match.poule_lettre = fb_meta.poule_lettre
            fallback += 1

    logger.info(
        "Enrichissement compétitions %s: %d enrichis (index), %d via préfixe, %d fallback (code), %d total",
        entite_code, enriched, prefix_enriched, fallback, len(matches),
    )

    return matches


def fetch_and_enrich_export(
    client: HttpClient,
    base_url: str,
    entite_code: str,
    saison: str,
    *,
    poule: Optional[str] = None,
) -> list[ExportMatchInfo]:
    """Télécharge l'export CSV et enrichit avec les métadonnées de compétition.

    Combinaison de ``fetch_export`` + ``enrich_matches_with_competition_info``
    en un seul appel pratique.

    Args:
        client: Client HTTP.
        base_url: URL de base FFVB.
        entite_code: Code de l'entité.
        saison: Saison au format "YYYY/YYYY".
        poule: Code de poule optionnel.

    Returns:
        Liste de matchs enrichis.
    """
    matches = fetch_export(client, base_url, entite_code, saison, poule=poule)
    if matches:
        enrich_matches_with_competition_info(
            matches, client, base_url, entite_code, saison,
        )
    return matches
