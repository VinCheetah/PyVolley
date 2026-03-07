"""
Scraper pour l'adressier FFVB (``adressier_pdf.php``).

L'adressier fournit les informations détaillées sur les clubs inscrits
dans une ou plusieurs poules d'une entité : coordonnées du correspondant,
couleurs, président, entraîneur, salles (nom, adresse, sol, capacité,
transport).

L'endpoint est ``POST /ffvbapp/adressier/adressier_pdf.php`` avec :
- ``adr_poule[]`` : codes des poules à inclure (un ou plusieurs)
- ``codent`` : code de l'entité (ex: ``ABCCS``)
- ``wss_get_saison`` : saison au format ``YYYY/YYYY``
- ``typ_edition`` : ``E`` pour l'export CSV

Le résultat est un fichier CSV (séparateur ``;``, encodage ``windows-1252``)
avec 36 colonnes par club.  Un même club peut apparaître plusieurs fois
s'il est dans plusieurs poules.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

from pyvolley.scrapers.http_client import HttpClient

logger = logging.getLogger(__name__)


# =====================================================================
# Colonnes de l'adressier (indices zéro-based, séparateur ;)
# =====================================================================
COL_ENTITE = 0
COL_POULE = 1
COL_NCLUB = 2        # Code club FFVB (ex: "0622126")
COL_NOM_CLUB = 3
COL_LIGUE = 4
COL_POSITION = 5
COL_COULEURS = 6
COL_PRESIDENT = 7    # Pdt
COL_ENTRAINEUR = 8   # Entr.
COL_ADJOINT = 9      # Adj.
COL_CORRESPONDANT = 10
COL_CO_ADR1 = 11
COL_CO_ADR2 = 12
COL_CO_ADR3 = 13
COL_CO_VILLE = 14
COL_CO_TEL = 15
COL_CO_PORT = 16
COL_CO_MAIL = 17
# Salle 1
COL_S1_NOM = 18
COL_S1_ADR1 = 19
COL_S1_ADR2 = 20
COL_S1_ADR3 = 21
COL_S1_VILLE = 22
COL_S1_TEL = 23
COL_S1_SOL = 24
COL_S1_CAP = 25
COL_S1_TRSP = 26
# Salle 2
COL_S2_NOM = 27
COL_S2_ADR1 = 28
COL_S2_ADR2 = 29
COL_S2_ADR3 = 30
COL_S2_VILLE = 31
COL_S2_TEL = 32
COL_S2_SOL = 33
COL_S2_CAP = 34
COL_S2_TRSP = 35

MIN_COLUMNS = 18  # Minimum pour les données de base (jusqu'à Co_Mail)

# Timeout pour l'adressier (plus rapide que l'export CSV)
ADRESSIER_TIMEOUT = 60

ADRESSIER_URL_PATH = "ffvbapp/adressier/adressier_pdf.php"


@dataclass
class SalleInfo:
    """Informations sur une salle de club."""
    numero: int  # 1 ou 2
    nom: Optional[str] = None
    adresse: Optional[str] = None
    ville: Optional[str] = None
    telephone: Optional[str] = None
    sol: Optional[str] = None
    capacite: Optional[int] = None
    transport: Optional[str] = None


@dataclass
class AdressierClubInfo:
    """Informations complètes d'un club depuis l'adressier FFVB.

    Contient toutes les données disponibles pour un club : identité,
    dirigeants, coordonnées du correspondant, et salles.
    """
    code_ffvb: str
    nom: str
    ligue: Optional[str] = None
    poule: Optional[str] = None
    position: Optional[int] = None
    couleurs: Optional[str] = None

    # Dirigeants
    president: Optional[str] = None
    entraineur: Optional[str] = None
    entraineur_adjoint: Optional[str] = None

    # Correspondant
    correspondant_nom: Optional[str] = None
    correspondant_adresse: Optional[str] = None
    correspondant_ville: Optional[str] = None
    correspondant_telephone: Optional[str] = None
    correspondant_portable: Optional[str] = None
    correspondant_email: Optional[str] = None

    # Salles
    salles: list[SalleInfo] = field(default_factory=list)


def _clean(value: str) -> Optional[str]:
    """Nettoie une chaîne de caractères (strip + None si vide)."""
    if not value:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _clean_address(*parts: str) -> Optional[str]:
    """Construit une adresse à partir de plusieurs parties (Adr1, Adr2, Adr3)."""
    parts_clean = [p.strip() for p in parts if p and p.strip()]
    return ", ".join(parts_clean) if parts_clean else None


def _parse_capacite(cap_str: str) -> Optional[int]:
    """Parse la capacité d'une salle en entier."""
    if not cap_str or not cap_str.strip():
        return None
    try:
        val = int(cap_str.strip())
        return val if val > 0 else None
    except ValueError:
        return None


def _parse_salle(row: list[str], num: int, nom_col: int) -> Optional[SalleInfo]:
    """Parse une salle (S1 ou S2) depuis une ligne CSV.

    Args:
        row: Ligne CSV.
        num: Numéro de la salle (1 ou 2).
        nom_col: Index de la colonne S{n}_Nom.
    """
    if nom_col >= len(row):
        return None

    nom = _clean(row[nom_col])
    if not nom:
        return None

    adr1 = row[nom_col + 1] if nom_col + 1 < len(row) else ""
    adr2 = row[nom_col + 2] if nom_col + 2 < len(row) else ""
    adr3 = row[nom_col + 3] if nom_col + 3 < len(row) else ""
    ville = row[nom_col + 4] if nom_col + 4 < len(row) else ""
    tel = row[nom_col + 5] if nom_col + 5 < len(row) else ""
    sol = row[nom_col + 6] if nom_col + 6 < len(row) else ""
    cap = row[nom_col + 7] if nom_col + 7 < len(row) else ""
    trsp = row[nom_col + 8] if nom_col + 8 < len(row) else ""

    return SalleInfo(
        numero=num,
        nom=nom,
        adresse=_clean_address(adr1, adr2, adr3),
        ville=_clean(ville),
        telephone=_clean(tel),
        sol=_clean(sol),
        capacite=_parse_capacite(cap),
        transport=_clean(trsp),
    )


def parse_adressier_csv(
    content_bytes: bytes,
) -> list[AdressierClubInfo]:
    """Parse le contenu brut d'un export adressier CSV FFVB.

    Args:
        content_bytes: Contenu brut de la réponse HTTP.

    Returns:
        Liste d'``AdressierClubInfo`` (un par club/poule trouvé).
    """
    # Décodage — l'adressier est en windows-1252
    try:
        content = content_bytes.decode("windows-1252")
    except (UnicodeDecodeError, AttributeError):
        try:
            content = content_bytes.decode("latin-1")
        except Exception:
            logger.error("Impossible de décoder l'adressier")
            return []

    if not content.strip():
        logger.warning("Adressier vide")
        return []

    reader = csv.reader(io.StringIO(content), delimiter=";")
    clubs: list[AdressierClubInfo] = []

    header_skipped = False
    for row in reader:
        if not header_skipped:
            header_skipped = True
            continue

        if len(row) < MIN_COLUMNS:
            continue

        code_ffvb = _clean(row[COL_NCLUB])
        nom = _clean(row[COL_NOM_CLUB])
        if not code_ffvb or not nom:
            continue

        # Position
        position = None
        pos_str = _clean(row[COL_POSITION])
        if pos_str:
            try:
                position = int(pos_str)
            except ValueError:
                pass

        # Correspondant adresse
        co_adr = _clean_address(
            row[COL_CO_ADR1] if COL_CO_ADR1 < len(row) else "",
            row[COL_CO_ADR2] if COL_CO_ADR2 < len(row) else "",
            row[COL_CO_ADR3] if COL_CO_ADR3 < len(row) else "",
        )

        # Salles
        salles: list[SalleInfo] = []
        s1 = _parse_salle(row, 1, COL_S1_NOM)
        if s1:
            salles.append(s1)
        s2 = _parse_salle(row, 2, COL_S2_NOM)
        if s2:
            salles.append(s2)

        club_info = AdressierClubInfo(
            code_ffvb=code_ffvb,
            nom=nom,
            ligue=_clean(row[COL_LIGUE]),
            poule=_clean(row[COL_POULE]),
            position=position,
            couleurs=_clean(row[COL_COULEURS]),
            president=_clean(row[COL_PRESIDENT]),
            entraineur=_clean(row[COL_ENTRAINEUR]),
            entraineur_adjoint=_clean(row[COL_ADJOINT]) if COL_ADJOINT < len(row) else None,
            correspondant_nom=_clean(row[COL_CORRESPONDANT]),
            correspondant_adresse=co_adr,
            correspondant_ville=_clean(row[COL_CO_VILLE]) if COL_CO_VILLE < len(row) else None,
            correspondant_telephone=_clean(row[COL_CO_TEL]) if COL_CO_TEL < len(row) else None,
            correspondant_portable=_clean(row[COL_CO_PORT]) if COL_CO_PORT < len(row) else None,
            correspondant_email=_clean(row[COL_CO_MAIL]) if COL_CO_MAIL < len(row) else None,
            salles=salles,
        )
        clubs.append(club_info)

    logger.info(
        "Adressier: %d entrées club trouvées (%d clubs uniques)",
        len(clubs),
        len({c.code_ffvb for c in clubs}),
    )
    return clubs


def build_adressier_url(base_url: str) -> str:
    """Construit l'URL de base de l'adressier."""
    # The adressier is under /ffvbapp/adressier/, not /ffvbapp/resu/
    base = base_url.rstrip("/")
    if base.endswith("/resu"):
        base = base[:-5]
    elif base.endswith("/ffvbapp/resu"):
        base = base[:-5]
    return f"{base}/adressier/adressier_pdf.php"


def fetch_adressier(
    client: HttpClient,
    base_url: str,
    entite_code: str,
    saison: str,
    poule_codes: list[str],
) -> list[AdressierClubInfo]:
    """Télécharge et parse l'adressier FFVB pour une liste de poules.

    Args:
        client: Client HTTP configuré.
        base_url: URL de base FFVB (ex: ``https://www.ffvbbeach.org/ffvbapp/resu/``).
        entite_code: Code de l'entité (ex: ``ABCCS``).
        saison: Saison au format ``YYYY/YYYY``.
        poule_codes: Liste des codes de poules à inclure.

    Returns:
        Liste d'``AdressierClubInfo`` (dédupliquée par code club FFVB).
    """
    if not poule_codes:
        logger.warning("Aucune poule spécifiée pour l'adressier")
        return []

    url = build_adressier_url(base_url)

    # Construire les données POST
    data: dict[str, str | list[str]] = {
        "codent": entite_code,
        "wss_get_saison": saison,
        "typ_edition": "E",
    }

    logger.info(
        "Téléchargement adressier: %s (%d poules, saison=%s)",
        entite_code, len(poule_codes), saison,
    )

    saved_timeout = client.timeout
    try:
        client._timeout = max(saved_timeout, ADRESSIER_TIMEOUT)
        # POST with list of poule codes
        post_data = [("codent", entite_code), ("wss_get_saison", saison), ("typ_edition", "E")]
        for code in poule_codes:
            post_data.append(("adr_poule[]", code))

        response = client.post(url, data=post_data)
    except Exception as e:
        logger.error("Erreur téléchargement adressier %s: %s", entite_code, e)
        return []
    finally:
        client._timeout = saved_timeout

    all_clubs = parse_adressier_csv(response.content)

    # Dédupliquer par code_ffvb (garder la première occurrence = rang le plus élevé)
    seen: set[str] = set()
    unique_clubs: list[AdressierClubInfo] = []
    for club in all_clubs:
        if club.code_ffvb not in seen:
            seen.add(club.code_ffvb)
            unique_clubs.append(club)

    logger.info(
        "Adressier %s: %d clubs uniques (sur %d entrées)",
        entite_code, len(unique_clubs), len(all_clubs),
    )

    return unique_clubs


def build_club_planning_url(
    base_url: str, entite_code: str, code_ffvb: str,
) -> str:
    """Construit l'URL de la page planning d'un club."""
    return (
        f"{base_url.rstrip('/')}/planning_club.php"
        f"?codent={entite_code}&cnclub={code_ffvb}"
    )


def build_club_classement_url(
    base_url: str, entite_code: str, saison: str, code_ffvb: str,
) -> str:
    """Construit l'URL de la page classement d'un club."""
    from urllib.parse import quote
    return (
        f"{base_url.rstrip('/')}/planning_club_class.php"
        f"?codent={entite_code}&saison={quote(saison)}&cnclub={code_ffvb}"
    )
