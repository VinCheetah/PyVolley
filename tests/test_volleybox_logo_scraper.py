"""Tests du scraper de logos Volleybox."""

import requests

from pyvolley.scrapers.volleybox.logo_scraper import LogoCandidate, VolleyboxLogoScraper, _TeamEntry


def test_find_best_team_from_sitemap_tokens(monkeypatch):
    scraper = VolleyboxLogoScraper()

    search_page = """
https://volleybox.net/fr/harnes-volley-ball-t99999
"""

    def fake_fetch(url: str) -> str:
        if "country=FR" in url and "name=" in url:
            return search_page
        if "fr/clubs?country=FR" in url:
            return search_page
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(scraper, "_fetch_text", fake_fetch)

    best = scraper.find_best_team(["HARNES VOLLEY-BALL", "HARNES VB"])

    assert best is not None
    assert best.team_url.endswith("/harnes-volley-ball-t99999")
    assert best.score > 0.5


def test_extract_logo_url_from_team_page(monkeypatch):
    scraper = VolleyboxLogoScraper()

    team_page = """
![Team image](https://volleybox.net/media/upload/teams/1234_harnes_logo.png)
"""

    monkeypatch.setattr(scraper, "_fetch_text", lambda url: team_page)

    logo = scraper.extract_logo_url("https://volleybox.net/fr/harnes-volley-ball-t99999")

    assert logo == "https://volleybox.net/media/upload/teams/1234_harnes_logo.png"


def test_load_teams_index_from_fr_clubs_pages(monkeypatch):
    scraper = VolleyboxLogoScraper(max_fr_pages=3)

    page_1 = """
    Clubs FR 123…2»
    https://volleybox.net/fr/club-a-t100
    https://volleybox.net/fr/club-b-t200
    """
    page_2 = """
    https://volleybox.net/fr/club-c-t300
    """
    def fake_fetch(url: str) -> str:
        if "fr/clubs?country=FR" in url and "&page=2" not in url:
            return page_1
        if "fr/clubs?country=FR" in url and "&page=2" in url:
            return page_2
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(scraper, "_fetch_text", fake_fetch)

    entries = scraper._load_teams_index()

    urls = [entry.team_url for entry in entries]
    assert "https://volleybox.net/fr/club-a-t100" in urls
    assert "https://volleybox.net/fr/club-b-t200" in urls
    assert "https://volleybox.net/fr/club-c-t300" in urls


def test_find_team_candidates_uses_short_name_acronym(monkeypatch):
    scraper = VolleyboxLogoScraper()
    teams = [
        _TeamEntry(
            team_url="https://volleybox.net/fr/association-sportive-villeurbanne-t111",
            slug="association-sportive-villeurbanne-t111".replace("-t111", ""),
            tokens=scraper._tokens("association sportive villeurbanne"),
        ),
        _TeamEntry(
            team_url="https://volleybox.net/fr/association-sportive-valence-t222",
            slug="association-sportive-valence-t222".replace("-t222", ""),
            tokens=scraper._tokens("association sportive valence"),
        ),
    ]

    monkeypatch.setattr(scraper, "_load_teams_index", lambda: teams)

    candidates = scraper.find_team_candidates(
        ["Association Sportive Villeurbanne", "ASV"],
        limit=2,
        min_score=0.0,
    )

    assert candidates
    assert candidates[0].team_url.endswith("association-sportive-villeurbanne-t111")


def test_extract_team_entries_from_html_relative_links():
    scraper = VolleyboxLogoScraper()
    html = """
    <html><body>
      <a href="/fr/harnes-volley-ball-t99999">Harnes</a>
      <a href="/fr/grenoble-vuc-t12345">Grenoble</a>
    </body></html>
    """

    entries = scraper._extract_team_entries(html)

    urls = [entry.team_url for entry in entries]
    assert "https://volleybox.net/fr/harnes-volley-ball-t99999" in urls
    assert "https://volleybox.net/fr/grenoble-vuc-t12345" in urls


def test_search_entries_uses_country_and_name_query(monkeypatch):
    scraper = VolleyboxLogoScraper()
    called_urls: list[str] = []

    html = """
    <html><body>
      <a href="/fr/as-caluire-vb-t39613">AS Caluire VB</a>
    </body></html>
    """

    def fake_fetch(url: str) -> str:
        called_urls.append(url)
        return html

    monkeypatch.setattr(scraper, "_fetch_text", fake_fetch)

    entries = scraper._search_entries_by_keywords(["Caluire"], per_keyword_pages=1)

    assert entries
    assert any("country=FR" in url and "name=Caluire" in url for url in called_urls)


def test_find_team_candidates_city_proximity_boost(monkeypatch):
    scraper = VolleyboxLogoScraper()

    teams = [
        _TeamEntry(
            team_url="https://volleybox.net/fr/union-sportive-villeurbanne-t10",
            slug="union-sportive-villeurbanne",
            tokens=scraper._tokens("union sportive villeurbanne"),
            city="Villeurbanne",
            city_tokens=scraper._tokens_with_numbers("Villeurbanne"),
        ),
        _TeamEntry(
            team_url="https://volleybox.net/fr/union-sportive-valence-t11",
            slug="union-sportive-valence",
            tokens=scraper._tokens("union sportive valence"),
            city="Valence",
            city_tokens=scraper._tokens_with_numbers("Valence"),
        ),
    ]

    monkeypatch.setattr(scraper, "_search_entries_by_keywords", lambda *args, **kwargs: teams)
    monkeypatch.setattr(scraper, "_load_teams_index", lambda: [])

    candidates = scraper.find_team_candidates(
        ["Union Sportive"],
        target_city="Villeurbanne",
        limit=2,
        min_score=0.0,
    )

    assert candidates
    assert candidates[0].team_url.endswith("union-sportive-villeurbanne-t10")
    assert candidates[0].city_score >= candidates[1].city_score


def test_find_team_candidates_does_not_raise_when_index_unavailable(monkeypatch):
    scraper = VolleyboxLogoScraper()

    teams = [
        _TeamEntry(
            team_url="https://volleybox.net/fr/as-caluire-vb-t39613",
            slug="as-caluire-vb",
            tokens=scraper._tokens("as caluire vb"),
            city="Caluire",
            city_tokens=scraper._tokens_with_numbers("Caluire"),
        )
    ]

    monkeypatch.setattr(scraper, "_search_entries_by_keywords", lambda *args, **kwargs: teams)

    def fail_index() -> list[_TeamEntry]:
        raise RuntimeError("Impossible de construire l'index des clubs Volleybox")

    monkeypatch.setattr(scraper, "_load_teams_index", fail_index)

    candidates = scraper.find_team_candidates(["AS Caluire VB"], target_city="Caluire", limit=1)

    assert candidates
    assert candidates[0].team_url.endswith("/as-caluire-vb-t39613")


def test_extract_google_first_result_from_search_html():
    scraper = VolleyboxLogoScraper()
    html = """
    <html><body>
      <a href="/url?q=https%3A%2F%2Fwww.example.org%2Fclub-logo&sa=U&ved=2ah">résultat</a>
    </body></html>
    """

    first = scraper._extract_google_first_result(html)

    assert first == "https://www.example.org/club-logo"


def test_find_logo_for_club_prefers_google_first_result(monkeypatch):
    scraper = VolleyboxLogoScraper()

    monkeypatch.setattr(
        scraper,
        "find_logo_via_google_first_result",
        lambda *args, **kwargs: LogoCandidate(
            team_url="https://example.org/club",
            slug="club",
            score=0.95,
            matched_name="AS Caluire VB",
            matched_city="Caluire",
            city_score=1.0,
            logo_url="https://example.org/logo.png",
            source="google-first-result",
            search_query="AS Caluire VB volley logo",
            result_url="https://example.org/club",
        ),
    )

    called = {"best": False}

    def fake_find_best_team(*args, **kwargs):
        called["best"] = True
        return None

    monkeypatch.setattr(scraper, "find_best_team", fake_find_best_team)

    result = scraper.find_logo_for_club(["AS Caluire VB"], target_city="Caluire")

    assert result is not None
    assert result.source == "google-first-result"
    assert result.logo_url == "https://example.org/logo.png"
    assert called["best"] is False


def test_find_logo_uses_duckduckgo_when_google_blocked(monkeypatch):
    scraper = VolleyboxLogoScraper()

    def fail_google(*args, **kwargs):
        raise requests.RequestException("429")

    monkeypatch.setattr(scraper, "_google_first_result_url", fail_google)
    monkeypatch.setattr(
        scraper,
        "_duckduckgo_first_result_url",
        lambda *args, **kwargs: "https://example.org/club-page",
    )
    monkeypatch.setattr(
        scraper,
        "_extract_logo_url_from_generic_page",
        lambda *args, **kwargs: "https://example.org/logo.svg",
    )

    result = scraper.find_logo_via_google_first_result(["AS Caluire VB"], target_city="Caluire")

    assert result is not None
    assert result.source == "duckduckgo-first-result"
    assert result.logo_url == "https://example.org/logo.svg"


def test_find_logo_uses_bing_when_google_and_duckduckgo_fail(monkeypatch):
    scraper = VolleyboxLogoScraper()

    def fail_search(*args, **kwargs):
        raise requests.RequestException("blocked")

    monkeypatch.setattr(scraper, "_google_first_result_url", fail_search)
    monkeypatch.setattr(scraper, "_duckduckgo_first_result_url", fail_search)
    monkeypatch.setattr(
        scraper,
        "_bing_first_result_url",
        lambda *args, **kwargs: "https://example.org/club-page",
    )
    monkeypatch.setattr(
        scraper,
        "_extract_logo_url_from_generic_page",
        lambda *args, **kwargs: "https://example.org/logo.png",
    )

    result = scraper.find_logo_via_google_first_result(["A.C. CHAPELAIN VOLLEY"])

    assert result is not None
    assert result.source == "bing-first-result"
    assert result.logo_url == "https://example.org/logo.png"
