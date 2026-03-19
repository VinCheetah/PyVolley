"""Récupération de logos clubs depuis Volleybox.

Stratégie de collecte :
- scraping HTML direct Volleybox,
- recherche ciblée ``country=FR&name=...`` depuis des mots-clés du club,
- fallback index global (pages clubs FR) si besoin de couverture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional
import re
import unicodedata
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from requests import RequestException
from bs4 import BeautifulSoup


_VOLLEYBOX_FR_CLUBS = (
    "https://volleybox.net/fr/clubs?country=FR&type=C&orderValue=id&orderDirection=desc"
)
_VOLLEYBOX_FR_CLUBS_SEARCH = (
    "https://volleybox.net/fr/clubs?country=FR&type=C&orderValue=id&orderDirection=desc&name="
)
_JINA_PREFIX = "https://r.jina.ai/http://"
_TEAM_URL_RE = re.compile(r"https://volleybox\.net/fr/([a-z0-9\-]+)-t(\d+)")
_TEAM_PATH_RE = re.compile(r"/fr/([a-z0-9\-]+)-t(\d+)")
_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")
_IMAGE_URL_RE = re.compile(r"https?://[^\s)\]]+\.(?:png|jpg|jpeg|webp|svg)", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+")
_PAGE_RE = re.compile(r"(?:\?|&)page=(\d+)")
_CITY_RE = re.compile(r"([A-Za-zÀ-ÖØ-öø-ÿ'\-\s\d]+),\s*France", re.IGNORECASE)
_GOOGLE_RESULT_RE = re.compile(r"^/url\?q=([^&]+)")

_GENERIC_TOKENS = {
    "club",
    "clubs",
    "volley",
    "volleyball",
    "volleyball",
    "ball",
    "team",
    "equipe",
    "equipes",
    "de",
    "du",
    "des",
    "la",
    "le",
    "les",
    "et",
    "d",
    "l",
}


@dataclass
class LogoCandidate:
    team_url: str
    slug: str
    score: float
    matched_name: Optional[str] = None
    matched_city: Optional[str] = None
    city_score: float = 0.0
    logo_url: Optional[str] = None
    source: str = "volleybox"
    search_query: Optional[str] = None
    result_url: Optional[str] = None


@dataclass
class _TeamEntry:
    team_url: str
    slug: str
    tokens: set[str]
    city: Optional[str] = None
    city_tokens: set[str] = field(default_factory=set)


class VolleyboxLogoScraper:
    def __init__(self, timeout: float = 25.0, max_fr_pages: int = 40):
        self.timeout = timeout
        self.max_fr_pages = max(1, max_fr_pages)
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

    @staticmethod
    def _looks_like_html(content: str) -> bool:
        lowered = (content or "").lower()
        return "<html" in lowered or "<!doctype html" in lowered or "<a " in lowered

    def _fetch_text_direct(self, url: str) -> str:
        response = self._session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _jina_url(url: str) -> str:
        return f"{_JINA_PREFIX}{url.replace('https://', '').replace('http://', '')}"

    def _fetch_text(self, url: str, *, allow_jina_fallback: bool = True) -> str:
        try:
            return self._fetch_text_direct(url)
        except RequestException:
            if not allow_jina_fallback:
                raise
            fallback_url = self._jina_url(url)
            return self._fetch_text_direct(fallback_url)

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFD", value or "")
        stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return re.sub(r"\s+", " ", stripped).strip().lower()

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        return {
            token
            for token in _WORD_RE.findall(cls._normalize(value))
            if token and token not in _GENERIC_TOKENS
        }

    @classmethod
    def _tokens_with_numbers(cls, value: str) -> set[str]:
        return set(_WORD_RE.findall(cls._normalize(value)))

    @staticmethod
    def _compact(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value)

    @staticmethod
    def _acronym_from_text(value: str) -> str:
        return "".join(token[0] for token in _WORD_RE.findall(value) if token)

    @classmethod
    def _acronym_from_slug(cls, slug: str) -> str:
        tokens = [token for token in slug.split("-") if token and token not in _GENERIC_TOKENS]
        return "".join(token[0] for token in tokens)

    @staticmethod
    def _extract_max_page(content: str) -> int:
        if "<" in content and ">" in content:
            soup = BeautifulSoup(content, "html.parser")
            pages: list[int] = []
            for link in soup.select("a[href]"):
                href = link.get("href") or ""
                for value in _PAGE_RE.findall(href):
                    pages.append(int(value))
                text = (link.get_text(" ", strip=True) or "").strip()
                if text.isdigit():
                    pages.append(int(text))
            if pages:
                return max(pages)

        match = re.search(r"…\s*(\d+)\s*»", content)
        if match:
            return max(1, int(match.group(1)))
        pages = [int(value) for value in _PAGE_RE.findall(content)]
        return max(pages, default=1)

    @staticmethod
    def _team_url_from_href(href: str) -> Optional[tuple[str, str]]:
        href = (href or "").strip()
        if not href:
            return None

        absolute_match = _TEAM_URL_RE.search(href)
        if absolute_match:
            slug = absolute_match.group(1)
            team_url = f"https://volleybox.net/fr/{slug}-t{absolute_match.group(2)}"
            return team_url, slug

        path_match = _TEAM_PATH_RE.search(href)
        if path_match:
            slug = path_match.group(1)
            team_url = f"https://volleybox.net/fr/{slug}-t{path_match.group(2)}"
            return team_url, slug

        return None

    @classmethod
    def _extract_city_from_text(cls, text: str) -> Optional[str]:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if not cleaned:
            return None

        match = _CITY_RE.search(cleaned)
        if not match:
            return None

        city_raw = re.sub(r"\s+", " ", match.group(1)).strip(" -")
        if not city_raw:
            return None

        words = city_raw.split()
        if len(words) > 4:
            city_raw = " ".join(words[-3:])

        return city_raw or None

    def _extract_team_entries(self, content: str) -> list[_TeamEntry]:
        entries: list[_TeamEntry] = []
        seen_urls: set[str] = set()

        if "<" in content and ">" in content:
            soup = BeautifulSoup(content, "html.parser")
            for link in soup.select("a[href]"):
                parsed = self._team_url_from_href(link.get("href") or "")
                if not parsed:
                    continue
                team_url, slug = parsed
                context_text = link.parent.get_text(" ", strip=True) if link.parent else ""
                city = self._extract_city_from_text(context_text) or self._extract_city_from_text(
                    link.get_text(" ", strip=True)
                )
                if team_url in seen_urls:
                    continue
                seen_urls.add(team_url)
                entries.append(
                    _TeamEntry(
                        team_url=team_url,
                        slug=slug,
                        tokens=self._tokens(slug.replace("-", " ")),
                        city=city,
                        city_tokens=self._tokens_with_numbers(city or ""),
                    )
                )

        for match in _TEAM_URL_RE.finditer(content):
            slug = match.group(1)
            team_url = f"https://volleybox.net/fr/{slug}-t{match.group(2)}"
            if team_url in seen_urls:
                continue
            seen_urls.add(team_url)
            entries.append(
                _TeamEntry(
                    team_url=team_url,
                    slug=slug,
                    tokens=self._tokens(slug.replace("-", " ")),
                    city=None,
                    city_tokens=set(),
                )
            )

        return entries

    def _search_entries_by_keywords(self, keywords: list[str], per_keyword_pages: int = 3) -> list[_TeamEntry]:
        collected: list[_TeamEntry] = []
        seen: set[str] = set()

        for keyword in keywords:
            query = keyword.strip()
            if not query:
                continue

            base_url = f"{_VOLLEYBOX_FR_CLUBS_SEARCH}{quote_plus(query)}"
            first_page = self._fetch_text(base_url)
            max_page = min(max(1, per_keyword_pages), self._extract_max_page(first_page))

            for page_number in range(1, max_page + 1):
                if page_number == 1:
                    content = first_page
                else:
                    content = self._fetch_text(f"{base_url}&page={page_number}")

                for entry in self._extract_team_entries(content):
                    if entry.team_url in seen:
                        continue
                    seen.add(entry.team_url)
                    collected.append(entry)

        return collected

    @staticmethod
    def _merge_entries(*groups: list[_TeamEntry]) -> list[_TeamEntry]:
        merged: list[_TeamEntry] = []
        seen_urls: set[str] = set()
        for group in groups:
            for entry in group:
                if entry.team_url in seen_urls:
                    continue
                seen_urls.add(entry.team_url)
                merged.append(entry)
        return merged

    def _load_teams_index(self) -> list[_TeamEntry]:
        if self._teams_index is not None:
            return self._teams_index

        entries: list[_TeamEntry] = []
        seen_urls: set[str] = set()

        try:
            first_page = self._fetch_text(_VOLLEYBOX_FR_CLUBS)
            max_page = min(self.max_fr_pages, self._extract_max_page(first_page))
            for page_number in range(1, max_page + 1):
                if page_number == 1:
                    content = first_page
                else:
                    content = self._fetch_text(f"{_VOLLEYBOX_FR_CLUBS}&page={page_number}")

                for entry in self._extract_team_entries(content):
                    if entry.team_url in seen_urls:
                        continue
                    seen_urls.add(entry.team_url)
                    entries.append(entry)
        except (RequestException, ValueError):
            entries = []

        if not entries:
            raise RuntimeError("Impossible de construire l'index des clubs Volleybox")

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

    def _build_query_variants(self, club_names: list[str]) -> list[tuple[str, set[str], float]]:
        variants: list[tuple[str, set[str], float]] = []
        seen: set[str] = set()

        for index, raw_name in enumerate(club_names):
            normalized_name = self._normalize(raw_name)
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)

            tokens = self._tokens(normalized_name)
            if not tokens:
                continue

            compact = self._compact(normalized_name)
            token_count = len(tokens)
            base_weight = 1.0 if index == 0 else 0.9
            if len(compact) <= 6 or token_count == 1:
                base_weight *= 0.92

            variants.append((normalized_name, tokens, base_weight))

        return variants

    def _extract_name_keywords(self, club_names: list[str], max_keywords: int = 8) -> list[str]:
        raw_names = [name.strip() for name in club_names if name and name.strip()]
        if not raw_names:
            return []

        keywords: list[str] = []
        seen: set[str] = set()

        normalized_primary = self._normalize(raw_names[0])
        if normalized_primary and normalized_primary not in seen:
            seen.add(normalized_primary)
            keywords.append(raw_names[0])

        name_tokens: list[str] = []
        for name in raw_names:
            for token in self._tokens(name):
                if len(token) < 3:
                    continue
                if token in seen:
                    continue
                seen.add(token)
                name_tokens.append(token)

        name_tokens.sort(key=len, reverse=True)
        for token in name_tokens:
            keywords.append(token)
            if len(keywords) >= max_keywords:
                break

        return keywords[:max_keywords]

    def _score_city_proximity(self, target_city: Optional[str], entry: _TeamEntry) -> tuple[float, Optional[str]]:
        if not target_city:
            return 0.0, entry.city

        target_norm = self._normalize(target_city)
        if not target_norm:
            return 0.0, entry.city

        target_tokens = self._tokens_with_numbers(target_norm)

        candidate_city = entry.city or entry.slug.replace("-", " ")
        candidate_norm = self._normalize(candidate_city)
        if not candidate_norm:
            return 0.0, entry.city

        candidate_tokens = entry.city_tokens or self._tokens_with_numbers(candidate_norm)
        token_score = self._score_tokens(
            {token for token in target_tokens if token not in _GENERIC_TOKENS},
            {token for token in candidate_tokens if token not in _GENERIC_TOKENS},
        )
        sequence_score = SequenceMatcher(None, target_norm, candidate_norm).ratio()

        contains_bonus = 0.0
        if target_norm in candidate_norm or candidate_norm in target_norm:
            contains_bonus = 0.2

        return min(1.0, (0.6 * token_score) + (0.4 * sequence_score) + contains_bonus), entry.city

    def _score_name_variant(
        self,
        query_name: str,
        query_tokens: set[str],
        candidate_slug: str,
        candidate_tokens: set[str],
    ) -> float:
        candidate_name = candidate_slug.replace("-", " ")
        token_score = self._score_tokens(query_tokens, candidate_tokens)
        sequence_score = SequenceMatcher(None, query_name, candidate_name).ratio()

        contains_bonus = 0.0
        if query_name in candidate_name or candidate_name in query_name:
            contains_bonus = 0.12

        acronym_bonus = 0.0
        query_compact = self._compact(query_name)
        acronym = self._acronym_from_slug(candidate_slug)
        query_acronym = self._acronym_from_text(query_name)
        if query_compact and acronym and len(query_compact) <= 6 and query_compact == acronym:
            acronym_bonus = 0.18
        elif query_acronym and acronym and len(query_acronym) <= 6 and query_acronym == acronym:
            acronym_bonus = 0.12

        score = (0.55 * token_score) + (0.35 * sequence_score) + contains_bonus + acronym_bonus
        return min(1.0, score)

    def find_team_candidates(
        self,
        club_names: list[str],
        *,
        target_city: Optional[str] = None,
        limit: int = 3,
        min_score: float = 0.2,
    ) -> list[LogoCandidate]:
        variants = self._build_query_variants(club_names)
        if not variants:
            return []

        entries: list[_TeamEntry] = []
        try:
            keywords = self._extract_name_keywords(club_names)
            entries = self._search_entries_by_keywords(keywords, per_keyword_pages=3)
        except (RequestException, ValueError):
            entries = []

        if len(entries) < 25:
            try:
                entries = self._merge_entries(entries, self._load_teams_index())
            except RuntimeError:
                pass

        candidates: list[LogoCandidate] = []
        for entry in entries:
            best_weighted_score = 0.0
            best_matched_name: Optional[str] = None
            support_hits = 0

            for query_name, query_tokens, weight in variants:
                raw_score = self._score_name_variant(query_name, query_tokens, entry.slug, entry.tokens)
                if raw_score >= 0.55:
                    support_hits += 1
                weighted_score = raw_score * weight
                if weighted_score > best_weighted_score:
                    best_weighted_score = weighted_score
                    best_matched_name = query_name

            bonus = min(0.12, 0.04 * max(support_hits - 1, 0))
            city_score, matched_city = self._score_city_proximity(target_city, entry)
            final_score = min(1.0, best_weighted_score + bonus + (0.18 * city_score))
            if final_score < min_score:
                continue

            candidates.append(
                LogoCandidate(
                    team_url=entry.team_url,
                    slug=entry.slug,
                    score=final_score,
                    matched_name=best_matched_name,
                    matched_city=matched_city,
                    city_score=city_score,
                )
            )

        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return candidates[: max(1, limit)]

    def find_best_team(self, club_names: list[str], *, target_city: Optional[str] = None) -> Optional[LogoCandidate]:
        candidates = self.find_team_candidates(club_names, target_city=target_city, limit=1)
        return candidates[0] if candidates else None

    @staticmethod
    def _is_valid_logo_url(url: str) -> bool:
        lowered = url.lower()
        if "default_team" in lowered or "default-team" in lowered:
            return False
        return (
            "/media/upload/teams/" in lowered
            or "/media/upload/" in lowered and "team" in lowered
        ) and lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg"))

    @staticmethod
    def _is_image_url(url: str) -> bool:
        lowered = (url or "").lower()
        return lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".avif"))

    @classmethod
    def _is_likely_logo_url(cls, url: str) -> bool:
        lowered = (url or "").lower()
        if cls._is_valid_logo_url(url):
            return True
        if "logo" in lowered or "crest" in lowered or "emblem" in lowered:
            return cls._is_image_url(lowered) or "/images/" in lowered or "/assets/" in lowered
        return False

    @staticmethod
    def _is_blocked_search_result(url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        return host.endswith("google.com") or host.endswith("google.fr")

    def _extract_google_first_result(self, html: str) -> Optional[str]:
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("a[href]"):
            href = (link.get("href") or "").strip()
            if not href:
                continue

            resolved: Optional[str] = None
            match = _GOOGLE_RESULT_RE.match(href)
            if match:
                resolved = unquote(match.group(1))
            elif href.startswith("http://") or href.startswith("https://"):
                resolved = href

            if not resolved:
                continue
            if self._is_blocked_search_result(resolved):
                continue
            return resolved

        return None

    def _google_first_result_url(self, query: str) -> Optional[str]:
        search_url = f"https://www.google.com/search?hl=fr&gl=fr&num=8&q={quote_plus(query)}"
        html = self._fetch_text(search_url, allow_jina_fallback=False)
        return self._extract_google_first_result(html)

    def _duckduckgo_first_result_url(self, query: str) -> Optional[str]:
        search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        html = self._fetch_text(search_url, allow_jina_fallback=False)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("a.result__a[href], a[href]"):
            href = (link.get("href") or "").strip()
            if not href:
                continue
            if href.startswith("http://") or href.startswith("https://"):
                if not self._is_blocked_search_result(href):
                    return href
        return None

    def _bing_first_result_url(self, query: str) -> Optional[str]:
        search_url = f"https://www.bing.com/search?q={quote_plus(query)}&setlang=fr"
        html = self._fetch_text(search_url, allow_jina_fallback=False)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("li.b_algo h2 a[href], h2 a[href], a[href]"):
            href = (link.get("href") or "").strip()
            if not href:
                continue
            if href.startswith("http://") or href.startswith("https://"):
                if not self._is_blocked_search_result(href):
                    return href
        return None

    def _extract_logo_url_from_generic_page(self, page_url: str) -> Optional[str]:
        response = self._session.get(page_url, timeout=self.timeout)
        response.raise_for_status()

        content_type = (response.headers.get("content-type") or "").lower()
        if content_type.startswith("image/") and self._is_image_url(page_url):
            return page_url

        content = response.text
        if not self._looks_like_html(content):
            for image_url in _IMAGE_URL_RE.findall(content):
                if self._is_likely_logo_url(image_url):
                    return image_url
            return None

        soup = BeautifulSoup(content, "html.parser")

        for selector in (
            'meta[property="og:image"]',
            'meta[name="twitter:image"]',
            'meta[property="og:image:url"]',
        ):
            meta = soup.select_one(selector)
            candidate = (meta.get("content") if meta else "") or ""
            candidate = candidate.strip()
            if not candidate:
                continue
            absolute = urljoin(page_url, candidate)
            if self._is_likely_logo_url(absolute):
                return absolute

        scored_images: list[tuple[int, str]] = []
        for image in soup.select("img[src]"):
            src = (image.get("src") or "").strip()
            if not src:
                continue
            absolute = urljoin(page_url, src)
            attrs = " ".join(
                [
                    image.get("alt") or "",
                    image.get("class") and " ".join(image.get("class")) or "",
                    image.get("id") or "",
                    image.get("title") or "",
                ]
            ).lower()

            score = 0
            lowered_url = absolute.lower()
            if "logo" in attrs or "logo" in lowered_url:
                score += 5
            if "crest" in attrs or "emblem" in attrs:
                score += 3
            if self._is_image_url(absolute):
                score += 2
            if "sprite" in lowered_url or "icon" in lowered_url:
                score -= 1

            if score > 0:
                scored_images.append((score, absolute))

        if scored_images:
            scored_images.sort(key=lambda item: item[0], reverse=True)
            return scored_images[0][1]

        return None

    def _build_google_queries(
        self,
        club_names: list[str],
        *,
        target_city: Optional[str] = None,
        max_queries: int = 4,
    ) -> list[str]:
        clean_names = [name.strip() for name in club_names if name and name.strip()]
        if not clean_names:
            return []

        queries: list[str] = []
        seen: set[str] = set()
        city = (target_city or "").strip()

        for index, name in enumerate(clean_names):
            base_forms = [
                f"{name} volley logo",
                f"{name} volleyball logo",
                f"{name} logo club volley",
            ]
            if index == 0:
                base_forms.append(f"{name} volleybox")
                base_forms.append(f"{name} site:volleybox.net")

            for query in base_forms:
                norm = self._normalize(query)
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                queries.append(query)
                if city:
                    city_query = f"{query} {city}"
                    city_norm = self._normalize(city_query)
                    if city_norm and city_norm not in seen:
                        seen.add(city_norm)
                        queries.append(city_query)

                if len(queries) >= max_queries:
                    return queries[:max_queries]

        return queries[:max_queries]

    def find_logo_via_google_first_result(
        self,
        club_names: list[str],
        *,
        target_city: Optional[str] = None,
    ) -> Optional[LogoCandidate]:
        queries = self._build_google_queries(club_names, target_city=target_city)
        if not queries:
            return None

        for query in queries:
            source = "google-first-result"
            try:
                first_result = self._google_first_result_url(query)
            except RequestException:
                first_result = None

            if not first_result:
                source = "duckduckgo-first-result"
                try:
                    first_result = self._duckduckgo_first_result_url(query)
                except RequestException:
                    first_result = None

            if not first_result:
                source = "bing-first-result"
                try:
                    first_result = self._bing_first_result_url(query)
                except RequestException:
                    first_result = None

            if not first_result:
                continue

            try:
                logo_url = self._extract_logo_url_from_generic_page(first_result)
            except RequestException:
                logo_url = first_result if self._is_likely_logo_url(first_result) else None

            if not logo_url and self._is_likely_logo_url(first_result):
                logo_url = first_result

            if not logo_url:
                continue

            slug_source = self._normalize(club_names[0] if club_names else "club").replace(" ", "-")
            return LogoCandidate(
                team_url=first_result,
                slug=slug_source,
                score=0.95,
                matched_name=club_names[0] if club_names else None,
                matched_city=target_city,
                city_score=1.0 if target_city else 0.0,
                logo_url=logo_url,
                source=source,
                search_query=query,
                result_url=first_result,
            )

        return None

    def extract_logo_url(self, team_url: str) -> Optional[str]:
        try:
            content = self._fetch_text(team_url)
        except RequestException:
            return None

        if self._looks_like_html(content):
            soup = BeautifulSoup(content, "html.parser")
            for image in soup.select("img[src]"):
                src = image.get("src") or ""
                if src.startswith("/"):
                    src = f"https://volleybox.net{src}"
                if self._is_valid_logo_url(src):
                    return src

        for image_url in _IMAGE_MD_RE.findall(content):
            if self._is_valid_logo_url(image_url):
                return image_url

        for image_url in _IMAGE_URL_RE.findall(content):
            if self._is_valid_logo_url(image_url):
                return image_url

        return None

    def find_logo_for_club(
        self,
        club_names: list[str],
        *,
        target_city: Optional[str] = None,
        prefer_google: bool = True,
    ) -> Optional[LogoCandidate]:
        if prefer_google:
            google_candidate = self.find_logo_via_google_first_result(
                club_names,
                target_city=target_city,
            )
            if google_candidate and google_candidate.logo_url:
                return google_candidate

        best = self.find_best_team(club_names, target_city=target_city)
        if not best:
            return None

        try:
            best.logo_url = self.extract_logo_url(best.team_url)
        except RequestException:
            return None
        if not best.logo_url:
            return None

        best.source = "volleybox"
        best.result_url = best.team_url

        return best
