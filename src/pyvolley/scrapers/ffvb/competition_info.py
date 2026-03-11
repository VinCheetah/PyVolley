"""
Extraction et analyse des métadonnées de compétitions FFVB.

Ce module fournit :
1. ``CompetitionMeta`` : structure riche décrivant une compétition FFVB
2. ``scrape_competition_index`` : scraping de la page d'accueil d'une entité
   (``vbspo_home.php``) qui donne la liste complète des poules avec leurs
   noms et leur catégorie parente
3. ``parse_competition_name`` : analyse statique d'un nom de compétition
   pour en extraire genre, catégorie d'âge, niveau, division, phase, etc.
4. ``build_competition_index`` : construit l'index complet des compétitions
   pour une entité (scraping + parsing)

Sources de données :
- Page ``vbspo_home.php`` : liste des poules groupées par catégorie
- Noms de compétitions : analyse par regex des conventions FFVB

Conventions FFVB pour les codes de poule / noms de compétition :
  - ``EMA`` → ELITE MASCULINE - POULE A
  - ``2FA`` → NATIONALE 2 FEMININE - POULE A
  - ``3MA`` → NATIONALE 3 MASCULINE POULE A
  - ``PMA`` → PRENATIONAL MASCULINS POULE A
  - ``RFC`` → REGIONAL FEMININS POULE C
  - ``BFA`` → TOURNOI REGIONAL M13 FEMININS POULE A
  - ``CMA`` → TOURNOI REGIONAL M18 MASCULINS POULE A
  - ``DSF`` → Dép. Senior Féminin
  - ``PRA`` → Pré-Régional d'Accession Masculin - Poule A
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode, urljoin

from pyvolley.scrapers.http_client import HttpClient

logger = logging.getLogger(__name__)


# =====================================================================
# Modèle de données
# =====================================================================


@dataclass
class CompetitionMeta:
    """Métadonnées riches d'une compétition FFVB.

    Représente toutes les informations qu'on peut déduire du nom de
    compétition et de la structure de la page d'accueil FFVB.
    """
    # Identifiants
    poule_code: str                # Code court (ex: "EMA", "2FA", "PMA")
    nom_complet: str               # Nom complet (ex: "ELITE MASCULINE - POULE A")
    categorie_groupe: str = ""     # Heading parent (ex: "ELITE MASCULINE", "NATIONALE 2 FÉMININE")

    # Classification
    genre: Optional[str] = None          # "MASCULIN", "FEMININ", "MIXTE"
    categorie_age: Optional[str] = None  # "SENIOR", "M21", "M20", "M18", "M17", "M15", "M13"
    niveau: Optional[str] = None         # "ELITE", "NATIONALE", "PRE_NATIONALE", "REGIONALE", "DEPARTEMENTALE", "LOISIR"
    division: Optional[str] = None       # "1", "2", "3" (numéro de division)

    # Détails supplémentaires
    type_competition: Optional[str] = None  # "CHAMPIONNAT", "COUPE", "TOURNOI", "BARRAGES", "PLAY_OFF", "PLAY_DOWN"
    phase: Optional[str] = None             # "POULE", "PHASE_FINALE", "BARRAGE", "PLAY_OFF", "PLAY_DOWN", "FINAL_FOUR"
    poule_lettre: Optional[str] = None      # "A", "B", "C", ... (lettre de poule)

    # Entité organisatrice
    entite_code: Optional[str] = None     # Code de l'entité (ex: "ABCCS", "LIRA")
    entite_nom: Optional[str] = None      # Nom de l'entité (ex: "Compétitions Nationales SENIORS")
    entite_type: Optional[str] = None     # "nationale", "ligue", "comite"

    def __repr__(self) -> str:
        parts = [f"<CompetitionMeta {self.poule_code}"]
        if self.genre:
            parts.append(self.genre)
        if self.categorie_age:
            parts.append(self.categorie_age)
        if self.niveau:
            parts.append(self.niveau)
        if self.division:
            parts.append(f"D{self.division}")
        parts.append(f'"{self.nom_complet}"')
        return " ".join(parts) + ">"


@dataclass
class CompetitionIndex:
    """Index de toutes les compétitions d'une entité pour une saison.

    Permet de chercher les métadonnées d'une compétition par code de poule.
    """
    entite_code: str
    entite_nom: str
    entite_type: str
    saison: str
    competitions: dict[str, CompetitionMeta] = field(default_factory=dict)
    # Groupes de compétitions (heading → [poule_codes])
    groupes: dict[str, list[str]] = field(default_factory=dict)

    def get(self, poule_code: str) -> Optional[CompetitionMeta]:
        """Retourne les métadonnées d'une compétition par code de poule."""
        return self.competitions.get(poule_code)

    def __len__(self) -> int:
        return len(self.competitions)


# =====================================================================
# Patterns de détection
# =====================================================================


# ── Genre ────────────────────────────────────────────────────────────

_GENRE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bMASCULIN(?:E|S|ES)?\b', re.IGNORECASE), "MASCULIN"),
    (re.compile(r'\bMASC\b', re.IGNORECASE), "MASCULIN"),
    (re.compile(r'\bF[EÉ]MININ(?:E|S|ES)?\b', re.IGNORECASE), "FEMININ"),
    (re.compile(r'\bFEM\b', re.IGNORECASE), "FEMININ"),
    (re.compile(r'\bMIXTE\b', re.IGNORECASE), "MIXTE"),
]

# Genre déduit du code de poule (dernière lettre avant les chiffres)
# xM* = Masculin, xF* = Féminin
_GENRE_FROM_CODE = {
    "M": "MASCULIN",
    "F": "FEMININ",
}


# ── Catégorie d'âge ──────────────────────────────────────────────────

_CATEGORIE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bSENIORS?\b', re.IGNORECASE), "SENIOR"),
    (re.compile(r'\bM21\b', re.IGNORECASE), "M21"),
    (re.compile(r'\bM20\b', re.IGNORECASE), "M20"),
    (re.compile(r'\bM18\b', re.IGNORECASE), "M18"),
    (re.compile(r'\bM17\b', re.IGNORECASE), "M17"),
    (re.compile(r'\bM15\b', re.IGNORECASE), "M15"),
    (re.compile(r'\bM13\b', re.IGNORECASE), "M13"),
    (re.compile(r'\bU21\b', re.IGNORECASE), "M21"),
    (re.compile(r'\bU20\b', re.IGNORECASE), "M20"),
    (re.compile(r'\bU18\b', re.IGNORECASE), "M18"),
    (re.compile(r'\bU17\b', re.IGNORECASE), "M17"),
    (re.compile(r'\bU15\b', re.IGNORECASE), "M15"),
    (re.compile(r'\bU13\b', re.IGNORECASE), "M13"),
    (re.compile(r'\bJEUNES?\b', re.IGNORECASE), "JEUNE"),
    (re.compile(r'\bV[EÉ]T[EÉ]RANS?\b', re.IGNORECASE), "VETERAN"),
]


# ── Niveau ───────────────────────────────────────────────────────────

# Ordonnés du plus spécifique au moins spécifique
_NIVEAU_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Elite
    (re.compile(r'\bELITE\b', re.IGNORECASE), "ELITE"),
    (re.compile(r'\bPRO\s*[AB]?\b', re.IGNORECASE), "ELITE"),
    (re.compile(r'\bLIGUE\s*[AB]\b', re.IGNORECASE), "ELITE"),
    (re.compile(r'\bLAM\b|\bLAF\b|\bLBM\b|\bLBF\b', re.IGNORECASE), "ELITE"),
    (re.compile(r'\bTQE\b', re.IGNORECASE), "ELITE"),
    (re.compile(r'\bELITE\s+AVENIR\b', re.IGNORECASE), "ELITE"),
    (re.compile(r'\bSUPERCOUPE\b', re.IGNORECASE), "ELITE"),
    # Pré-nationale (avant nationale pour éviter un match partiel)
    (re.compile(r'\bPR[EÉ][\s-]*NATIONAL(?:E|AUX|ES?)?\b', re.IGNORECASE), "PRE_NATIONALE"),
    (re.compile(r'\bPRENATIONAL\b', re.IGNORECASE), "PRE_NATIONALE"),
    (re.compile(r'\bPR[EÉ][\s-]*R[EÉ]GIONAL(?:E|AUX|ES?)?\b', re.IGNORECASE), "PRE_NATIONALE"),
    (re.compile(r'\bACCESSION\b', re.IGNORECASE), "PRE_NATIONALE"),
    # Nationale
    (re.compile(r'\bNATIONAL(?:E|AUX|ES?)?\s*\d?\b', re.IGNORECASE), "NATIONALE"),
    (re.compile(r'\bCOUPE\s+DE\s+FRANCE\b', re.IGNORECASE), "NATIONALE"),
    (re.compile(r'\bFINALE?\s+N\d[MF]\b', re.IGNORECASE), "NATIONALE"),
    (re.compile(r'\bULTRAMARIN\b', re.IGNORECASE), "NATIONALE"),
    # Régionale
    (re.compile(r'\bR[EÉ]GIONAL(?:E|AUX|ES?)?\s*\d?\b', re.IGNORECASE), "REGIONALE"),
    (re.compile(r'\bTOURNOI\s+R[EÉ]GIONAL\b', re.IGNORECASE), "REGIONALE"),
    (re.compile(r'\bCHAMPIONNAT\s+R[EÉ]GIONAL\b', re.IGNORECASE), "REGIONALE"),
    (re.compile(r'\bTID\b', re.IGNORECASE), "REGIONALE"),  # Tournoi InterDépartemental
    # Départementale
    (re.compile(r'\bD[EÉ]PARTEMENTAL(?:E|AUX|ES?)?\b', re.IGNORECASE), "DEPARTEMENTALE"),
    (re.compile(r'\bD[EÉ]P\.?\b', re.IGNORECASE), "DEPARTEMENTALE"),
    # Loisir
    (re.compile(r'\bLOISIRS?\b', re.IGNORECASE), "LOISIR"),
    (re.compile(r'\bBRASSAGES?\b', re.IGNORECASE), "LOISIR"),
    (re.compile(r'\bCOMPET\s*FUN\b', re.IGNORECASE), "LOISIR"),
    (re.compile(r'\bCOMPET\s*MOUV\b', re.IGNORECASE), "LOISIR"),
]


# ── Division (chiffre après le niveau) ───────────────────────────────

_DIVISION_PATTERNS: list[re.Pattern] = [
    # "NATIONALE 2", "REGIONALE 1", "DEPARTEMENTALE 3"
    re.compile(
        r'\b(?:NATIONAL|R[EÉ]GIONAL|DEPARTEMENTAL|PR[EÉ]NATIONAL)(?:E|AUX|ES?)?\s+(\d)\b',
        re.IGNORECASE,
    ),
    # "N2 FEMININE", "N3 MASCULINE"
    re.compile(r'\bN(\d)[MF]?\b', re.IGNORECASE),
    # Code match prefix: "2FA" → division 2, "3MA" → division 3
    re.compile(r'^(\d)[A-Z]{2}', re.IGNORECASE),
]


# ── Type de compétition ──────────────────────────────────────────────

_TYPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bCOUPE\b', re.IGNORECASE), "COUPE"),
    (re.compile(r'\bTOURNOI\b', re.IGNORECASE), "TOURNOI"),
    (re.compile(r'\bCHAMPIONNAT\b', re.IGNORECASE), "CHAMPIONNAT"),
    (re.compile(r'\bSUPERCOUPE\b', re.IGNORECASE), "SUPERCOUPE"),
]


# ── Phase ────────────────────────────────────────────────────────────

_PHASE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bPLAY[\s-]*OFF\b', re.IGNORECASE), "PLAY_OFF"),
    (re.compile(r'\bPLAY[\s-]*DOWN\b', re.IGNORECASE), "PLAY_DOWN"),
    (re.compile(r'\bFINAL\s*FOUR\b', re.IGNORECASE), "FINAL_FOUR"),
    (re.compile(r'\bPHASE\s+FINALE\b', re.IGNORECASE), "PHASE_FINALE"),
    (re.compile(r'\bBARRAGES?\b', re.IGNORECASE), "BARRAGE"),
    (re.compile(r'\bD[EÉ]L[EÉ]GATIONS?\b', re.IGNORECASE), "DELEGATION"),
    (re.compile(r'\bQUALIFICATIONS?\b', re.IGNORECASE), "QUALIFICATION"),
    (re.compile(r'\bPOULE\s+HAUTE\b', re.IGNORECASE), "POULE_HAUTE"),
    (re.compile(r'\bPOULE\s+BASSE\b', re.IGNORECASE), "POULE_BASSE"),
    (re.compile(r'\bPOULE\s+([A-Z])\b', re.IGNORECASE), "POULE"),
]


# ── Lettre de poule ──────────────────────────────────────────────────

_POULE_LETTRE_PATTERN = re.compile(
    r'(?:POULE\s+([A-Z])|[-\s]+POULE\s+([A-Z]))\b',
    re.IGNORECASE,
)
# Fallback: dernière lettre du code poule
_POULE_LETTRE_FROM_CODE = re.compile(r'^[A-Z0-9]+([A-Z])$')


# =====================================================================
# Parsing d'un nom de compétition
# =====================================================================


def parse_competition_name(
    nom: str,
    *,
    poule_code: Optional[str] = None,
    categorie_groupe: Optional[str] = None,
    entite_type: Optional[str] = None,
) -> CompetitionMeta:
    """Analyse un nom de compétition FFVB pour en extraire les métadonnées.

    Analyse le nom complet de la compétition (et optionnellement le code
    de poule et le heading parent) pour extraire :
    - Genre (MASCULIN, FEMININ, MIXTE)
    - Catégorie d'âge (SENIOR, M18, M15, M13, ...)
    - Niveau (ELITE, NATIONALE, REGIONALE, DEPARTEMENTALE, LOISIR, ...)
    - Division (1, 2, 3)
    - Type de compétition (CHAMPIONNAT, COUPE, TOURNOI)
    - Phase (POULE, PLAY_OFF, BARRAGE, PHASE_FINALE, ...)
    - Lettre de poule (A, B, C, ...)

    Args:
        nom: Nom complet de la compétition.
        poule_code: Code de la poule (optionnel, pour enrichir l'analyse).
        categorie_groupe: Heading parent de la catégorie (optionnel).
        entite_type: Type de l'entité organisatrice (optionnel).

    Returns:
        CompetitionMeta avec toutes les métadonnées extraites.

    Examples:
        >>> m = parse_competition_name("ELITE MASCULINE - POULE A", poule_code="EMA")
        >>> m.genre, m.niveau, m.categorie_age
        ('MASCULIN', 'ELITE', 'SENIOR')

        >>> m = parse_competition_name("NATIONALE 2 FEMININE - POULE A", poule_code="2FA")
        >>> m.genre, m.niveau, m.division
        ('FEMININ', 'NATIONALE', '2')

        >>> m = parse_competition_name("TOURNOI REGIONAL M13 FEMININS POULE A")
        >>> m.genre, m.niveau, m.categorie_age
        ('FEMININ', 'REGIONALE', 'M13')
    """
    meta = CompetitionMeta(
        poule_code=poule_code or "",
        nom_complet=nom,
        categorie_groupe=categorie_groupe or "",
    )

    # Texte combiné pour l'analyse (nom + groupe parent)
    texts = [nom]
    if categorie_groupe and categorie_groupe != nom:
        texts.append(categorie_groupe)
    combined = " ".join(texts)

    # ── Genre ──
    meta.genre = _detect_genre(combined, poule_code)

    # ── Catégorie d'âge ──
    meta.categorie_age = _detect_categorie_age(combined, entite_type)

    # ── Niveau ──
    meta.niveau = _detect_niveau(combined, entite_type)

    # ── Division ──
    meta.division = _detect_division(combined, poule_code)

    # ── Type de compétition ──
    meta.type_competition = _detect_type(combined)

    # ── Phase ──
    meta.phase = _detect_phase(combined)

    # ── Lettre de poule ──
    meta.poule_lettre = _detect_poule_lettre(nom, poule_code)

    return meta


# =====================================================================
# Fonctions de détection internes
# =====================================================================


def _detect_genre(text: str, poule_code: Optional[str] = None) -> Optional[str]:
    """Détecte le genre depuis le texte et/ou le code de poule."""
    for pattern, genre in _GENRE_PATTERNS:
        if pattern.search(text):
            return genre

    # Fallback : déduction depuis le code de poule
    if poule_code and len(poule_code) >= 2:
        # Patterns courants : xMA (Masculin), xFA (Féminin)
        # ou xxM, xxF en avant-dernière position
        # Ex: EMA → M, EFA → F, 2FA → F, PMA → M
        upper = poule_code.upper()
        # Chercher M ou F dans le code (position significative)
        for i, c in enumerate(upper):
            if c in _GENRE_FROM_CODE and i > 0:
                # Vérifier que c'est suivi d'une lettre (pas un chiffre)
                if i + 1 < len(upper) and upper[i + 1].isalpha():
                    return _GENRE_FROM_CODE[c]
                # Ou en dernière position
                if i == len(upper) - 1:
                    return _GENRE_FROM_CODE[c]

    return None


def _detect_categorie_age(text: str, entite_type: Optional[str] = None) -> Optional[str]:
    """Détecte la catégorie d'âge depuis le texte."""
    for pattern, cat in _CATEGORIE_PATTERNS:
        if pattern.search(text):
            return cat

    # Si pas de catégorie explicite et c'est un niveau senior
    # (Elite, Nationale, Régionale, etc.), c'est SENIOR par défaut
    upper = text.upper()
    if any(kw in upper for kw in ("ELITE", "NATIONALE", "REGIONALE", "RÉGIONALE",
                                   "PRENATIONAL", "PRÉNATIONAL", "PRE-NATIONAL",
                                   "DEPARTEMENTALE", "DÉPARTEMENTALE",
                                   "LOISIR", "COUPE DE FRANCE")):
        # Vérifier qu'il n'y a pas une catégorie jeune cachée
        if not re.search(r'\bM\d{2}\b|\bU\d{2}\b|\bJEUNE', upper):
            return "SENIOR"

    return None


def _detect_niveau(text: str, entite_type: Optional[str] = None) -> Optional[str]:
    """Détecte le niveau de compétition."""
    # "CHAMPIONNAT REGIONAL ELITE M15" → ELITE (pas REGIONALE)
    # L'ordre des patterns gère cette priorité
    for pattern, niveau in _NIVEAU_PATTERNS:
        if pattern.search(text):
            return niveau

    # Fallback : déduire du type d'entité
    if entite_type:
        type_map = {
            "nationale": "NATIONALE",
            "ligue": "REGIONALE",
            "comite": "DEPARTEMENTALE",
        }
        return type_map.get(entite_type)

    return None


def _detect_division(text: str, poule_code: Optional[str] = None) -> Optional[str]:
    """Détecte le numéro de division."""
    for pattern in _DIVISION_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)

    # Fallback : déduction depuis le code de poule
    # "2FA" → division 2, "3MA" → division 3
    if poule_code and len(poule_code) >= 2 and poule_code[0].isdigit():
        return poule_code[0]

    return None


def _detect_type(text: str) -> Optional[str]:
    """Détecte le type de compétition."""
    for pattern, comp_type in _TYPE_PATTERNS:
        if pattern.search(text):
            return comp_type
    return "CHAMPIONNAT"  # Par défaut, c'est un championnat


def _detect_phase(text: str) -> Optional[str]:
    """Détecte la phase de la compétition."""
    for pattern, phase in _PHASE_PATTERNS:
        m = pattern.search(text)
        if m:
            return phase
    return "POULE"  # Par défaut, c'est une phase de poule


def _detect_poule_lettre(text: str, poule_code: Optional[str] = None) -> Optional[str]:
    """Extrait la lettre de poule."""
    m = _POULE_LETTRE_PATTERN.search(text)
    if m:
        return (m.group(1) or m.group(2)).upper()

    # Fallback : dernière lettre du code poule
    if poule_code:
        m = _POULE_LETTRE_FROM_CODE.match(poule_code.upper())
        if m:
            letter = m.group(1)
            # Exclure M et F (genre) et certaines lettres ambiguës
            if letter not in ("M", "F"):
                return letter

    return None


# =====================================================================
# Scraping de la page d'accueil (vbspo_home.php)
# =====================================================================


def scrape_competition_index(
    client: HttpClient,
    base_url: str,
    entite_code: str,
    saison: str,
) -> CompetitionIndex:
    """Scrape la page d'accueil FFVB pour construire l'index des compétitions.

    La page ``vbspo_home.php`` liste toutes les poules groupées par catégorie
    de compétition. Chaque catégorie est un heading (ex: "ELITE MASCULINE")
    suivi de la liste des poules (ex: "EMA ELITE MASCULINE - POULE A").

    Args:
        client: Client HTTP.
        base_url: URL de base FFVB.
        entite_code: Code de l'entité.
        saison: Saison au format "YYYY/YYYY".

    Returns:
        CompetitionIndex complet avec toutes les compétitions.
    """
    params = {"saison": saison, "codent": entite_code}
    url = urljoin(base_url, f"vbspo_home.php?{urlencode(params)}")

    logger.info("Scraping index compétitions: %s (saison=%s)", entite_code, saison)

    try:
        soup = client.get_soup(url)
    except Exception as e:
        logger.error("Erreur scraping index compétitions %s: %s", entite_code, e)
        return CompetitionIndex(
            entite_code=entite_code, entite_nom=entite_code,
            entite_type="autre", saison=saison,
        )

    # Extraire le nom de l'entité depuis le titre de la page
    entite_nom = entite_code
    entite_type = "autre"

    # Chercher le titre/nom de l'entité
    # Le titre se trouve souvent dans le premier texte significatif de la page
    title_text = _extract_entity_title(soup)
    if title_text:
        entite_nom = title_text
        entite_type = _detect_entity_type_from_name(title_text)

    index = CompetitionIndex(
        entite_code=entite_code,
        entite_nom=entite_nom,
        entite_type=entite_type,
        saison=saison,
    )

    # Parser la table de compétitions
    # Structure HTML : table avec des rows, certaines contenant des headings
    # (catégories) et d'autres contenant les liens vers les poules.
    #
    # Les headings sont en gras/majuscules et n'ont pas de lien.
    # Les poules ont un lien et commencent par le code de poule.
    _parse_competition_table(soup, index)

    logger.info(
        "Index compétitions %s: %d poules dans %d groupes",
        entite_code, len(index.competitions), len(index.groupes),
    )

    return index


def _extract_entity_title(soup) -> Optional[str]:
    """Extrait le titre/nom de l'entité depuis le HTML."""
    # Chercher dans le texte de la page, souvent après le logo
    # Pattern typique : "Compétitions Nationales SENIORS", "Ligue AUVERGNE-RHÔNE-ALPES",
    #                   "Comité de l'Isère"
    for tag_name in ("h1", "h2", "h3", "b", "strong"):
        for tag in soup.find_all(tag_name):
            text = tag.get_text(strip=True)
            if text and len(text) > 5 and any(kw in text.lower() for kw in
                ("compétition", "competition", "ligue", "comité", "comite")):
                return text

    # Fallback : chercher dans le texte brut
    text = soup.get_text()
    for line in text.split("\n"):
        line = line.strip()
        if len(line) > 5 and any(kw in line.lower() for kw in
            ("compétitions nationales", "ligue ", "comité ")):
            return line

    return None


def _detect_entity_type_from_name(name: str) -> str:
    """Détecte le type d'entité depuis son nom."""
    lower = name.lower()
    if "nationale" in lower or "compétition" in lower:
        return "nationale"
    if "ligue" in lower:
        return "ligue"
    if "comité" in lower or "comite" in lower:
        return "comite"
    return "autre"


def _parse_competition_table(soup, index: CompetitionIndex) -> None:
    """Parse les compétitions depuis la page d'accueil FFVB.

    La structure HTML utilise des listes imbriquées ``<ul>``/``<li>`` :
    - Les headings sont des ``<a href="#">`` qui contiennent le nom de la
      catégorie (ex: "ELITE MASCULINE")
    - Les poules sont des ``<li>`` enfants de la ``<ul>`` sœur du heading,
      chacune contenant un lien vers le calendrier de la poule
      (ex: ``<a href="...?poule=EMA">EMA ELITE MASCULINE - POULE A</a>``)

    Si aucune structure de listes imbriquées n'est trouvée, on tente un
    fallback sur la structure ``<table>`` utilisée par certaines pages.
    """
    # ── Stratégie 1 : listes imbriquées <ul>/<li> ──
    parsed = _parse_list_structure(soup, index)
    if parsed:
        return

    # ── Stratégie 2 (fallback) : tables ──
    _parse_table_structure(soup, index)


def _parse_list_structure(soup, index: CompetitionIndex) -> bool:
    """Parse la structure de listes imbriquées de la page d'accueil FFVB.

    Cherche les ``<a href="#">`` qui sont des headings de catégorie,
    puis extrait les poules de la ``<ul>`` enfant du ``<li>`` parent.

    Returns:
        True si des compétitions ont été trouvées, False sinon.
    """
    found = False

    # Chercher tous les <a href="#"> qui sont des headings de catégorie
    heading_links = soup.find_all("a", href="#")

    for heading_link in heading_links:
        heading_text = heading_link.get_text(strip=True)
        if not heading_text or len(heading_text) < 3:
            continue

        # Exclure les headings non-compétitions
        lower = heading_text.lower()
        if any(kw in lower for kw in ("contact", "adressier", "boutique",
                                       "engagements", "envoyer", "ffvolley",
                                       "accès direct")):
            continue

        # Trouver le <li> parent et sa <ul> enfant
        parent_li = heading_link.find_parent("li")
        if not parent_li:
            continue

        sub_ul = parent_li.find("ul")
        if not sub_ul:
            continue

        # Vérifier que ce n'est pas un heading parent/conteneur
        # (un heading parent a des enfants <li> qui eux-mêmes contiennent
        # des <ul> imbriquées — ce sont eux les vraies catégories)
        child_lis = sub_ul.find_all("li", recursive=False)
        is_container = any(
            child_li.find("ul") is not None
            for child_li in child_lis
        )
        if is_container:
            continue

        # Ce heading est une catégorie de compétition
        current_group = heading_text.strip()
        if current_group not in index.groupes:
            index.groupes[current_group] = []

        # Extraire les poules de la liste enfant
        for li in sub_ul.find_all("li", recursive=False):
            link = li.find("a")
            if not link:
                continue

            link_text = link.get_text(strip=True)
            if link_text and len(link_text) >= 3:
                _process_poule_entry(link_text, current_group, index)
                found = True

    return found


def _parse_table_structure(soup, index: CompetitionIndex) -> None:
    """Fallback : parse les compétitions depuis une structure <table>.

    Utilisé pour les pages qui utilisent encore l'ancien format de table.
    """
    current_group = ""

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            for cell in cells:
                text = cell.get_text(strip=True)
                if not text:
                    continue

                link = cell.find("a")
                if link:
                    link_text = link.get_text(strip=True)
                    _process_poule_entry(link_text, current_group, index)
                elif _is_category_heading(text, cell):
                    current_group = text.strip()
                    if current_group and current_group not in index.groupes:
                        index.groupes[current_group] = []


def _is_category_heading(text: str, cell) -> bool:
    """Vérifie si une cellule est un heading de catégorie."""
    # Les headings sont souvent :
    # - Tout en majuscules
    # - En gras
    # - Ne commencent pas par un code de poule (2-4 lettres/chiffres suivis d'un espace)
    if not text or len(text) < 3:
        return False

    # Exclure les lignes qui ressemblent à des codes de poule
    if re.match(r'^[A-Z0-9]{2,5}\s+', text):
        return False

    # Exclure les labels de section non-compétitions
    lower = text.lower()
    if any(kw in lower for kw in ("contact", "adressier", "boutique",
                                   "engagements", "accès direct",
                                   "ffvolley", "envoyer")):
        return False

    # Les headings sont en majuscules ou contiennent des mots-clés de compétition
    upper_ratio = sum(1 for c in text if c.isupper()) / max(len(text), 1)
    has_comp_keywords = any(kw in text.upper() for kw in (
        "ELITE", "NATIONALE", "REGIONALE", "RÉGIONALE", "DEPARTEMENTALE",
        "DÉPARTEMENTALE", "PRENATIONAL", "PRÉNATIONAL", "PRÉ-RÉGIONAL",
        "CHAMPIONNAT", "COUPE", "TOURNOI", "LOISIR", "SUPERCOUPE",
        "JEUNE", "M13", "M15", "M17", "M18", "M20", "M21",
        "MASCULIN", "FEMININ", "FÉMININ", "MIXTE", "INTERDEPARTEMENTAL",
    ))

    return upper_ratio > 0.5 or has_comp_keywords


def _process_poule_entry(text: str, current_group: str, index: CompetitionIndex) -> None:
    """Traite une entrée de poule depuis la page d'accueil.

    Format typique : "EMA ELITE MASCULINE - POULE A"
    Le code de poule est le premier mot (ou les premiers caractères).
    """
    if not text or len(text) < 3:
        return

    # Séparer le code de poule du nom
    # Le code est le premier token alphanumérique
    match = re.match(r'^([A-Z0-9]{2,6})\s+(.*)', text, re.IGNORECASE)
    if not match:
        # Certaines entrées n'ont pas de code séparé
        # Ex: "COUPE DE FRANCE FEDERALE FEMININE"
        # Dans ce cas, utiliser le texte entier comme nom
        return

    poule_code = match.group(1).upper()
    nom_complet = match.group(2).strip()

    if not nom_complet:
        nom_complet = text

    # Parser les métadonnées
    meta = parse_competition_name(
        nom_complet,
        poule_code=poule_code,
        categorie_groupe=current_group,
        entite_type=index.entite_type,
    )

    # Enrichir avec les infos de l'entité
    meta.entite_code = index.entite_code
    meta.entite_nom = index.entite_nom
    meta.entite_type = index.entite_type

    # Ajouter à l'index
    index.competitions[poule_code] = meta
    if current_group in index.groupes:
        index.groupes[current_group].append(poule_code)
    elif current_group:
        index.groupes[current_group] = [poule_code]


# =====================================================================
# Construction de l'index complet (scraping + cache)
# =====================================================================


_COMPETITION_INDEX_CACHE: dict[tuple[str, str], CompetitionIndex] = {}


def build_competition_index(
    client: HttpClient,
    base_url: str,
    entite_code: str,
    saison: str,
    *,
    force_refresh: bool = False,
) -> CompetitionIndex:
    """Construit ou récupère l'index des compétitions pour une entité.

    Utilise un cache en mémoire pour éviter les requêtes répétées.

    Args:
        client: Client HTTP.
        base_url: URL de base FFVB.
        entite_code: Code de l'entité.
        saison: Saison au format "YYYY/YYYY".
        force_refresh: Force le re-scraping même si en cache.

    Returns:
        CompetitionIndex complet.
    """
    cache_key = (entite_code, saison)
    if not force_refresh and cache_key in _COMPETITION_INDEX_CACHE:
        return _COMPETITION_INDEX_CACHE[cache_key]

    index = scrape_competition_index(client, base_url, entite_code, saison)
    _COMPETITION_INDEX_CACHE[cache_key] = index
    return index


def clear_competition_cache() -> None:
    """Vide le cache des index de compétitions."""
    _COMPETITION_INDEX_CACHE.clear()


# =====================================================================
# Utilitaires d'enrichissement
# =====================================================================


def build_competition_display_name(meta: CompetitionMeta) -> str:
    """Construit un nom d'affichage lisible pour une compétition.

    Combine le nom original avec les métadonnées pour un affichage clair.

    Examples:
        >>> meta = CompetitionMeta(poule_code="EMA", nom_complet="ELITE MASCULINE - POULE A",
        ...     genre="MASCULIN", categorie_age="SENIOR", niveau="ELITE")
        >>> build_competition_display_name(meta)
        'ELITE MASCULINE - POULE A'

        >>> meta = CompetitionMeta(poule_code="DSF", nom_complet="Dép. Senior Féminin",
        ...     genre="FEMININ", categorie_age="SENIOR", niveau="DEPARTEMENTALE")
        >>> build_competition_display_name(meta)
        'Dép. Senior Féminin'
    """
    # Utiliser le nom original s'il est informatif
    if meta.nom_complet and len(meta.nom_complet) > 3:
        return meta.nom_complet

    # Construire un nom à partir des métadonnées
    parts = []
    if meta.niveau:
        parts.append(meta.niveau)
    if meta.division:
        parts.append(meta.division)
    if meta.categorie_age and meta.categorie_age != "SENIOR":
        parts.append(meta.categorie_age)
    if meta.genre:
        parts.append(meta.genre)
    if meta.poule_lettre:
        parts.append(f"POULE {meta.poule_lettre}")

    return " ".join(parts) if parts else meta.poule_code


def enrich_competition_meta_from_code(
    poule_code: str,
    entite_type: Optional[str] = None,
) -> CompetitionMeta:
    """Crée des métadonnées minimales de compétition à partir du code seul.

    Fallback quand la page d'accueil n'est pas disponible.
    Utilise les conventions de nommage FFVB pour déduire le maximum.

    Args:
        poule_code: Code de la poule (ex: "EMA", "2FA", "PMA").
        entite_type: Type d'entité optionnel.

    Returns:
        CompetitionMeta avec les métadonnées déduites du code.
    """
    meta = CompetitionMeta(
        poule_code=poule_code,
        nom_complet=poule_code,
    )

    if not poule_code or len(poule_code) < 2:
        return meta

    upper = poule_code.upper()

    # Détection du genre depuis le code
    # Patterns: xMx = Masculin, xFx = Féminin
    for i, c in enumerate(upper):
        if c in _GENRE_FROM_CODE and i > 0:
            if i + 1 < len(upper) and upper[i + 1].isalpha():
                meta.genre = _GENRE_FROM_CODE[c]
                break
            if i == len(upper) - 1:
                meta.genre = _GENRE_FROM_CODE[c]
                break

    # Division depuis le premier caractère si c'est un chiffre
    if upper[0].isdigit():
        meta.division = upper[0]
        # Si commence par un chiffre, c'est un niveau national
        meta.niveau = "NATIONALE"
    elif upper[0] == "E":
        meta.niveau = "ELITE"
    elif upper[0] == "P":
        meta.niveau = "PRE_NATIONALE"
    elif upper[0] == "R":
        meta.niveau = "REGIONALE"
    elif upper[0] == "D":
        meta.niveau = "DEPARTEMENTALE"

    # Catégorie implicite
    if meta.niveau in ("ELITE", "NATIONALE", "PRE_NATIONALE", "REGIONALE", "DEPARTEMENTALE"):
        meta.categorie_age = "SENIOR"

    # Lettre de poule (dernière lettre si pas M/F)
    if len(upper) >= 3:
        last = upper[-1]
        if last.isalpha() and last not in ("M", "F"):
            meta.poule_lettre = last

    # Fallback sur le type d'entité
    if not meta.niveau and entite_type:
        type_map = {
            "nationale": "NATIONALE",
            "ligue": "REGIONALE",
            "comite": "DEPARTEMENTALE",
        }
        meta.niveau = type_map.get(entite_type)

    return meta
