"""
Scraper pour le site FFVB (ffvbbeach.org).
"""

import re
import time
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from pyvolley.core.config import settings
from pyvolley.core.exceptions import NetworkError, PageNotFoundError, ScrapingError
from pyvolley.scrapers.base import (
    BaseScraper,
    CompetitionInfo,
    MatchInfo,
    ScrapeResult,
)


class FFVBScraper(BaseScraper):
    """
    Scraper pour le site des résultats FFVB.
    
    URL de base: https://www.ffvbbeach.org/ffvbapp/resu/
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        request_delay: Optional[float] = None,
        timeout: Optional[int] = None,
    ):
        self._base_url = base_url or settings.ffvb_base_url
        self._delay = request_delay or settings.ffvb_request_delay
        self._timeout = timeout or settings.ffvb_timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; PyVolley/0.1)"
        })
        self._last_request_time = 0.0
    
    @property
    def name(self) -> str:
        return "FFVB"
    
    @property
    def base_url(self) -> str:
        return self._base_url
    
    def _rate_limit(self):
        """Applique le délai entre les requêtes."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_request_time = time.time()
    
    def _get(self, url: str) -> requests.Response:
        """Effectue une requête GET avec gestion des erreurs."""
        self._rate_limit()
        try:
            response = self._session.get(url, timeout=self._timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise PageNotFoundError(f"Page non trouvée: {url}")
            raise NetworkError(f"Erreur HTTP {e.response.status_code}: {url}")
        except requests.exceptions.RequestException as e:
            raise NetworkError(f"Erreur réseau: {e}")
    
    def _get_soup(self, url: str) -> BeautifulSoup:
        """Récupère et parse une page HTML."""
        response = self._get(url)
        return BeautifulSoup(response.content, "html.parser")
    
    def get_ligues(self) -> list[dict]:
        """
        Récupère la liste des ligues depuis la page d'accueil.
        
        Returns:
            Liste de dictionnaires {code, nom}
        """
        url = urljoin(self.base_url, "vbspo_calendrier.php")
        soup = self._get_soup(url)
        
        ligues = []
        select = soup.find("select", {"name": "saession"})
        if select:
            for option in select.find_all("option"):
                code = option.get("value", "")
                nom = option.text.strip()
                if code and len(code) > 2:
                    # Format: AAAAMMJJ_CODE (ex: 20240901_LIIDF)
                    parts = code.split("_")
                    if len(parts) >= 2:
                        ligues.append({
                            "code": parts[-1],
                            "nom": nom,
                            "session": code
                        })
        
        return ligues
    
    def get_competitions(
        self, 
        ligue_code: str, 
        saison: Optional[str] = None
    ) -> list[CompetitionInfo]:
        """
        Récupère les compétitions d'une ligue.
        
        Args:
            ligue_code: Code de la ligue (ex: LIIDF)
            saison: Saison au format AAAAMMJJ_CODE (optionnel)
        """
        # Construire l'URL
        if saison:
            url = urljoin(self.base_url, f"vbspo_calendrier.php?saession={saison}")
        else:
            url = urljoin(self.base_url, f"vbspo_calendrier.php")
        
        soup = self._get_soup(url)
        competitions = []
        
        # Chercher les liens vers les compétitions
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "codent=" in href:
                match = re.search(r"codent=(\w+)", href)
                if match:
                    code = match.group(1)
                    nom = link.text.strip()
                    
                    # Détecter genre et catégorie depuis le nom
                    genre = self._detect_genre(nom)
                    categorie = self._detect_categorie(nom)
                    
                    competitions.append(CompetitionInfo(
                        code=code,
                        nom=nom,
                        ligue_code=ligue_code,
                        saison=saison or "current",
                        genre=genre,
                        categorie=categorie
                    ))
        
        return competitions
    
    def _detect_genre(self, nom: str) -> Optional[str]:
        """Détecte le genre depuis le nom de compétition."""
        nom_upper = nom.upper()
        if "MASCULIN" in nom_upper or " M " in f" {nom_upper} ":
            return "MASCULIN"
        elif "FEMININ" in nom_upper or "FÉMININ" in nom_upper or " F " in f" {nom_upper} ":
            return "FEMININ"
        return None
    
    def _detect_categorie(self, nom: str) -> Optional[str]:
        """Détecte la catégorie depuis le nom de compétition."""
        nom_upper = nom.upper()
        if "SENIOR" in nom_upper:
            return "SENIOR"
        for cat in ["M21", "M20", "M18", "M17", "M15", "M13"]:
            if cat in nom_upper:
                return cat
        return None
    
    def get_poules(self, competition_code: str, ligue_code: str) -> list[dict]:
        """
        Récupère les poules d'une compétition.
        
        Returns:
            Liste de {code, nom}
        """
        url = urljoin(
            self.base_url, 
            f"vbspo_calendrier.php?codent={competition_code}"
        )
        soup = self._get_soup(url)
        
        poules = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "poession=" in href:
                match = re.search(r"poession=(\w+)", href)
                if match:
                    poules.append({
                        "code": match.group(1),
                        "nom": link.text.strip()
                    })
        
        return poules
    
    def get_matches(self, competition: CompetitionInfo) -> Iterator[MatchInfo]:
        """
        Récupère les matchs d'une compétition.
        
        Yields:
            MatchInfo pour chaque match trouvé
        """
        # D'abord récupérer les poules
        poules = self.get_poules(competition.code, competition.ligue_code)
        
        for poule in poules:
            url = urljoin(
                self.base_url,
                f"vbspo_calendrier.php?codent={competition.code}&poession={poule['code']}"
            )
            soup = self._get_soup(url)
            
            # Chercher les liens vers les feuilles de match
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if "vbspo_feuille2.php" in href and "ression=" in href:
                    match = re.search(r"ression=([^&]+)", href)
                    if match:
                        match_code = match.group(1)
                        pdf_url = self._build_pdf_url(competition.ligue_code, match_code)
                        
                        yield MatchInfo(
                            code=match_code,
                            competition_code=competition.code,
                            ligue_code=competition.ligue_code,
                            saison=competition.saison,
                            pdf_url=pdf_url
                        )
    
    def _build_pdf_url(self, ligue_code: str, match_code: str) -> str:
        """Construit l'URL du PDF d'un match."""
        return urljoin(
            self.base_url,
            f"fdme/{ligue_code}/{ligue_code}_{match_code}.pdf"
        )
    
    def download_match_pdf(self, match: MatchInfo, output_dir: Path) -> ScrapeResult:
        """
        Télécharge le PDF d'un match.
        
        Args:
            match: Informations sur le match
            output_dir: Dossier de destination
            
        Returns:
            ScrapeResult avec le statut
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = output_dir / match.filename
        
        try:
            if not match.pdf_url:
                match.pdf_url = self._build_pdf_url(match.ligue_code, match.code)
            
            response = self._get(match.pdf_url)
            
            # Vérifier que c'est bien un PDF
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower() and not response.content.startswith(b"%PDF"):
                return ScrapeResult(
                    success=False,
                    message=f"Not a PDF: {match.filename}",
                    error=ScrapingError("Invalid content type")
                )
            
            # Sauvegarder le fichier
            with open(filepath, "wb") as f:
                f.write(response.content)
            
            return ScrapeResult(
                success=True,
                message=f"Downloaded: {match.filename}",
                data={"path": str(filepath), "size": len(response.content)}
            )
            
        except Exception as e:
            return ScrapeResult(
                success=False,
                message=f"Failed: {match.filename}",
                error=e
            )
    
    def search_by_code(self, match_code: str, ligue_code: str) -> Optional[MatchInfo]:
        """
        Recherche un match par son code.
        
        Args:
            match_code: Code du match (ex: PMAA001)
            ligue_code: Code de la ligue (ex: LIIDF)
            
        Returns:
            MatchInfo si trouvé, None sinon
        """
        pdf_url = self._build_pdf_url(ligue_code, match_code)
        
        # Vérifier si le PDF existe
        try:
            response = self._session.head(pdf_url, timeout=self._timeout)
            if response.status_code == 200:
                return MatchInfo(
                    code=match_code,
                    competition_code=match_code[:3],  # Extrait "PMA" de "PMAA001"
                    ligue_code=ligue_code,
                    saison="unknown",
                    pdf_url=pdf_url
                )
        except requests.RequestException:
            pass
        
        return None
