"""
Client HTTP avec gestion du rate limiting, retry et session.

Extrait du scraper FFVB pour être réutilisable par tous les scrapers.
"""

import logging
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pyvolley.core.config import settings
from pyvolley.core.exceptions import NetworkError, PageNotFoundError

logger = logging.getLogger(__name__)


class HttpClient:
    """
    Client HTTP avec rate limiting et retry automatique.

    Gère :
    - Délai configurable entre requêtes (rate limiting)
    - Retry automatique sur 403, 429, 5xx
    - Headers réalistes pour éviter les blocages
    - Parsing HTML via BeautifulSoup
    """

    MAX_RETRIES = 5
    RETRY_BACKOFF_FACTOR = 2.0  # secondes : 2, 4, 8, 16, 32...

    def __init__(
        self,
        request_delay: Optional[float] = None,
        timeout: Optional[int] = None,
    ):
        self._delay = request_delay or settings.ffvb_request_delay
        self._timeout = timeout or settings.ffvb_timeout
        self._session = requests.Session()
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
        retry_strategy = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=self.RETRY_BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._last_request_time = 0.0

    @property
    def session(self) -> requests.Session:
        """Accès direct à la session requests sous-jacente."""
        return self._session

    @property
    def timeout(self) -> int:
        return self._timeout

    @property
    def delay(self) -> float:
        return self._delay

    @delay.setter
    def delay(self, value: float):
        self._delay = value

    def rate_limit(self):
        """Applique le délai entre les requêtes."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_request_time = time.time()

    def get(self, url: str) -> requests.Response:
        """Effectue une requête GET avec gestion des erreurs et retry sur 403."""
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            self.rate_limit()
            try:
                response = self._session.get(url, timeout=self._timeout)
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status == 404:
                    raise PageNotFoundError(f"Page non trouvée: {url}")
                if status == 403 and attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BACKOFF_FACTOR * (2 ** (attempt - 1))
                    logger.warning(
                        "HTTP 403 sur %s – tentative %d/%d, retry dans %.0fs",
                        url, attempt, self.MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    self._delay = max(self._delay, 1.0 + attempt * 0.5)
                    last_exc = e
                    continue
                raise NetworkError(f"Erreur HTTP {status}: {url}")
            except requests.exceptions.RequestException as e:
                if attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BACKOFF_FACTOR * (2 ** (attempt - 1))
                    logger.warning(
                        "Erreur réseau sur %s – tentative %d/%d, retry dans %.0fs",
                        url, attempt, self.MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    last_exc = e
                    continue
                raise NetworkError(f"Erreur réseau: {e}")

        raise NetworkError(f"Échec après {self.MAX_RETRIES} tentatives: {url} ({last_exc})")

    def get_soup(self, url: str) -> BeautifulSoup:
        """Récupère et parse une page HTML."""
        response = self.get(url)
        return BeautifulSoup(response.content, "html.parser")

    def safe_get_soup(self, url: str) -> Optional[BeautifulSoup]:
        """Récupère et parse une page HTML, retourne None en cas d'erreur."""
        try:
            return self.get_soup(url)
        except Exception as e:
            logger.warning("Impossible de récupérer %s : %s", url, e)
            return None
