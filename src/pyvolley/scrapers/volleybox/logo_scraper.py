"""Récupération de logos clubs depuis Volleybox.

Le site Volleybox peut bloquer les requêtes directes (403). Ce scraper utilise
un fallback via ``r.jina.ai/http://...`` pour récupérer le contenu texte indexé,
puis :
- construit un index des clubs Volleybox depuis les sitemaps,
- sélectionne le meilleur candidat via score de similarité,
- extrait l'URL de logo de la page candidat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import re
import unicodedata

import requests


_JINA_PREFIX = "https://r.jina.ai/http://"
_VOLLEYBOX_FR_SITEMAP = "https://volleybox.net/fr/sitemap.xml"
_TEAM_URL_RE = re.compile(r"https://volleybox\.net/fr/([a-z0-9\-]+)-t(\d+)")
_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")
_IMAGE_URL_RE = re.compile(r"https?://[^\s)\]]+\.(?:png|jpg|jpeg|webp|svg)", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class LogoCandidate:
    team_url: str
    slug: str
    score: float
    logo_url: Optional[str] = None


@dataclass
class _TeamEntry:
    team_url: str
    slug: str
    tokens: set[str]


class VolleyboxLogoScraper:
    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            }
        )
        self._teams_index: Optional[list[_TeamEntry]] = None

    def _fetch_text(self, url: str) -> str:
        proxy_url = f"{_JINA_PREFIX}{url.replace('https://', '').replace('http://', '')}"
        response = self._session.get(proxy_url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFD", value or "")
        stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return re.sub(r"\s+", " ", stripped).strip().lower()

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        return set(_WORD_RE.findall(cls._normalize(value)))

    def _load_teams_index(self) -> list[_TeamEntry]:
        if self._teams_index is not None:
            return self._teams_index

        sitemap_root = self._fetch_text(_VOLLEYBOX_FR_SITEMAP)
        team_sitemaps = sorted(set(re.findall(r"https://volleybox\.net/fr/sitemap-teams-\d+\.xml", sitemap_root)))

        entries: list[_TeamEntry] = []
        for sitemap_url in team_sitemaps:
            content = self._fetch_text(sitemap_url)
            for match in _TEAM_URL_RE.finditer(content):
                slug = match.group(1)
                team_url = f"https://volleybox.net/fr/{slug}-t{match.group(2)}"
                entries.append(_TeamEntry(team_url=team_url, slug=slug, tokens=self._tokens(slug.replace("-", " "))))

        self._teams_index = entries
        return entries

    @classmethod
    def _score_tokens(cls, query_tokens: set[str], candidate_tokens: set[str]) -> float:
        if not query_tokens or not candidate_tokens:
            return 0.0

        intersection = len(query_tokens & candidate_tokens)
        if intersection == 0:
            return 0.0

        union = len(query_tokens | candidate_tokens)
        jaccard = intersection / union
        coverage = intersection / max(len(query_tokens), 1)
        return (0.65 * coverage) + (0.35 * jaccard)

    def find_best_team(self, club_names: list[str]) -> Optional[LogoCandidate]:
        names = [name for name in club_names if name and name.strip()]
        if not names:
            return None

        query_tokens: set[str] = set()
        for name in names:
            query_tokens |= self._tokens(name)

        if not query_tokens:
            return None

        best: Optional[LogoCandidate] = None
        for entry in self._load_teams_index():
            score = self._score_tokens(query_tokens, entry.tokens)
            if score < 0.2:
                continue
            candidate = LogoCandidate(team_url=entry.team_url, slug=entry.slug, score=score)
            if best is None or candidate.score > best.score:
                best = candidate

        return best

    @staticmethod
    def _is_valid_logo_url(url: str) -> bool:
        lowered = url.lower()
        return (
            "/media/upload/teams/" in lowered
            or "/media/upload/" in lowered and "team" in lowered
        ) and lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg"))

    def extract_logo_url(self, team_url: str) -> Optional[str]:
        content = self._fetch_text(team_url)

        for image_url in _IMAGE_MD_RE.findall(content):
            if self._is_valid_logo_url(image_url):
                return image_url

        for image_url in _IMAGE_URL_RE.findall(content):
            if self._is_valid_logo_url(image_url):
                return image_url

        return None

    def find_logo_for_club(self, club_names: list[str]) -> Optional[LogoCandidate]:
        best = self.find_best_team(club_names)
        if not best:
            return None

        best.logo_url = self.extract_logo_url(best.team_url)
        if not best.logo_url:
            return None

        return best
