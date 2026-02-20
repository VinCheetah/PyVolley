"""
Client HTTP asynchrone avec gestion du rate limiting, retry et concurrence.

Utilise httpx pour le support HTTP/2 et les requêtes concurrentes,
permettant un scraping bien plus rapide que l'ancien client séquentiel.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from pyvolley.core.config import settings
from pyvolley.core.exceptions import NetworkError, PageNotFoundError

logger = logging.getLogger(__name__)


class AsyncHttpClient:
    """
    Client HTTP asynchrone avec HTTP/2, rate limiting et concurrence.

    Avantages sur HttpClient :
    - Requêtes concurrentes (configurable via max_concurrent)
    - Support HTTP/2 natif (contourne certains WAFs)
    - Sémaphore pour limiter la charge serveur
    - Retry automatique avec backoff exponentiel
    """

    MAX_RETRIES = 5
    RETRY_BACKOFF_FACTOR = 2.0

    def __init__(
        self,
        request_delay: Optional[float] = None,
        timeout: Optional[int] = None,
        max_concurrent: int = 5,
    ):
        self._delay = request_delay if request_delay is not None else settings.ffvb_request_delay
        self._timeout = timeout or settings.ffvb_timeout
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()

        self._headers = {
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
        }

        transport = httpx.AsyncHTTPTransport(
            retries=0,  # On gère les retries nous-mêmes
            http2=True,
        )
        self._client = httpx.AsyncClient(
            headers=self._headers,
            transport=transport,
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=max_concurrent * 2,
                max_keepalive_connections=max_concurrent,
            ),
        )

    @property
    def timeout(self) -> int:
        return self._timeout

    @property
    def delay(self) -> float:
        return self._delay

    @delay.setter
    def delay(self, value: float):
        self._delay = value

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    async def _rate_limit(self):
        """Applique le délai entre les requêtes (thread-safe)."""
        async with self._lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._delay:
                await asyncio.sleep(self._delay - elapsed)
            self._last_request_time = time.time()

    async def get(self, url: str) -> httpx.Response:
        """Effectue une requête GET avec sémaphore, rate limiting et retry."""
        last_exc: Optional[Exception] = None

        async with self._semaphore:
            for attempt in range(1, self.MAX_RETRIES + 1):
                await self._rate_limit()
                try:
                    response = await self._client.get(url)
                    response.raise_for_status()
                    return response
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    if status == 404:
                        raise PageNotFoundError(f"Page non trouvée: {url}")
                    if status == 403 and attempt < self.MAX_RETRIES:
                        wait = self.RETRY_BACKOFF_FACTOR * (2 ** (attempt - 1))
                        logger.warning(
                            "HTTP 403 sur %s – tentative %d/%d, retry dans %.0fs",
                            url, attempt, self.MAX_RETRIES, wait,
                        )
                        await asyncio.sleep(wait)
                        last_exc = e
                        continue
                    if status in (429, 500, 502, 503, 504) and attempt < self.MAX_RETRIES:
                        wait = self.RETRY_BACKOFF_FACTOR * (2 ** (attempt - 1))
                        logger.warning(
                            "HTTP %d sur %s – tentative %d/%d, retry dans %.0fs",
                            status, url, attempt, self.MAX_RETRIES, wait,
                        )
                        await asyncio.sleep(wait)
                        last_exc = e
                        continue
                    raise NetworkError(f"Erreur HTTP {status}: {url}")
                except httpx.RequestError as e:
                    if attempt < self.MAX_RETRIES:
                        wait = self.RETRY_BACKOFF_FACTOR * (2 ** (attempt - 1))
                        logger.warning(
                            "Erreur réseau sur %s – tentative %d/%d, retry dans %.0fs",
                            url, attempt, self.MAX_RETRIES, wait,
                        )
                        await asyncio.sleep(wait)
                        last_exc = e
                        continue
                    raise NetworkError(f"Erreur réseau: {e}")

        raise NetworkError(f"Échec après {self.MAX_RETRIES} tentatives: {url} ({last_exc})")

    async def head(self, url: str) -> httpx.Response:
        """Effectue une requête HEAD avec sémaphore et rate limiting."""
        async with self._semaphore:
            await self._rate_limit()
            try:
                return await self._client.head(url)
            except httpx.RequestError as e:
                raise NetworkError(f"Erreur réseau HEAD: {e}")

    async def get_soup(self, url: str) -> BeautifulSoup:
        """Récupère et parse une page HTML."""
        response = await self.get(url)
        return BeautifulSoup(response.content, "html.parser")

    async def safe_get_soup(self, url: str) -> Optional[BeautifulSoup]:
        """Récupère et parse une page HTML, retourne None en cas d'erreur."""
        try:
            return await self.get_soup(url)
        except Exception as e:
            logger.warning("Impossible de récupérer %s : %s", url, e)
            return None

    async def get_many(self, urls: list[str]) -> list[Optional[httpx.Response]]:
        """
        Récupère plusieurs URLs en parallèle.

        Returns:
            Liste de réponses (ou None pour les URLs en erreur).
        """
        async def _fetch_one(url: str) -> Optional[httpx.Response]:
            try:
                return await self.get(url)
            except Exception as e:
                logger.warning("Erreur pour %s : %s", url, e)
                return None

        return await asyncio.gather(*[_fetch_one(u) for u in urls])

    async def get_many_soups(self, urls: list[str]) -> list[Optional[BeautifulSoup]]:
        """
        Récupère et parse plusieurs pages HTML en parallèle.
        """
        responses = await self.get_many(urls)
        return [
            BeautifulSoup(r.content, "html.parser") if r is not None else None
            for r in responses
        ]

    async def download_file(
        self,
        url: str,
        filepath: str,
        *,
        min_valid_size: int = 0,
    ) -> bool:
        """
        Télécharge un fichier et l'écrit sur disque.

        Args:
            min_valid_size: Taille minimum pour considérer le fichier valide.

        Returns:
            True si téléchargé avec succès, False sinon.
        """
        try:
            response = await self.get(url)
            content = response.content

            if min_valid_size > 0 and len(content) < min_valid_size:
                logger.debug("Fichier trop petit (%d octets): %s", len(content), url)
                return False

            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower() and not content.startswith(b"%PDF"):
                logger.warning("Contenu non-PDF pour %s: %s", url, content_type)
                return False

            import aiofiles
            async with aiofiles.open(filepath, "wb") as f:
                await f.write(content)

            return True
        except Exception as e:
            logger.warning("Échec téléchargement %s: %s", url, e)
            return False

    async def close(self):
        """Ferme le client HTTP."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
