"""Tests du scraper de logos Volleybox."""

from pyvolley.scrapers.volleybox.logo_scraper import VolleyboxLogoScraper


def test_find_best_team_from_sitemap_tokens(monkeypatch):
    scraper = VolleyboxLogoScraper()

    sitemap_root = "https://volleybox.net/fr/sitemap-teams-1.xml"
    sitemap_teams = """
https://volleybox.net/fr/harnes-volley-ball-t99999
https://volleybox.net/fr/grenoble-vuc-t12345
"""

    def fake_fetch(url: str) -> str:
        if url.endswith("/fr/sitemap.xml"):
            return sitemap_root
        if url.endswith("sitemap-teams-1.xml"):
            return sitemap_teams
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
