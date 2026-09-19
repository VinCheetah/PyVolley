"""
Scraper pour l'annuaire fédéral officiel de la FFVB (``rech_aff_club.php``).

Permet de moissonner l'ensemble du référentiel national :
- 23 Ligues Régionales (coordonnées, siège, président, site web, email)
- ~95 Comités Départementaux (code, nom, ligue de rattachement, site web, email)
- 1 293 Clubs affiliés (code FFVB, nom, ligue, comité, email, site web)
- Fiche détaillée de club (siège social avec rue, CP et ville, couleurs, dirigeants)
"""

from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from pyvolley.core.config import settings
from pyvolley.scrapers.http_client import HttpClient

logger = logging.getLogger(__name__)

# Liste canonique des 23 Ligues régionales de la FFVB
FFVB_LIGUES = [
    ("09", "AUVERGNE-RHÔNE-ALPES"),
    ("04", "BOURGOGNE-FRANCHE-COMTE"),
    ("05", "BRETAGNE"),
    ("06", "CENTRE-VAL DE LOIRE"),
    ("30", "CORSE"),
    ("16", "GRAND EST"),
    ("24", "GUADELOUPE"),
    ("26", "GUYANE"),
    ("10", "HAUTS-DE-FRANCE"),
    ("13", "ILE-DE-FRANCE"),
    ("35", "ILES DU NORD"),
    ("27", "LA REUNION"),
    ("25", "MARTINIQUE"),
    ("31", "MAYOTTE"),
    ("18", "NORMANDIE"),
    ("12", "NOUVELLE AQUITAINE"),
    ("28", "NOUVELLE CALEDONIE"),
    ("14", "OCCITANIE"),
    ("02", "PAYS DE LA LOIRE"),
    ("08", "PROVENCE-ALPES-CÔTE D’AZUR"),
    ("34", "ST-PIERRE ET MIQUELON"),
    ("32", "TAHITI"),
    ("29", "WALLIS ET FUTUNA"),
]

ANNUAIRE_URL_PATH = "ffvbapp/adressier/rech_aff_club.php"


@dataclass
class AnnuaireLigueInfo:
    """Informations officielles d'une ligue régionale."""
    code: str
    nom: str
    telephone: Optional[str] = None
    email: Optional[str] = None
    site_web: Optional[str] = None
    adresse_siege: Optional[str] = None
    president: Optional[str] = None


@dataclass
class AnnuaireComiteInfo:
    """Informations officielles d'un comité départemental."""
    code: str  # ex: "075"
    nom: str  # ex: "Paris"
    numero_departement: Optional[str] = None  # ex: "75"
    ligue_code: str = ""
    email: Optional[str] = None
    site_web: Optional[str] = None
    telephone: Optional[str] = None
    adresse_siege: Optional[str] = None


@dataclass
class AnnuaireClubInfo:
    """Informations d'un club dans l'annuaire fédéral."""
    code_ffvb: str  # 7 chiffres (ex: "0750001")
    nom: str
    ligue_code: str
    comite_code: str  # 3 chiffres (ex: "075")
    email: Optional[str] = None
    site_web: Optional[str] = None
    telephone: Optional[str] = None
    adresse_siege: Optional[str] = None
    code_postal_siege: Optional[str] = None
    ville_siege: Optional[str] = None
    couleurs: Optional[str] = None
    president: Optional[str] = None
    correspondant_nom: Optional[str] = None


@dataclass
class AnnuaireFicheClub:
    """Fiche détaillée d'un club obtenue par son identifiant id_club."""
    code_ffvb: str
    nom: str
    couleurs: Optional[str] = None
    telephone: Optional[str] = None
    portable: Optional[str] = None
    fax: Optional[str] = None
    email: Optional[str] = None
    adresse_siege: Optional[str] = None
    code_postal_siege: Optional[str] = None
    ville_siege: Optional[str] = None
    correspondant_nom: Optional[str] = None
    president: Optional[str] = None


def build_annuaire_url(base_url: str) -> str:
    """Construit l'URL vers rech_aff_club.php."""
    base = base_url.rstrip("/")
    if base.endswith("/resu"):
        base = base[:-5]
    elif base.endswith("/ffvbapp/resu"):
        base = base[:-5]
    return f"{base}/adressier/rech_aff_club.php"


def _get_cache_dir() -> Path:
    cache_dir = settings.data_dir / "cache" / "annuaire"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _clean_str(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    cleaned = val.strip()
    return cleaned if cleaned else None


def _departement_from_comite_code(comite_code: str) -> Optional[str]:
    """Convertit un code comité à 3 chiffres (ex: '075') en numéro de département (ex: '75')."""
    if not comite_code:
        return None
    code = comite_code.strip()
    if code.startswith("0") and len(code) == 3 and code[1:].isdigit():
        return code[1:]
    return code


def parse_ligue_annuaire_html(
    raw_html: str,
    ligue_code: str,
    default_ligue_nom: str = "",
) -> tuple[AnnuaireLigueInfo, list[AnnuaireComiteInfo], list[AnnuaireClubInfo]]:
    """Parse le HTML renvoyé par rech_aff_club.php pour une ligue."""
    soup = BeautifulSoup(raw_html, "html.parser")

    # 1. Extraction Ligue
    title_td = soup.find("td", class_="titreblanc_gd")
    ligue_nom = default_ligue_nom
    if title_td:
        t_text = title_td.get_text(strip=True)
        if t_text.lower().startswith("ligue "):
            ligue_nom = t_text[6:].strip()
        elif t_text:
            ligue_nom = t_text

    telephone = None
    email = None
    site_web = None
    adresse_siege = None
    president = None

    for tr in soup.find_all("tr"):
        for td in tr.find_all("td", class_="liengris_pt"):
            label = td.get_text(strip=True).lower()
            val_td = td.find_next_sibling("td")
            if val_td:
                val = val_td.get_text(strip=True)
                if "tél" in label or "tel" in label:
                    telephone = _clean_str(val)
                elif "président" in label or "president" in label:
                    president = _clean_str(val)

    mail_a = soup.find("a", href=re.compile(r"^mailto:", re.I))
    if mail_a:
        email = _clean_str(mail_a.get("href", "").replace("mailto:", "").strip())

    site_a = soup.find("a", href=re.compile(r"^https?://", re.I), target="_blank")
    if site_a and "ffvb" not in site_a.get("href", "").lower():
        site_web = _clean_str(site_a.get("href", "").strip())

    ligue_info = AnnuaireLigueInfo(
        code=ligue_code,
        nom=ligue_nom,
        telephone=telephone,
        email=email,
        site_web=site_web,
        adresse_siege=adresse_siege,
        president=president,
    )

    # 2. Extraction Comités Départementaux
    comites: list[AnnuaireComiteInfo] = []
    seen_comites: set[str] = set()
    for tr in soup.find_all("tr"):
        code_td = tr.find("td", class_="liensuite4_gd", align="center")
        if code_td and re.match(r"^\d{3}$", code_td.get_text(strip=True)):
            c_code = code_td.get_text(strip=True)
            if c_code in seen_comites:
                continue
            nom_td = code_td.find_next_sibling("td", class_="liensuite4_gd")
            c_nom = nom_td.get_text(strip=True) if nom_td else ""
            c_mail = None
            c_site = None
            m_link = tr.find("a", href=re.compile(r"^mailto:", re.I))
            if m_link:
                c_mail = _clean_str(m_link.get("href", "").replace("mailto:", ""))
            w_link = tr.find("a", href=re.compile(r"^https?://", re.I))
            if w_link and "ffvb" not in w_link.get("href", "").lower():
                c_site = _clean_str(w_link.get("href"))

            seen_comites.add(c_code)
            comites.append(
                AnnuaireComiteInfo(
                    code=c_code,
                    numero_departement=_departement_from_comite_code(c_code),
                    nom=c_nom,
                    ligue_code=ligue_code,
                    email=c_mail,
                    site_web=c_site,
                )
            )

    # 3. Extraction Clubs
    clubs_dict: dict[str, AnnuaireClubInfo] = {}
    for tr in soup.find_all("tr"):
        c_code_td = tr.find("td", class_="lienquestion", align="center")
        if not c_code_td:
            continue
        c_code = c_code_td.get_text(strip=True)
        if not re.match(r"^\d{7}$", c_code):
            continue

        nom_td = tr.find(
            lambda tag: tag.name == "td"
            and "lienquestion" in tag.get("class", [])
            and tag.get("align") != "center"
        )
        c_nom = nom_td.get_text(strip=True) if nom_td else ""
        if not c_nom:
            continue

        c_comite = c_code[:3]

        c_mail = None
        m_link = tr.find("a", href=re.compile(r"^mailto:", re.I))
        if m_link:
            c_mail = _clean_str(m_link.get("href", "").replace("mailto:", ""))

        c_site = None
        s_link = tr.find("a", href=re.compile(r"^https?://", re.I))
        if s_link and "ffvb" not in s_link.get("href", "").lower():
            c_site = _clean_str(s_link.get("href"))

        if c_code not in clubs_dict:
            clubs_dict[c_code] = AnnuaireClubInfo(
                code_ffvb=c_code,
                nom=c_nom,
                ligue_code=ligue_code,
                comite_code=c_comite,
                email=c_mail,
                site_web=c_site,
            )
        else:
            if not clubs_dict[c_code].email and c_mail:
                clubs_dict[c_code].email = c_mail
            if not clubs_dict[c_code].site_web and c_site:
                clubs_dict[c_code].site_web = c_site

    return ligue_info, comites, list(clubs_dict.values())


def parse_club_fiche_html(raw_html: str, code_ffvb: str) -> AnnuaireFicheClub:
    """Parse la fiche détaillée d'un club (id_club)."""
    soup = BeautifulSoup(raw_html, "html.parser")

    nom = ""
    title_td = soup.find("td", class_="titreblanc_gd")
    if title_td:
        t_text = title_td.get_text(strip=True)
        if t_text.startswith(code_ffvb):
            nom = t_text[len(code_ffvb):].strip()
        else:
            nom = t_text

    couleurs = None
    col_match = re.search(r"Couleurs du club:\s*</span>\s*([^<]+)", raw_html, re.I)
    if col_match:
        couleurs = _clean_str(col_match.group(1))

    telephone = None
    portable = None
    fax = None
    email = None
    adresse_siege = None
    code_postal_siege = None
    ville_siege = None
    correspondant_nom = None
    president = None

    for section_td in soup.find_all("td", class_="lienblanc_pt"):
        sec_title = section_td.get_text(strip=True).lower()
        table = section_td.find_parent("table")
        if not table:
            continue

        rows = table.find_all("tr")
        if "coordonnées" in sec_title or "coordonnees" in sec_title:
            for tr in rows:
                tds = tr.find_all("td")
                if len(tds) >= 2:
                    label = tds[0].get_text(strip=True).lower()
                    val = tds[1].get_text(strip=True)
                    if "tél" in label or "tel" in label:
                        telephone = _clean_str(val)
                    elif "portable" in label:
                        portable = _clean_str(val)
                    elif "fax" in label:
                        fax = _clean_str(val)
            m_a = table.find("a", href=re.compile(r"^mailto:", re.I))
            if m_a:
                email = _clean_str(m_a.get("href", "").replace("mailto:", ""))

        elif "siège social" in sec_title or "siege social" in sec_title:
            lines = []
            for tr in rows:
                for td in tr.find_all("td", class_="lienquestion"):
                    txt = td.get_text(strip=True)
                    if txt:
                        lines.append(txt)
            if lines:
                if len(lines) == 1:
                    adresse_siege = lines[0]
                else:
                    adresse_siege = lines[0]
                    cp_city = lines[1]
                    m_cp = re.match(r"^(\d{5})\s+(.+)$", cp_city)
                    if m_cp:
                        code_postal_siege = m_cp.group(1)
                        ville_siege = m_cp.group(2).strip()
                    else:
                        ville_siege = cp_city

        elif "correspondant" in sec_title:
            for tr in rows:
                c_td = tr.find("td", class_="lienquestion")
                if c_td:
                    correspondant_nom = _clean_str(c_td.get_text(strip=True))

    return AnnuaireFicheClub(
        code_ffvb=code_ffvb,
        nom=nom,
        couleurs=couleurs,
        telephone=telephone,
        portable=portable,
        fax=fax,
        email=email,
        adresse_siege=adresse_siege,
        code_postal_siege=code_postal_siege,
        ville_siege=ville_siege,
        correspondant_nom=correspondant_nom,
        president=president,
    )


class AnnuaireScraper:
    """Scraper principal pour l'annuaire fédéral FFVB."""

    def __init__(self, client: Optional[HttpClient] = None, base_url: Optional[str] = None):
        self.client = client or HttpClient()
        self.base_url = base_url or settings.ffvb_base_url
        self.annuaire_url = build_annuaire_url(self.base_url)

    def fetch_ligue_annuaire(
        self,
        ligue_code: str,
        ligue_nom: str = "",
        force_refresh: bool = False,
    ) -> tuple[AnnuaireLigueInfo, list[AnnuaireComiteInfo], list[AnnuaireClubInfo]]:
        """Télécharge et parse l'annuaire pour une ligue."""
        cache_path = _get_cache_dir() / f"ligue_{ligue_code}.html"

        raw_html = None
        if not force_refresh and cache_path.exists():
            try:
                if (time.time() - cache_path.stat().st_mtime) < (48 * 3600):
                    raw_html = cache_path.read_text(encoding="windows-1252", errors="replace")
            except Exception as e:
                logger.debug("Erreur lecture cache ligue %s: %s", ligue_code, e)

        if not raw_html:
            data = [
                ("ws_new_ligue", ligue_code),
                ("ws_new_comit", "0"),
                ("ws_list_dep", ""),
                ("id_club", ""),
            ]
            resp = self.client.post(self.annuaire_url, data=data)
            raw_html = resp.content.decode("windows-1252", errors="replace")
            try:
                cache_path.write_bytes(resp.content)
            except Exception as e:
                logger.debug("Erreur sauvegarde cache ligue %s: %s", ligue_code, e)

        return parse_ligue_annuaire_html(raw_html, ligue_code, ligue_nom)

    def fetch_club_fiche(
        self,
        code_ffvb: str,
        force_refresh: bool = False,
    ) -> AnnuaireFicheClub:
        """Télécharge et parse la fiche détaillée d'un club (id_club)."""
        cache_path = _get_cache_dir() / f"club_{code_ffvb}.html"

        raw_html = None
        if not force_refresh and cache_path.exists():
            try:
                if (time.time() - cache_path.stat().st_mtime) < (7 * 86400):
                    raw_html = cache_path.read_text(encoding="windows-1252", errors="replace")
            except Exception as e:
                logger.debug("Erreur lecture cache club %s: %s", code_ffvb, e)

        if not raw_html:
            data = [
                ("ws_new_ligue", "0"),
                ("ws_new_comit", "0"),
                ("ws_list_dep", ""),
                ("id_club", code_ffvb),
            ]
            resp = self.client.post(self.annuaire_url, data=data)
            raw_html = resp.content.decode("windows-1252", errors="replace")
            try:
                cache_path.write_bytes(resp.content)
            except Exception as e:
                logger.debug("Erreur sauvegarde cache club %s: %s", code_ffvb, e)

        return parse_club_fiche_html(raw_html, code_ffvb)

    def scrape_all_ligues(
        self,
        force_refresh: bool = False,
        max_workers: int = 6,
    ) -> tuple[list[AnnuaireLigueInfo], list[AnnuaireComiteInfo], list[AnnuaireClubInfo]]:
        """Scrape en parallèle les 23 ligues régionales et consolide l'ensemble."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        all_ligues: list[AnnuaireLigueInfo] = []
        all_comites: list[AnnuaireComiteInfo] = []
        all_clubs: dict[str, AnnuaireClubInfo] = {}

        logger.info("Début scraping annuaire fédéral (%d ligues, %d workers)...", len(FFVB_LIGUES), max_workers)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_code = {
                executor.submit(
                    self.fetch_ligue_annuaire, code, nom, force_refresh=force_refresh
                ): (code, nom)
                for code, nom in FFVB_LIGUES
            }

            for future in as_completed(future_to_code):
                code, nom = future_to_code[future]
                try:
                    ligue_info, comites, clubs = future.result()
                    all_ligues.append(ligue_info)
                    all_comites.extend(comites)
                    for club in clubs:
                        if club.code_ffvb not in all_clubs:
                            all_clubs[club.code_ffvb] = club
                        else:
                            existing = all_clubs[club.code_ffvb]
                            if not existing.email and club.email:
                                existing.email = club.email
                            if not existing.site_web and club.site_web:
                                existing.site_web = club.site_web
                except Exception as e:
                    logger.error("Erreur scraping ligue %s (%s): %s", code, nom, e)

        unique_comites_map = {c.code: c for c in all_comites}

        logger.info(
            "Scraping annuaire terminé: %d ligues, %d comités, %d clubs.",
            len(all_ligues),
            len(unique_comites_map),
            len(all_clubs),
        )

        return all_ligues, list(unique_comites_map.values()), list(all_clubs.values())
