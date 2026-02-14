"""
Scraper pour le site FFVB (ffvbbeach.org).

Ce module permet de récupérer les feuilles de match de volley-ball
depuis le site officiel de la Fédération Française de Volley-Ball.

Structure du site FFVB:
- planning_volley.php : Liste des entités (ligues, comités, compétitions nationales)
- vbspo_calendrier.php : Calendrier des matchs d'une compétition
- ffvolley_fdme.php : Téléchargement du PDF d'une feuille de match
"""

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urljoin, urlencode

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pyvolley.core.config import settings
from pyvolley.core.exceptions import NetworkError, PageNotFoundError, ScrapingError
from pyvolley.scrapers.base import (
    BaseScraper,
    CompetitionInfo,
    MatchInfo,
    ScrapeResult,
)

logger = logging.getLogger(__name__)


@dataclass
class EntityInfo:
    """Informations sur une entité (ligue, comité, compétition nationale)."""
    code: str  # Code de l'entité (ex: LIIDF, ABCCS, PTPL44)
    nom: str   # Nom complet
    type: str  # Type: 'nationale', 'ligue', 'comite'


@dataclass 
class PouleInfo:
    """Informations sur une poule/division."""
    code: str          # Code de la poule (ex: EFA, EFB)
    nom: str           # Nom complet
    entity_code: str   # Code de l'entité parente
    saison: str        # Saison (ex: 2025/2026)
    is_division: bool = False  # True si c'est une division plutôt qu'une poule


class FFVBScraper(BaseScraper):
    """
    Scraper pour le site des résultats FFVB.
    
    URL de base: https://www.ffvbbeach.org/ffvbapp/resu/
    
    Méthodes principales:
    - get_entities(): Récupère toutes les entités (ligues, comités, compétitions)
    - get_poules_for_entity(): Récupère les poules d'une entité
    - get_matches_for_poule(): Récupère les matchs d'une poule
    - download_match_pdf(): Télécharge le PDF d'un match
    """
    
    # Nombre max de tentatives pour les erreurs récupérables (403, 429, 5xx)
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 2.0  # secondes : 2, 4, 8...

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
        # Headers réalistes pour éviter les blocages 403
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
        # Retry automatique via urllib3 pour les erreurs de connexion
        retry_strategy = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=self.RETRY_BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
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
        """Effectue une requête GET avec gestion des erreurs et retry sur 403."""
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            self._rate_limit()
            try:
                response = self._session.get(url, timeout=self._timeout)
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status == 404:
                    raise PageNotFoundError(f"Page non trouvée: {url}")
                # 403 : le serveur bloque temporairement → retry avec backoff
                if status == 403 and attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BACKOFF_FACTOR * (2 ** (attempt - 1))
                    logger.warning(
                        f"HTTP 403 sur {url} – tentative {attempt}/{self.MAX_RETRIES}, "
                        f"retry dans {wait:.0f}s"
                    )
                    time.sleep(wait)
                    last_exc = e
                    continue
                raise NetworkError(f"Erreur HTTP {status}: {url}")
            except requests.exceptions.RequestException as e:
                if attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BACKOFF_FACTOR * (2 ** (attempt - 1))
                    logger.warning(
                        f"Erreur réseau sur {url} – tentative {attempt}/{self.MAX_RETRIES}, "
                        f"retry dans {wait:.0f}s"
                    )
                    time.sleep(wait)
                    last_exc = e
                    continue
                raise NetworkError(f"Erreur réseau: {e}")

        # Ne devrait pas arriver, mais par sécurité
        raise NetworkError(f"Échec après {self.MAX_RETRIES} tentatives: {url} ({last_exc})")
    
    def _get_soup(self, url: str) -> BeautifulSoup:
        """Récupère et parse une page HTML."""
        response = self._get(url)
        return BeautifulSoup(response.content, "html.parser")
    
    # =========================================================================
    # Méthodes pour récupérer les entités
    # =========================================================================
    
    def get_entities(self) -> list[EntityInfo]:
        """
        Récupère la liste de toutes les entités depuis planning_volley.php.
        
        Returns:
            Liste d'EntityInfo (ligues, comités, compétitions nationales)
        """
        url = urljoin(self.base_url, "planning_volley.php")
        soup = self._get_soup(url)
        
        entities = []
        select = soup.find("select", {"name": "sel_entites"})
        
        if not select:
            raise ScrapingError("Select 'sel_entites' non trouvé sur la page")
        
        for option in select.find_all("option"):
            code = option.get("value", "").strip()
            nom = option.text.strip()
            
            # Ignorer les options vides ou de séparation
            if not code or code == "0" or code.startswith("-"):
                continue
            
            # Détecter le type d'entité
            entity_type = self._detect_entity_type(code, nom)
            
            entities.append(EntityInfo(
                code=code,
                nom=nom,
                type=entity_type
            ))
        
        return entities
    
    def _detect_entity_type(self, code: str, nom: str) -> str:
        """Détecte le type d'entité depuis le code et le nom."""
        nom_lower = nom.lower()
        
        # Compétitions nationales
        if code.startswith("A") or "nationale" in nom_lower:
            return "nationale"
        # Ligues régionales
        if code.startswith("LI") or "ligue" in nom_lower:
            return "ligue"
        # Comités départementaux
        if code.startswith("PT") or "comité" in nom_lower or code.startswith("CD"):
            return "comite"
        
        return "autre"
    
    def get_ligues(self) -> list[dict]:
        """
        Récupère la liste des ligues (pour compatibilité avec l'interface).
        
        Returns:
            Liste de dictionnaires {code, nom, type}
        """
        entities = self.get_entities()
        return [
            {"code": e.code, "nom": e.nom, "type": e.type}
            for e in entities
        ]
    
    # =========================================================================
    # Méthodes pour récupérer les poules/compétitions
    # =========================================================================
    
    # Mapping des entités vers les URLs ffvb.org pour récupérer les poules
    ENTITY_FFVB_URLS = {
        "ABCCS": "http://www.ffvb.org/front/119-159-1-Championnats-Nationaux",
        "ACJEUNES": "http://www.ffvb.org/front/124-167-1-Coupes-de-France-Jeunes",
    }
    
    def get_poules_for_entity(
        self, 
        entity_code: str,
        saison: Optional[str] = None
    ) -> list[PouleInfo]:
        """
        Récupère les poules/divisions disponibles pour une entité.
        
        Args:
            entity_code: Code de l'entité (ex: LIIDF, ABCCS)
            saison: Saison au format YYYY/YYYY (ex: 2025/2026)
            
        Returns:
            Liste de PouleInfo
        """
        if saison is None:
            saison = self._get_current_saison()
        
        poules = []
        
        # Méthode 1: Pour les compétitions nationales, récupérer depuis ffvb.org
        if entity_code in self.ENTITY_FFVB_URLS:
            poules = self._get_poules_from_ffvb_org(entity_code, saison)
        
        # Méthode 2: Récupérer depuis la page home (sommaire) - marche pour ligues/comités
        if not poules:
            poules = self._get_poules_from_home(entity_code, saison)
        
        # Méthode 3: Si pas de poules trouvées, essayer via la page calendrier
        if not poules:
            poules = self._get_poules_from_calendar(entity_code, saison)
        
        # Méthode 4: Si toujours pas de poules, essayer d'extraire depuis les index_xxx.htm
        if not poules:
            poules = self._get_poules_by_pattern(entity_code, saison)
        
        return poules
    
    def _get_poules_from_ffvb_org(
        self, 
        entity_code: str, 
        saison: str
    ) -> list[PouleInfo]:
        """Récupère les poules depuis ffvb.org."""
        url = self.ENTITY_FFVB_URLS.get(entity_code)
        if not url:
            return []
        
        try:
            soup = self._get_soup(url)
        except Exception:
            return []
        
        poules = []
        saison_folder = saison.replace("/", "-")
        
        # Chercher les liens vers les pages index_xxx.htm
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.text.strip()
            
            # Pattern: /resu/.../index_xxx.htm
            if "ffvbbeach.org/ffvbapp/resu" in href and "index_" in href:
                match = re.search(r"index_([^.]+)\.htm", href)
                if match:
                    poule_code = match.group(1).upper()  # Convertir en majuscules
                    if not any(p.code == poule_code for p in poules):
                        poules.append(PouleInfo(
                            code=poule_code,
                            nom=text or poule_code,
                            entity_code=entity_code,
                            saison=saison
                        ))
        
        return poules
    
    def _get_poules_from_home(
        self, 
        entity_code: str, 
        saison: str
    ) -> list[PouleInfo]:
        """
        Récupère les poules depuis la page home (sommaire) de l'entité.
        
        Fonctionne particulièrement bien pour les ligues et comités.
        """
        params = {
            "saison": saison,
            "codent": entity_code,
        }
        url = urljoin(self.base_url, f"vbspo_home.php?{urlencode(params)}")
        
        try:
            soup = self._get_soup(url)
        except Exception:
            return []
        
        poules = []
        
        # Chercher les liens vers les calendriers avec paramètre poule=
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.text.strip()
            
            # Pattern: vbspo_calendrier.php?...&poule=XXX
            if "vbspo_calendrier.php" in href and "poule=" in href:
                match = re.search(r"poule=([^&]+)", href)
                if match:
                    poule_code = match.group(1).upper()
                    if poule_code and not any(p.code == poule_code for p in poules):
                        # Nettoyer le nom (enlever le code au début s'il y est)
                        nom = text
                        if nom.upper().startswith(poule_code):
                            nom = nom[len(poule_code):].strip()
                        nom = f"{poule_code} {nom}" if nom else poule_code
                        
                        poules.append(PouleInfo(
                            code=poule_code,
                            nom=nom,
                            entity_code=entity_code,
                            saison=saison
                        ))
            
            # Aussi chercher les divisions (division=XXX)
            elif "vbspo_calendrier.php" in href and "division=" in href:
                match = re.search(r"division=([^&]+)", href)
                if match:
                    div_code = match.group(1).upper()
                    if div_code and not any(p.code == div_code for p in poules):
                        poules.append(PouleInfo(
                            code=div_code,
                            nom=text or div_code,
                            entity_code=entity_code,
                            saison=saison,
                            is_division=True
                        ))
        
        return poules
    
    def _get_poules_from_calendar(
        self, 
        entity_code: str, 
        saison: str
    ) -> list[PouleInfo]:
        """Récupère les poules depuis la page calendrier."""
        params = {
            "saison": saison,
            "codent": entity_code,
        }
        url = urljoin(self.base_url, f"vbspo_calendrier.php?{urlencode(params)}")
        
        try:
            soup = self._get_soup(url)
        except Exception:
            return []
        
        poules = []
        
        # Chercher les liens vers les poules dans les formulaires ou liens
        for form in soup.find_all("form"):
            action = form.get("action", "")
            if "vbspo_calendrier.php" in action:
                poule_input = form.find("input", {"name": "poule"})
                if poule_input and poule_input.get("value"):
                    poule_code = poule_input["value"].upper()
                    if poule_code and not any(p.code == poule_code for p in poules):
                        poules.append(PouleInfo(
                            code=poule_code,
                            nom=poule_code,
                            entity_code=entity_code,
                            saison=saison
                        ))
        
        # Chercher aussi dans les liens directs
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "poule=" in href:
                match = re.search(r"poule=([^&]+)", href)
                if match:
                    poule_code = match.group(1).upper()
                    if poule_code and not any(p.code == poule_code for p in poules):
                        poules.append(PouleInfo(
                            code=poule_code,
                            nom=link.text.strip() or poule_code,
                            entity_code=entity_code,
                            saison=saison
                        ))
        
        return poules
    
    def _get_poules_by_pattern(
        self, 
        entity_code: str, 
        saison: str
    ) -> list[PouleInfo]:
        """
        Génère des poules potentielles basées sur des patterns connus.
        
        Utilisé en dernier recours quand les autres méthodes échouent.
        """
        # Patterns courants pour les compétitions nationales seniors
        if entity_code == "ABCCS":
            patterns = [
                # Elite
                ("EFA", "Elite Féminine Poule Haute"),
                ("EFB", "Elite Féminine Poule Basse"),
                ("EMA", "Elite Masculine Poule A"),
                # EAM
                ("EAA", "EAM Poule A"),
                ("EAB", "EAM Poule B"),
                # N2
                ("2FA", "N2 Féminine Poule A"),
                ("2FB", "N2 Féminine Poule B"),
                ("2FC", "N2 Féminine Poule C"),
                ("2FD", "N2 Féminine Poule D"),
                ("2MA", "N2 Masculine Poule A"),
                ("2MB", "N2 Masculine Poule B"),
                ("2MC", "N2 Masculine Poule C"),
                ("2MD", "N2 Masculine Poule D"),
                # N3
                ("3FA", "N3 Féminine Poule A"),
                ("3FB", "N3 Féminine Poule B"),
                ("3FC", "N3 Féminine Poule C"),
                ("3FD", "N3 Féminine Poule D"),
                ("3FE", "N3 Féminine Poule E"),
                ("3FF", "N3 Féminine Poule F"),
                ("3FG", "N3 Féminine Poule G"),
                ("3FH", "N3 Féminine Poule H"),
                ("3MA", "N3 Masculine Poule A"),
                ("3MB", "N3 Masculine Poule B"),
                ("3MC", "N3 Masculine Poule C"),
                ("3MD", "N3 Masculine Poule D"),
                ("3ME", "N3 Masculine Poule E"),
                ("3MF", "N3 Masculine Poule F"),
                ("3MG", "N3 Masculine Poule G"),
                ("3MH", "N3 Masculine Poule H"),
            ]
            return [
                PouleInfo(code=code, nom=nom, entity_code=entity_code, saison=saison)
                for code, nom in patterns
            ]
        
        return []
    
    def get_competitions(
        self, 
        ligue_code: str, 
        saison: Optional[str] = None
    ) -> list[CompetitionInfo]:
        """
        Récupère les compétitions d'une ligue (compatibilité interface).
        
        Args:
            ligue_code: Code de la ligue/entité
            saison: Saison au format YYYY/YYYY
        """
        if saison is None:
            saison = self._get_current_saison()
            
        poules = self.get_poules_for_entity(ligue_code, saison)
        
        competitions = []
        for poule in poules:
            genre = self._detect_genre(poule.nom)
            categorie = self._detect_categorie(poule.nom)
            
            competitions.append(CompetitionInfo(
                code=poule.code,
                nom=poule.nom,
                ligue_code=ligue_code,
                saison=saison,
                genre=genre,
                categorie=categorie
            ))
        
        return competitions
    
    def _detect_genre(self, nom: str) -> Optional[str]:
        """Détecte le genre depuis le nom de compétition."""
        nom_upper = nom.upper()
        if any(x in nom_upper for x in ["MASCULIN", " M ", "MASC"]):
            return "MASCULIN"
        elif any(x in nom_upper for x in ["FEMININ", "FÉMININ", " F ", "FEM"]):
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
    
    def _get_current_saison(self) -> str:
        """Retourne la saison courante au format YYYY/YYYY."""
        from datetime import datetime
        now = datetime.now()
        # La saison commence en septembre
        if now.month >= 9:
            return f"{now.year}/{now.year + 1}"
        else:
            return f"{now.year - 1}/{now.year}"
    
    # =========================================================================
    # Méthodes pour récupérer les matchs
    # =========================================================================
    
    def get_matches_for_poule(
        self,
        entity_code: str,
        poule_code: str,
        saison: Optional[str] = None
    ) -> Iterator[MatchInfo]:
        """
        Récupère tous les matchs d'une poule.
        
        Args:
            entity_code: Code de l'entité (ex: ABCCS)
            poule_code: Code de la poule (ex: EFA)
            saison: Saison au format YYYY/YYYY
            
        Yields:
            MatchInfo pour chaque match trouvé
        """
        if saison is None:
            saison = self._get_current_saison()
        
        # Récupérer le calendrier complet
        params = {
            "saison": saison,
            "codent": entity_code,
            "poule": poule_code,
            "calend": "COMPLET"
        }
        url = urljoin(self.base_url, f"vbspo_calendrier.php?{urlencode(params)}")
        soup = self._get_soup(url)
        
        # Chercher les formulaires avec action vers ffvolley_fdme.php
        seen_codes = set()
        for form in soup.find_all("form"):
            action = form.get("action", "")
            if "ffvolley_fdme.php" in action:
                # Extraire le code du match depuis l'action
                match = re.search(r"codmatch=([^&]+)", action)
                if match:
                    match_code = match.group(1)
                    
                    # Éviter les doublons
                    if match_code in seen_codes:
                        continue
                    seen_codes.add(match_code)
                    
                    # Construire l'URL du PDF
                    pdf_url = self._build_pdf_url(entity_code, match_code, saison)
                    
                    yield MatchInfo(
                        code=match_code,
                        competition_code=poule_code,
                        ligue_code=entity_code,
                        saison=saison,
                        pdf_url=pdf_url
                    )
    
    def get_matches(self, competition: CompetitionInfo) -> Iterator[MatchInfo]:
        """
        Récupère les matchs d'une compétition (compatibilité interface).
        
        Args:
            competition: Information sur la compétition
            
        Yields:
            MatchInfo pour chaque match trouvé
        """
        yield from self.get_matches_for_poule(
            entity_code=competition.ligue_code,
            poule_code=competition.code,
            saison=competition.saison
        )
    
    def get_poules(self, competition_code: str, ligue_code: str) -> list[dict]:
        """
        Récupère les poules d'une compétition (compatibilité ancienne interface).
        """
        poules = self.get_poules_for_entity(ligue_code)
        return [{"code": p.code, "nom": p.nom} for p in poules]
    
    # =========================================================================
    # Méthodes pour le téléchargement des PDFs
    # =========================================================================
    
    def _build_pdf_url(
        self, 
        entity_code: str, 
        match_code: str, 
        saison: Optional[str] = None
    ) -> str:
        """Construit l'URL du PDF d'un match."""
        if saison is None:
            saison = self._get_current_saison()
        
        params = {
            "saison": saison,
            "codent": entity_code,
            "codmatch": match_code
        }
        return urljoin(self.base_url, f"ffvolley_fdme.php?{urlencode(params)}")
    
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
                match.pdf_url = self._build_pdf_url(
                    match.ligue_code, 
                    match.code, 
                    match.saison
                )
            
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
    
    def search_by_code(
        self, 
        match_code: str, 
        entity_code: str, 
        saison: Optional[str] = None
    ) -> Optional[MatchInfo]:
        """
        Recherche un match par son code.
        
        Args:
            match_code: Code du match (ex: EFA001)
            entity_code: Code de l'entité (ex: ABCCS)
            saison: Saison au format YYYY/YYYY
            
        Returns:
            MatchInfo si trouvé, None sinon
        """
        if saison is None:
            saison = self._get_current_saison()
            
        pdf_url = self._build_pdf_url(entity_code, match_code, saison)
        
        # Vérifier si le PDF existe
        try:
            self._rate_limit()
            response = self._session.head(pdf_url, timeout=self._timeout)
            if response.status_code == 200:
                # Extraire le code de la poule depuis le code match
                poule_match = re.match(r"([A-Z]+)", match_code)
                competition_code = poule_match.group(1) if poule_match else match_code[:3]
                
                return MatchInfo(
                    code=match_code,
                    competition_code=competition_code,
                    ligue_code=entity_code,
                    saison=saison,
                    pdf_url=pdf_url
                )
        except requests.RequestException:
            pass
        
        return None
    
    # =========================================================================
    # Méthodes pour le scraping massif
    # =========================================================================
    
    def get_all_matches_for_entity(
        self,
        entity_code: str,
        saison: Optional[str] = None
    ) -> Iterator[MatchInfo]:
        """
        Récupère TOUS les matchs de toutes les poules d'une entité.
        
        Args:
            entity_code: Code de l'entité
            saison: Saison au format YYYY/YYYY
            
        Yields:
            MatchInfo pour chaque match trouvé
        """
        if saison is None:
            saison = self._get_current_saison()
        
        # D'abord récupérer toutes les poules
        poules = self.get_poules_for_entity(entity_code, saison)
        
        for poule in poules:
            yield from self.get_matches_for_poule(entity_code, poule.code, saison)
    
    def download_all_matches_for_entity(
        self,
        entity_code: str,
        base_output_dir: Path,
        saison: Optional[str] = None,
        skip_existing: bool = True,
        organize_by_poule: bool = True
    ) -> list[ScrapeResult]:
        """
        Télécharge toutes les feuilles de match d'une entité.
        
        Args:
            entity_code: Code de l'entité
            base_output_dir: Dossier de destination de base
            saison: Saison au format YYYY/YYYY
            skip_existing: Ignorer les fichiers existants
            organize_by_poule: Organiser par poule (True) ou tout dans le même dossier
            
        Returns:
            Liste des résultats de téléchargement
        """
        if saison is None:
            saison = self._get_current_saison()
        
        base_output_dir = Path(base_output_dir)
        results = []
        
        # Récupérer toutes les poules
        poules = self.get_poules_for_entity(entity_code, saison)
        
        for poule in poules:
            # Déterminer le dossier de destination
            if organize_by_poule:
                # Structure: base_dir/saison/entity/poule/
                saison_folder = saison.replace("/", "-")
                output_dir = base_output_dir / saison_folder / entity_code / poule.code
            else:
                output_dir = base_output_dir
            
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Récupérer et télécharger les matchs
            for match in self.get_matches_for_poule(entity_code, poule.code, saison):
                filepath = output_dir / match.filename
                
                if skip_existing and filepath.exists():
                    results.append(ScrapeResult(
                        success=True,
                        message=f"Skipped (exists): {match.filename}"
                    ))
                    continue
                
                result = self.download_match_pdf(match, output_dir)
                results.append(result)
        
        return results
    
    def collect_all_pdf_urls(
        self,
        entity_codes: Optional[list[str]] = None,
        saison: Optional[str] = None,
        entity_types: Optional[list[str]] = None
    ) -> list[dict]:
        """
        Collecte toutes les URLs de PDFs sans télécharger.
        
        Utile pour préparer un téléchargement massif ou analyser le volume de données.
        
        Args:
            entity_codes: Liste des codes d'entités (None = toutes)
            saison: Saison au format YYYY/YYYY
            entity_types: Filtrer par type ('nationale', 'ligue', 'comite')
            
        Returns:
            Liste de dictionnaires avec les infos des matchs
        """
        if saison is None:
            saison = self._get_current_saison()
        
        # Récupérer les entités si non spécifiées
        if entity_codes is None:
            entities = self.get_entities()
            if entity_types:
                entities = [e for e in entities if e.type in entity_types]
            entity_codes = [e.code for e in entities]
        
        all_matches = []
        
        for entity_code in entity_codes:
            try:
                for match in self.get_all_matches_for_entity(entity_code, saison):
                    all_matches.append({
                        "entity_code": match.ligue_code,
                        "poule_code": match.competition_code,
                        "match_code": match.code,
                        "saison": match.saison,
                        "pdf_url": match.pdf_url,
                        "filename": match.filename
                    })
            except Exception as e:
                # Log l'erreur mais continue avec les autres entités
                print(f"Erreur pour l'entité {entity_code}: {e}")
        
        return all_matches
