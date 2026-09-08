"""Provider de logos depuis Wikipedia et Wikimedia Commons.

Ce provider interroge l'API MediaWiki officielle pour récupérer les logos officiels
vectoriels (SVG) ou haute résolution (PNG) des clubs de volley-ball français.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests
from requests import RequestException

logger = logging.getLogger(__name__)

_WIKIPEDIA_API_URL = "https://fr.wikipedia.org/w/api.php"
_DEFAULT_USER_AGENT = (
    "PyVolleyBot/1.0 (https://github.com/VinCheetah/PyVolley; contact@pyvolley.org) "
    "requests/2.31.0"
)

# Termes indésirables dans les noms de fichiers d'images Wikipedia
_EXCLUDE_FILE_PATTERNS = (
    "flag",
    "drapeau",
    "kit",
    "maillot",
    "short",
    "sock",
    "simple",
    "travaux",
    "commons",
    "pictogram",
    "icon",
    "fauteuil",
    "stade",
    "salle",
    "carte",
    "map",
)


@dataclass
class WikipediaLogoResult:
    """Résultat d'une recherche de logo sur Wikipedia."""

    logo_url: str
    page_title: str
    file_name: str
    score: float = 0.90
    source: str = "wikipedia"


class WikipediaLogoProvider:
    """Récupère les logos de clubs depuis l'API Wikipédia en français."""

    def __init__(
        self,
        timeout: float = 8.0,
        user_agent: str = _DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = max(2.0, timeout)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )

    def _search_pages(self, query: str, limit: int = 3) -> list[str]:
        """Recherche les titres de pages correspondant à la requête."""
        params = {
            "action": "opensearch",
            "search": query,
            "limit": limit,
            "namespace": 0,
            "format": "json",
        }
        try:
            response = self._session.get(
                _WIKIPEDIA_API_URL, params=params, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                return [str(title) for title in data[1]]
        except (RequestException, ValueError) as exc:
            logger.debug("Erreur lors de la recherche Wikipedia pour '%s': %s", query, exc)
        return []

    def _get_page_images(self, title: str) -> list[str]:
        """Extrait la liste des fichiers d'images d'une page Wikipedia."""
        params = {
            "action": "parse",
            "page": title,
            "prop": "images",
            "format": "json",
        }
        try:
            response = self._session.get(
                _WIKIPEDIA_API_URL, params=params, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            images = data.get("parse", {}).get("images", [])
            return [str(img) for img in images]
        except (RequestException, ValueError) as exc:
            logger.debug("Erreur lors de l'extraction des images de '%s': %s", title, exc)
        return []

    def _get_image_direct_url(self, file_name: str) -> Optional[str]:
        """Récupère l'URL directe d'un fichier hébergé sur Wikimedia."""
        clean_file = file_name.strip()
        title = clean_file if clean_file.startswith("Fichier:") else f"Fichier:{clean_file}"
        params = {
            "action": "query",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
        }
        try:
            response = self._session.get(
                _WIKIPEDIA_API_URL, params=params, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            pages = data.get("query", {}).get("pages", {})
            for _, page_info in pages.items():
                imageinfo = page_info.get("imageinfo", [])
                if imageinfo and isinstance(imageinfo, list):
                    url = imageinfo[0].get("url")
                    if url:
                        return str(url)
        except (RequestException, ValueError) as exc:
            logger.debug("Erreur lors de la résolution de l'URL pour '%s': %s", file_name, exc)
        return None

    @staticmethod
    def _is_probable_logo_file(file_name: str) -> bool:
        """Détermine si un nom de fichier ressemble à un logo de club."""
        lowered = file_name.lower()
        if not (lowered.endswith(".svg") or lowered.endswith((".png", ".jpg", ".jpeg", ".webp"))):
            return False

        if any(term in lowered for term in _EXCLUDE_FILE_PATTERNS):
            return False

        return (
            "logo" in lowered
            or "blason" in lowered
            or "crest" in lowered
            or "ecusson" in lowered
            or "emblem" in lowered
        )

    def find_logo(
        self,
        club_name: str,
        city: Optional[str] = None,
    ) -> Optional[WikipediaLogoResult]:
        """Recherche le logo d'un club sur Wikipédia.

        Args:
            club_name: Nom du club (ex: 'Tours Volley-Ball').
            city: Ville optionnelle pour affiner la recherche.

        Returns:
            WikipediaLogoResult si un logo est identifié, sinon None.
        """
        clean_name = re.sub(r"\s+", " ", club_name or "").strip()
        if not clean_name:
            return None

        # Variantes de requêtes ordonnées par pertinence
        queries = [clean_name]
        if "volley" not in clean_name.lower():
            queries.append(f"{clean_name} volley-ball")
        if city and city.lower() not in clean_name.lower():
            queries.append(f"{clean_name} {city}")

        visited_titles: set[str] = set()

        for query in queries:
            page_titles = self._search_pages(query, limit=3)
            for title in page_titles:
                if title in visited_titles:
                    continue
                visited_titles.add(title)

                # Vérifier la pertinence minimale
                title_lower = title.lower()
                clean_lower = clean_name.lower()
                if "volley" not in title_lower and (not city or city.lower() not in title_lower):
                    # Accepter si le nom du club est présent dans le titre
                    if not any(token in title_lower for token in clean_lower.split() if len(token) >= 4):
                        continue

                images = self._get_page_images(title)
                logo_candidates = [img for img in images if self._is_probable_logo_file(img)]
                if not logo_candidates:
                    continue

                # Privilégier les fichiers contenant explicitement 'logo', puis les SVG
                def _logo_priority(fname: str) -> tuple[int, int, str]:
                    low = fname.lower()
                    has_logo = 0 if "logo" in low else 1
                    is_svg = 0 if low.endswith(".svg") else 1
                    return (has_logo, is_svg, low)

                logo_candidates.sort(key=_logo_priority)

                for candidate in logo_candidates:
                    direct_url = self._get_image_direct_url(candidate)
                    if direct_url:
                        return WikipediaLogoResult(
                            logo_url=direct_url,
                            page_title=title,
                            file_name=candidate,
                            score=0.92 if candidate.lower().endswith(".svg") else 0.88,
                        )

        return None
