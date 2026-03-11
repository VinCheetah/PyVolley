"""
Scraper pour la Coupe de France Jeunes (``ACJEUNES``).

La Coupe de France Jeunes est organisée différemment des compétitions
classiques FFVB. La structure est hiérarchique :

    Catégorie d'âge (M21, M18, M18-CHAL, M15, M13, M11)
    └── Division (code 3 lettres : JMX, JFX, CMX, CFX, ...)
        └── Tour (01, 02, ..., 07)
            └── Poules (multiples dans chaque tour, 3 lettres chacune)
                └── Matchs

L'URL de base diffère du format classique ``poule=XXX`` :
  ``vbspo_calendrier.php?saison=YYYY/YYYY&codent=ACJEUNES&division=CMX&tour=01``

Sources de données :
  - Page de navigation ``jeunes/{saison}/pbscript.htm`` : structure complète
    des catégories, divisions et tours disponibles
  - Export CSV ``vbspo_calendrier_export.php`` : données structurées (lent
    pour l'entité complète, préférer le filtre par division)
  - Pages calendrier HTML : classements + résultats par tour

Codes de division connus (2025-2026) :
  ┌──────────┬──────────────────────────────────┬──────┬──────┐
  │ Catégorie│ Description                      │ Masc │ Fém  │
  ├──────────┼──────────────────────────────────┼──────┼──────┤
  │ M21      │ Juniors                          │ JMX  │ JFX  │
  │ M18      │ Cadets                           │ CMX  │ CFX  │
  │ M18-CHAL │ Cadets Challenge                 │ RMX  │ RFX  │
  │ M15      │ Minimes                          │ MMX  │ MFX  │
  │ M13      │ Benjamins                        │ BMX  │ BFX  │
  │ M11      │ Poussins (finales uniquement)    │ PMA  │ PFA  │
  └──────────┴──────────────────────────────────┴──────┴──────┘
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from pyvolley.scrapers.ffvb.models import ScrapeContext
from pyvolley.scrapers.http_client import HttpClient

logger = logging.getLogger(__name__)


# =====================================================================
# Constantes
# =====================================================================

ENTITY_CODE = "ACJEUNES"

# Base URL du frameset jeunes (par saison)
JEUNES_BASE_PATH = "jeunes/"
NAV_FRAME_FILENAME = "pbscript.htm"

# Mapping : code division → (catégorie d'âge, genre)
DIVISION_MAP: dict[str, tuple[str, str]] = {
    "JMX": ("M21", "MASCULIN"),
    "JFX": ("M21", "FEMININ"),
    "CMX": ("M18", "MASCULIN"),
    "CFX": ("M18", "FEMININ"),
    "RMX": ("M18", "MASCULIN"),   # M18-Challenge
    "RFX": ("M18", "FEMININ"),    # M18-Challenge
    "MMX": ("M15", "MASCULIN"),
    "MFX": ("M15", "FEMININ"),
    "BMX": ("M13", "MASCULIN"),
    "BFX": ("M13", "FEMININ"),
    # M11 utilise un format spécial (finales)
    "PMA": ("M11", "MASCULIN"),
    "PFA": ("M11", "FEMININ"),
}

# Mapping : code division → label catégorie affichée
DIVISION_CATEGORY_LABEL: dict[str, str] = {
    "JMX": "M21",
    "JFX": "M21",
    "CMX": "M18",
    "CFX": "M18",
    "RMX": "M18-CHALLENGE",
    "RFX": "M18-CHALLENGE",
    "MMX": "M15",
    "MFX": "M15",
    "BMX": "M13",
    "BFX": "M13",
    "PMA": "M11",
    "PFA": "M11",
}


# ── Inference poule → division basée sur le code poule ──
#
# L'endpoint CSV ``vbspo_calendrier_export.php`` ignore le paramètre
# ``division=`` et retourne TOUS les matchs ACJEUNES dans une seule
# réponse. Il faut donc déduire la division de chaque match à partir
# de son code de poule.
#
# Convention observée empiriquement (saison 2025-2026) :
#   - 1er caractère  → catégorie d'âge (B=M13, C=M18, J=M21, M=M15, R=M18-CHAL)
#   - 2e  caractère  → genre :
#       • M, X, Y, Z   → MASCULIN → division *MX
#       • F, G, H, I   → FEMININ  → division *FX
#       • autres (rare) → indéterminé
#
# Vérifié par scraping des pages calendrier HTML qui, elles, filtrent
# correctement par division.

CATEGORY_LETTER_MAP: dict[str, tuple[str, str, str]] = {
    # first_letter: (categorie_age, masc_division_code, fem_division_code)
    "B": ("M13", "BMX", "BFX"),
    "C": ("M18", "CMX", "CFX"),
    "J": ("M21", "JMX", "JFX"),
    "M": ("M15", "MMX", "MFX"),
    "R": ("M18", "RMX", "RFX"),
}

_MASCULINE_SECOND_LETTERS = frozenset("MXYZ")
_FEMININE_SECOND_LETTERS = frozenset("FGHI")

# Geographic zone letters (2nd char of poule code).
# These encode parallel geographic zones, NOT sequential tours.
# Actual tour number is determined by the ``journee`` field on each match.
_MASCULINE_ZONE_LETTERS = "MXYZ"
_FEMININE_ZONE_LETTERS = "FGHI"


def infer_zone_from_poule_code(poule_code: str) -> Optional[str]:
    """Déduit la zone géographique depuis le code poule d'une compétition jeune.

    Le 2e caractère du code poule encode la zone géographique, et non le tour.
    Les tours sont identifiés par le champ ``journee`` sur chaque match.

    - Masculin : M / X / Y / Z  (4 zones parallèles)
    - Féminin  : F / G / H / I  (4 zones parallèles)

    Args:
        poule_code: Code poule (ex: "CMA", "CXA", "BFD").

    Returns:
        Lettre de zone (ex: "M", "X") ou None si impossible à déterminer.
    """
    if len(poule_code) < 2:
        return None

    second = poule_code[1].upper()

    if second in _MASCULINE_ZONE_LETTERS:
        return second
    if second in _FEMININE_ZONE_LETTERS:
        return second

    return None


def infer_tour_from_poule_code(poule_code: str) -> Optional[int]:
    """DEPRECATED – Le 2e caractère encode la zone, pas le tour.

    Conservé temporairement pour compatibilité. Utiliser
    ``infer_zone_from_poule_code`` à la place. Le tour réel est
    donné par ``MatchDB.journee``.
    """
    return None


def is_youth_competition(competition_nom: Optional[str]) -> bool:
    """Détermine si une compétition est une Coupe de France Jeunes."""
    if not competition_nom:
        return False
    return competition_nom.startswith("CdF Jeunes")


def get_tour_label(tour_num: int) -> str:
    """Retourne le label affiché pour un numéro de tour.

    Args:
        tour_num: Numéro de tour (1, 2, 3, 4 ou 99).

    Returns:
        Label (ex: "Tour 1", "Phases finales").
    """
    if tour_num == 99:
        return "Phases finales"
    return f"Tour {tour_num}"


def infer_division_from_poule_code(poule_code: str) -> Optional[str]:
    """Déduit le code division (CMX, JFX…) à partir d'un code poule jeune.

    Le code poule commence par 2 lettres significatives :
    - 1re lettre = catégorie (B, C, J, M, R)
    - 2e lettre  = genre (M/X/Y/Z → masc, F/G/H/I → fém)

    Args:
        poule_code: Code poule (ex: "CYQ", "BFA", "JMA").

    Returns:
        Code division (ex: "CMX", "BFX", "JMX") ou None si indéterminé.
    """
    if len(poule_code) < 2:
        return None

    first = poule_code[0].upper()
    second = poule_code[1].upper()

    cat_info = CATEGORY_LETTER_MAP.get(first)
    if not cat_info:
        return None

    _, masc_div, fem_div = cat_info

    if second in _MASCULINE_SECOND_LETTERS:
        return masc_div
    elif second in _FEMININE_SECOND_LETTERS:
        return fem_div

    # Indéterminé (ex: CC) → on retourne la division masculine par défaut
    # et on log un avertissement
    logger.debug(
        "Code poule %s: genre indéterminé (2e lettre '%s'), "
        "assigné à la division masculine %s par défaut",
        poule_code, second, masc_div,
    )
    return masc_div


def infer_category_from_poule_code(
    poule_code: str,
) -> Optional[tuple[str, str]]:
    """Retourne (categorie_age, categorie_label) depuis un code poule.

    Args:
        poule_code: Code poule (ex: "CYQ", "BFA").

    Returns:
        Tuple (categorie_age, label) ou None si inconnu.
    """
    if not poule_code:
        return None
    first = poule_code[0].upper()
    cat_info = CATEGORY_LETTER_MAP.get(first)
    if not cat_info:
        return None
    categorie_age = cat_info[0]

    # Construire le label (utiliser la division déduite pour le label)
    div_code = infer_division_from_poule_code(poule_code)
    if div_code:
        label = DIVISION_CATEGORY_LABEL.get(div_code, categorie_age)
    else:
        label = categorie_age
    return (categorie_age, label)


# =====================================================================
# Modèles de données
# =====================================================================


@dataclass
class YouthDivisionInfo:
    """Informations sur une division jeune (ex: CMX = M18 Masculin)."""
    code: str                   # Code division (ex: CMX, JFX)
    categorie_age: str          # Catégorie d'âge (ex: M18, M15)
    genre: str                  # MASCULIN ou FEMININ
    categorie_label: str        # Label affiché (ex: M18, M18-CHALLENGE)
    tours: list[YouthTourInfo] = field(default_factory=list)

    @property
    def nom_complet(self) -> str:
        """Nom complet de la division."""
        genre_label = "Masc." if self.genre == "MASCULIN" else "Fém."
        return f"CdF Jeunes {self.categorie_label} {genre_label}"

    @property
    def nb_tours(self) -> int:
        return len(self.tours)


@dataclass
class YouthTourInfo:
    """Informations sur un tour dans une division jeune."""
    numero: int                 # Numéro du tour (1, 2, 3...)
    division_code: str          # Code division parent (ex: CMX)
    url: str                    # URL complète du calendrier de ce tour
    saison: str = ""            # Saison (ex: 2025/2026)
    poules: list[YouthPouleInfo] = field(default_factory=list)

    @property
    def code(self) -> str:
        """Code formaté du tour (ex: T01, T02)."""
        return f"T{self.numero:02d}"

    @property
    def nom_complet(self) -> str:
        """Nom complet du tour."""
        div_info = DIVISION_MAP.get(self.division_code, ("?", "?"))
        genre_label = "Masc." if div_info[1] == "MASCULIN" else "Fém."
        return f"Tour {self.numero} {div_info[0]} {genre_label}"


@dataclass
class YouthPouleInfo:
    """Informations sur une poule dans un tour de compétition jeune."""
    code: str                   # Code poule (ex: CYQ, BFA)
    tour_numero: int            # Numéro du tour parent
    division_code: str          # Code division parent (ex: CMX)
    saison: str = ""            # Saison
    equipes: list[str] = field(default_factory=list)  # Noms des équipes
    club_codes: list[str] = field(default_factory=list)  # Codes club FFVB
    nb_matchs: int = 0          # Nombre de matchs dans la poule

    @property
    def categorie_age(self) -> str:
        info = DIVISION_MAP.get(self.division_code)
        return info[0] if info else "?"

    @property
    def genre(self) -> str:
        info = DIVISION_MAP.get(self.division_code)
        return info[1] if info else "?"


@dataclass
class YouthCupIndex:
    """Index complet de la Coupe de France Jeunes pour une saison.

    Structure hiérarchique :
      divisions → tours → poules → matchs
    """
    saison: str
    divisions: dict[str, YouthDivisionInfo] = field(default_factory=dict)
    finales_urls: dict[str, str] = field(default_factory=dict)  # M11 finales

    @property
    def nb_divisions(self) -> int:
        return len(self.divisions)

    @property
    def nb_tours_total(self) -> int:
        return sum(d.nb_tours for d in self.divisions.values())

    @property
    def categories(self) -> list[str]:
        """Catégories d'âge uniques triées."""
        cats = sorted({d.categorie_label for d in self.divisions.values()})
        return cats

    def get_division(self, code: str) -> Optional[YouthDivisionInfo]:
        return self.divisions.get(code)

    def get_divisions_by_category(self, categorie: str) -> list[YouthDivisionInfo]:
        """Retourne les divisions d'une catégorie (ex: M18 → CMX + CFX)."""
        return [
            d for d in self.divisions.values()
            if d.categorie_label == categorie
        ]

    def summary(self) -> str:
        """Résumé textuel de l'index."""
        lines = [f"Coupe de France Jeunes {self.saison}"]
        lines.append(f"  {self.nb_divisions} divisions, {self.nb_tours_total} tours")
        for cat in self.categories:
            divs = self.get_divisions_by_category(cat)
            tours_str = ", ".join(
                f"{d.code}({d.nb_tours}T)" for d in divs
            )
            lines.append(f"  {cat}: {tours_str}")
        if self.finales_urls:
            lines.append(f"  Finales M11: {list(self.finales_urls.keys())}")
        return "\n".join(lines)


# =====================================================================
# Scraping de la page de navigation jeunes
# =====================================================================


def _build_nav_url(base_url: str, saison: str) -> str:
    """Construit l'URL de la page de navigation jeunes (pbscript.htm).

    La saison doit être au format ``YYYY/YYYY``, convertie en ``YYYY-YYYY``
    pour le chemin du frameset.
    """
    saison_path = saison.replace("/", "-")
    return urljoin(base_url, f"{JEUNES_BASE_PATH}{saison_path}/{NAV_FRAME_FILENAME}")


def _parse_option_url(url: str) -> Optional[dict[str, str]]:
    """Parse une URL d'option <select> pour en extraire les paramètres."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    result: dict[str, str] = {}
    for key in ("saison", "codent", "division", "tour", "poule"):
        if key in params:
            result[key] = params[key][0]
    return result if result else None


def scrape_youth_nav(
    client: HttpClient,
    base_url: str,
    saison: str,
) -> YouthCupIndex:
    """Scrape la page de navigation jeunes pour découvrir toutes les divisions/tours.

    Parse le fichier ``pbscript.htm`` qui contient les menus déroulants
    ``<select>`` avec toutes les options de navigation.

    Args:
        client: Client HTTP.
        base_url: URL de base FFVB (``https://...ffvbapp/resu/``).
        saison: Saison au format ``YYYY/YYYY``.

    Returns:
        YouthCupIndex complet avec divisions, tours et URLs.
    """
    nav_url = _build_nav_url(base_url, saison)
    logger.info("Scraping navigation Coupe de France Jeunes: %s", nav_url)

    index = YouthCupIndex(saison=saison)

    try:
        response = client.get(nav_url)
        content = response.content.decode("windows-1252", errors="replace")
    except Exception as e:
        logger.error("Erreur scraping navigation jeunes: %s", e)
        return index

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, "html.parser")

    # Parser tous les <select> qui contiennent les menus de catégories
    for select in soup.find_all("select"):
        _parse_select_options(select, index, saison)

    logger.info(
        "Index jeunes %s: %d divisions, %d tours total",
        saison, index.nb_divisions, index.nb_tours_total,
    )

    return index


def _parse_select_options(
    select,
    index: YouthCupIndex,
    saison: str,
) -> None:
    """Parse les options d'un <select> pour extraire divisions et tours."""
    for option in select.find_all("option"):
        url = option.get("value", "").strip()
        label = option.get_text(strip=True)

        if not url or not url.startswith("http"):
            continue

        params = _parse_option_url(url)
        if not params:
            continue

        # Cas spécial : page de finales M11
        if "ffvb_jeunes_finales.php" in url:
            poule = params.get("poule", "")
            if poule:
                index.finales_urls[poule] = url
            continue

        division_code = params.get("division", "")
        tour_str = params.get("tour", "")

        if not division_code or not tour_str:
            continue

        try:
            tour_num = int(tour_str)
        except ValueError:
            logger.warning("Tour invalide: %s", tour_str)
            continue

        # Créer ou récupérer la division
        if division_code not in index.divisions:
            div_info = DIVISION_MAP.get(division_code, ("INCONNU", "INCONNU"))
            cat_label = DIVISION_CATEGORY_LABEL.get(division_code, division_code)
            index.divisions[division_code] = YouthDivisionInfo(
                code=division_code,
                categorie_age=div_info[0],
                genre=div_info[1],
                categorie_label=cat_label,
            )

        division = index.divisions[division_code]

        # Vérifier si ce tour existe déjà
        existing_tours = {t.numero for t in division.tours}
        if tour_num not in existing_tours:
            division.tours.append(YouthTourInfo(
                numero=tour_num,
                division_code=division_code,
                url=url,
                saison=saison,
            ))

    # Trier les tours par numéro
    for division in index.divisions.values():
        division.tours.sort(key=lambda t: t.numero)


# =====================================================================
# Construction d'URLs pour les compétitions jeunes
# =====================================================================


def build_youth_calendar_url(
    base_url: str,
    saison: str,
    division: str,
    tour: int,
) -> str:
    """Construit l'URL du calendrier pour un tour jeune spécifique.

    Args:
        base_url: URL de base FFVB.
        saison: Saison (ex: "2025/2026").
        division: Code division (ex: "CMX").
        tour: Numéro du tour (ex: 1).

    Returns:
        URL complète du calendrier.
    """
    params = {
        "saison": saison,
        "codent": ENTITY_CODE,
        "division": division,
        "tour": f"{tour:02d}",
    }
    return urljoin(base_url, f"vbspo_calendrier.php?{urlencode(params)}")


def build_youth_export_url(
    base_url: str,
    saison: str,
    division: Optional[str] = None,
) -> str:
    """Construit l'URL d'export CSV pour les compétitions jeunes.

    Si ``division`` est None, exporte tout (lent !).
    Préférer le filtrage par division.

    Args:
        base_url: URL de base FFVB.
        saison: Saison.
        division: Code division optionnel pour filtrage.

    Returns:
        URL d'export CSV.
    """
    params: dict[str, str] = {
        "saison": saison,
        "codent": ENTITY_CODE,
        "calend": "COMPLET",
    }
    if division:
        params["division"] = division
    return urljoin(base_url, f"vbspo_calendrier_export.php?{urlencode(params)}")


# =====================================================================
# Scraping des poules et classements d'un tour
# =====================================================================


@dataclass
class YouthStandingEntry:
    """Entrée de classement d'une poule jeune."""
    rang: int
    equipe: str
    club_code: str = ""         # Code club FFVB
    points: int = 0
    joues: int = 0
    gagnes: int = 0
    perdus: int = 0
    forfaits: int = 0
    sets_pour: int = 0
    sets_contre: int = 0
    points_pour: int = 0
    points_contre: int = 0


@dataclass
class YouthMatchResult:
    """Résultat d'un match dans une poule jeune (depuis le HTML)."""
    code: str                       # Code match (ex: CYQ001)
    poule_code: str                 # Code poule (ex: CYQ)
    date: Optional[str] = None     # Date au format DD/MM/YY
    heure: Optional[str] = None
    equipe_a: Optional[str] = None
    equipe_b: Optional[str] = None
    sets_a: Optional[int] = None
    sets_b: Optional[int] = None
    score_detail: Optional[str] = None  # "25:12, 25:19"
    total: Optional[str] = None         # "050-031"
    arbitres: Optional[str] = None
    pdf_url: Optional[str] = None


def scrape_youth_tour(
    client: HttpClient,
    base_url: str,
    saison: str,
    division: str,
    tour: int,
) -> list[YouthPouleInfo]:
    """Scrape un tour complet pour découvrir ses poules et matchs.

    Parse la page calendrier HTML d'un tour, qui contient :
    - Alternance de tableaux de classement et de matchs
    - Chaque bloc = 1 poule (classement + résultats)

    Args:
        client: Client HTTP.
        base_url: URL de base FFVB.
        saison: Saison.
        division: Code division (ex: CMX).
        tour: Numéro du tour.

    Returns:
        Liste de YouthPouleInfo avec équipes et matchs.
    """
    url = build_youth_calendar_url(base_url, saison, division, tour)
    logger.info("Scraping tour %d division %s: %s", tour, division, url)

    try:
        response = client.get(url)
        content = response.content.decode("windows-1252", errors="replace")
    except Exception as e:
        logger.error("Erreur scraping tour %d/%s: %s", tour, division, e)
        return []

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, "html.parser")

    poules: list[YouthPouleInfo] = []
    current_poule_code: Optional[str] = None
    current_equipes: list[str] = []
    current_club_codes: list[str] = []
    current_nb_matchs: int = 0

    # Les tables alternent classement / calendrier
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue

        # Détecter si c'est un tableau de classement ou de matchs
        first_row = rows[0]
        header_cells = first_row.find_all("td")

        # Tableau de classement : en-têtes contiennent "Points", "Jou.", etc.
        is_standing = any(
            cell.get_text(strip=True) in ("Points", "Jou.", "Gag.", "Per.")
            for cell in header_cells
        )

        # Tableau de matchs : contient "Tour XX" dans le header
        is_matches = any(
            "Tour" in cell.get_text(strip=True)
            for cell in header_cells
        )

        if is_standing:
            # Sauvegarder la poule précédente si elle existe
            if current_poule_code and current_equipes:
                poules.append(YouthPouleInfo(
                    code=current_poule_code,
                    tour_numero=tour,
                    division_code=division,
                    saison=saison,
                    equipes=current_equipes,
                    club_codes=current_club_codes,
                    nb_matchs=current_nb_matchs,
                ))

            # Réinitialiser
            current_equipes = []
            current_club_codes = []
            current_nb_matchs = 0
            current_poule_code = None

            # Extraire les équipes du classement
            for row in rows[1:]:  # Skip header
                cells = row.find_all("td")
                if len(cells) >= 2:
                    team_name = cells[1].get_text(strip=True)
                    if team_name and not team_name.isdigit():
                        current_equipes.append(team_name)

                    # Chercher le code club dans les inputs hidden
                    club_input = row.find("input", {"name": "cnclub"})
                    if club_input:
                        club_code = club_input.get("value", "")
                        if club_code:
                            current_club_codes.append(club_code)

        elif is_matches:
            # Extraire les matchs
            for row in rows[1:]:  # Skip header
                cells = row.find_all("td")
                if len(cells) >= 2:
                    match_code_text = cells[0].get_text(strip=True)
                    if match_code_text and re.match(r'^[A-Z]{2}[A-Z0-9]\d{3}$', match_code_text):
                        current_nb_matchs += 1
                        # Extraire le code poule du code match
                        # Codes can be "CMA001" (3 letters) or "CY3001" (2 letters + digit)
                        poule_code = match_code_text[:3]
                        if not current_poule_code:
                            current_poule_code = poule_code

    # Sauvegarder la dernière poule
    if current_poule_code and current_equipes:
        poules.append(YouthPouleInfo(
            code=current_poule_code,
            tour_numero=tour,
            division_code=division,
            saison=saison,
            equipes=current_equipes,
            club_codes=current_club_codes,
            nb_matchs=current_nb_matchs,
        ))

    logger.info(
        "Tour %d/%s: %d poules, %d matchs total",
        tour, division, len(poules),
        sum(p.nb_matchs for p in poules),
    )

    return poules


# =====================================================================
# Export CSV — Récupération et répartition des matchs ACJEUNES
# =====================================================================
#
# Le endpoint ``vbspo_calendrier_export.php`` IGNORE le paramètre
# ``division=``. Il retourne TOUJOURS l'intégralité des matchs
# ACJEUNES en une seule réponse (~5600 matchs, ~90s).
#
# La stratégie est donc :
#   1. Télécharger le CSV complet UNE SEULE FOIS
#   2. Inférer la division de chaque match depuis son code de poule
#   3. Enrichir chaque match avec les métadonnées correctes
# =====================================================================

# Cache du CSV complet (une seule requête par saison)
_YOUTH_EXPORT_CACHE: dict[str, list] = {}


def fetch_all_youth_matches(
    client: HttpClient,
    base_url: str,
    saison: str,
    *,
    force_refresh: bool = False,
) -> list:
    """Télécharge et parse l'export CSV complet pour ACJEUNES.

    Le résultat est mis en cache pour éviter les requêtes répétées
    (l'export est lent : ~90s).

    Args:
        client: Client HTTP.
        base_url: URL de base FFVB.
        saison: Saison.
        force_refresh: Ignorer le cache.

    Returns:
        Liste brute de ExportMatchInfo (sans métadonnées de division).
    """
    if not force_refresh and saison in _YOUTH_EXPORT_CACHE:
        return _YOUTH_EXPORT_CACHE[saison]

    from pyvolley.scrapers.ffvb.export_scraper import (
        parse_export_csv,
        EXPORT_TIMEOUT,
    )

    url = build_youth_export_url(base_url, saison)
    logger.info("Export CSV complet ACJEUNES: %s", url)

    saved_timeout = client.timeout
    try:
        client._timeout = max(saved_timeout, EXPORT_TIMEOUT, 180)
        response = client.get(url)
    except Exception as e:
        logger.error("Erreur export CSV ACJEUNES: %s", e)
        return []
    finally:
        client._timeout = saved_timeout

    matches = parse_export_csv(response.content, ENTITY_CODE, saison, base_url)
    _YOUTH_EXPORT_CACHE[saison] = matches
    logger.info("Export CSV ACJEUNES: %d matchs bruts", len(matches))
    return matches


def _enrich_match_with_division(match, div_code: str) -> None:
    """Enrichit un ExportMatchInfo avec les métadonnées de sa division."""
    div_info = DIVISION_MAP.get(div_code)
    if not div_info:
        return
    cat_label = DIVISION_CATEGORY_LABEL.get(div_code, div_code)
    genre_label = "Masc." if div_info[1] == "MASCULIN" else "Fém."

    match.division_code = div_code
    match.genre = div_info[1]
    match.categorie_age = div_info[0]
    match.niveau = "NATIONALE"
    match.type_competition = "COUPE"
    match.competition_nom = (
        f"Coupe de France Jeunes {cat_label} {genre_label}"
    )
    match.competition_groupe = f"CdF Jeunes {cat_label} {genre_label}"


def fetch_youth_export(
    client: HttpClient,
    base_url: str,
    saison: str,
    division: Optional[str] = None,
) -> list:
    """Récupère les matchs jeunes enrichis, filtrés par division.

    Télécharge le CSV complet (avec cache) puis filtre et enrichit
    les matchs en se basant sur le code de poule de chaque match
    pour déterminer sa division.

    .. warning::

       Le paramètre ``division`` de l'URL d'export est **ignoré** par
       le serveur FFVB. Le filtrage est effectué côté client via
       ``infer_division_from_poule_code()``.

    Args:
        client: Client HTTP.
        base_url: URL de base FFVB.
        saison: Saison.
        division: Code division optionnel pour ne retourner qu'une
            division (ex: "CMX"). Si None, retourne tout enrichi.

    Returns:
        Liste de ExportMatchInfo enrichies avec les métadonnées jeunes.
    """
    all_matches = fetch_all_youth_matches(client, base_url, saison)

    # Enrichir chaque match en déduisant la division du code de poule
    result = []
    unresolved = 0

    for match in all_matches:
        inferred_div = infer_division_from_poule_code(match.poule_code)

        if not inferred_div:
            unresolved += 1
            # Fallback : catégorie depuis la 1re lettre, genre inconnu
            inferred_div = _fallback_division(match.poule_code)

        if inferred_div:
            _enrich_match_with_division(match, inferred_div)

        # Filtrer par division si demandé
        if division is None or inferred_div == division:
            result.append(match)

    if unresolved:
        logger.warning(
            "Export jeunes: %d matchs avec division non résolue", unresolved,
        )

    if division:
        logger.info(
            "Export jeunes %s: %d matchs (sur %d total)",
            division, len(result), len(all_matches),
        )
    else:
        logger.info(
            "Export jeunes: %d matchs enrichis (%d non résolus)",
            len(result), unresolved,
        )

    return result


def fetch_youth_export_by_division(
    client: HttpClient,
    base_url: str,
    saison: str,
) -> dict[str, list]:
    """Récupère tous les matchs jeunes, groupés par division.

    Un seul téléchargement CSV, mais les matchs sont répartis dans
    un dict {division_code: [ExportMatchInfo]}.

    Args:
        client: Client HTTP.
        base_url: URL de base FFVB.
        saison: Saison.

    Returns:
        Dict {division_code: [ExportMatchInfo]}.
    """
    from collections import defaultdict

    all_matches = fetch_all_youth_matches(client, base_url, saison)
    by_division: dict[str, list] = defaultdict(list)

    for match in all_matches:
        div_code = infer_division_from_poule_code(match.poule_code)
        if not div_code:
            div_code = _fallback_division(match.poule_code) or "INCONNU"

        _enrich_match_with_division(match, div_code)
        by_division[div_code].append(match)

    for div_code, matches in by_division.items():
        logger.info(
            "Division jeune %s: %d matchs", div_code, len(matches),
        )

    return dict(by_division)


def _fallback_division(poule_code: str) -> Optional[str]:
    """Fallback : devine la division masculine par défaut."""
    if not poule_code:
        return None
    first = poule_code[0].upper()
    cat_info = CATEGORY_LETTER_MAP.get(first)
    if cat_info:
        # Retourne la division masculine par défaut
        return cat_info[1]
    return None


def clear_youth_export_cache() -> None:
    """Vide le cache de l'export CSV jeunes."""
    _YOUTH_EXPORT_CACHE.clear()


# =====================================================================
# Construction d'un index enrichi (nav + export)
# =====================================================================


def build_youth_cup_index(
    client: HttpClient,
    base_url: str,
    saison: str,
    *,
    scrape_tours: bool = False,
    divisions: Optional[list[str]] = None,
) -> YouthCupIndex:
    """Construit l'index complet de la Coupe de France Jeunes.

    Phase 1 : Scrape la navigation pour découvrir la structure.
    Phase 2 (si ``scrape_tours=True``) : Scrape chaque tour pour
    découvrir les poules et les équipes.

    Args:
        client: Client HTTP.
        base_url: URL de base FFVB.
        saison: Saison.
        scrape_tours: Si True, scrape aussi chaque tour individuellement.
        divisions: Liste optionnelle de codes division à scraper
            (par défaut : toutes).

    Returns:
        YouthCupIndex complet.
    """
    index = scrape_youth_nav(client, base_url, saison)

    if not scrape_tours:
        return index

    target_divisions = divisions or list(index.divisions.keys())

    for div_code in target_divisions:
        division = index.get_division(div_code)
        if not division:
            logger.warning("Division %s non trouvée dans l'index", div_code)
            continue

        for tour in division.tours:
            poules = scrape_youth_tour(
                client, base_url, saison,
                division.code, tour.numero,
            )
            tour.poules = poules

    return index


# =====================================================================
# Cache de l'index jeunes
# =====================================================================

_YOUTH_INDEX_CACHE: dict[str, YouthCupIndex] = {}


def get_youth_cup_index(
    client: HttpClient,
    base_url: str,
    saison: str,
    *,
    force_refresh: bool = False,
) -> YouthCupIndex:
    """Récupère ou construit l'index jeunes (avec cache)."""
    if not force_refresh and saison in _YOUTH_INDEX_CACHE:
        return _YOUTH_INDEX_CACHE[saison]

    index = build_youth_cup_index(client, base_url, saison)
    _YOUTH_INDEX_CACHE[saison] = index
    return index


def clear_youth_cache() -> None:
    """Vide tous les caches du module jeunes (index + export)."""
    _YOUTH_INDEX_CACHE.clear()
    _YOUTH_EXPORT_CACHE.clear()
