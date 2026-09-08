"""Tests unitaires pour le ClubLogoService et ses providers."""

import pytest
from unittest.mock import MagicMock

from pyvolley.scrapers.logos.logo_service import ClubLogoResult, ClubLogoService
from pyvolley.scrapers.logos.svg_badge_generator import SvgBadgeGenerator
from pyvolley.scrapers.logos.wikipedia_provider import WikipediaLogoProvider, WikipediaLogoResult
from pyvolley.scrapers.volleybox.logo_scraper import LogoCandidate, VolleyboxLogoScraper


class TestSvgBadgeGenerator:
    def test_extract_monogram(self):
        gen = SvgBadgeGenerator()
        assert gen.extract_monogram("ASUL LYON VOLLEY BALL") == "ASUL"
        assert gen.extract_monogram("TOURS VOLLEY-BALL") == "TVB"
        assert gen.extract_monogram("CHAUMONT VOLLEY-BALL 52") == "CVB5"
        assert gen.extract_monogram("") == "VB"

    def test_generate_svg_structure(self):
        svg = SvgBadgeGenerator.generate_svg(
            club_name="ASUL LYON VOLLEY BALL",
            couleurs="Rouge / Noir",
            city="Lyon",
        )
        assert "<svg" in svg
        assert "</svg>" in svg
        assert "ASUL" in svg
        assert "LYON" in svg
        # Vérifier présence des éléments graphiques
        assert "linearGradient" in svg
        assert "path" in svg

    def test_generate_data_uri(self):
        data_uri = SvgBadgeGenerator.generate_data_uri(
            club_name="Tours Volley-Ball",
            couleurs="Bleu / Blanc",
            city="Tours",
        )
        assert data_uri.startswith("data:image/svg+xml;base64,")


class TestWikipediaLogoProvider:
    def test_find_logo_success(self, monkeypatch):
        provider = WikipediaLogoProvider()

        # Mock de recherche
        monkeypatch.setattr(
            provider,
            "_search_pages",
            lambda query, limit=3: ["Tours Volley-Ball"] if "tours" in query.lower() else [],
        )
        # Mock d'images
        monkeypatch.setattr(
            provider,
            "_get_page_images",
            lambda title: ["Flag_of_France.svg", "Logo_Tours_Volley-ball_2024.png", "Kit_shorts.png"],
        )
        # Mock d'URL directe
        monkeypatch.setattr(
            provider,
            "_get_image_direct_url",
            lambda fname: "https://upload.wikimedia.org/wikipedia/fr/9/98/Logo_Tours_Volley-ball_2024.png"
            if "Logo_Tours" in fname
            else None,
        )

        res = provider.find_logo("TOURS VOLLEY-BALL", city="TOURS")
        assert res is not None
        assert res.source == "wikipedia"
        assert res.logo_url.endswith("Logo_Tours_Volley-ball_2024.png")
        assert res.file_name == "Logo_Tours_Volley-ball_2024.png"

    def test_find_logo_no_result(self, monkeypatch):
        provider = WikipediaLogoProvider()
        monkeypatch.setattr(provider, "_search_pages", lambda *args, **kwargs: [])
        res = provider.find_logo("Club Inconnu XYZ 99")
        assert res is None


class TestClubLogoService:
    def test_resolve_logo_uses_volleybox_first(self, monkeypatch):
        mock_vb = MagicMock(spec=VolleyboxLogoScraper)
        mock_vb.find_logo_for_club.return_value = LogoCandidate(
            team_url="https://volleybox.net/fr/asul-t123",
            slug="asul",
            score=0.85,
            matched_name="ASUL Lyon Volley",
            matched_city="Lyon",
            logo_url="https://volleybox.net/media/upload/teams/asul.png",
        )

        service = ClubLogoService(volleybox_scraper=mock_vb)
        res = service.resolve_logo(
            nom="ASUL LYON VOLLEY BALL",
            nom_court="ASUL",
            ville="LYON",
            min_score=0.60,
        )

        assert res is not None
        assert res.source == "volleybox"
        assert res.logo_url == "https://volleybox.net/media/upload/teams/asul.png"
        assert res.confidence == 0.85

    def test_resolve_logo_falls_back_to_wikipedia(self, monkeypatch):
        mock_vb = MagicMock(spec=VolleyboxLogoScraper)
        mock_vb.find_logo_for_club.return_value = None

        mock_wiki = MagicMock(spec=WikipediaLogoProvider)
        mock_wiki.find_logo.return_value = WikipediaLogoResult(
            logo_url="https://upload.wikimedia.org/wikipedia/fr/logo.svg",
            page_title="Tours Volley-Ball",
            file_name="Logo.svg",
            score=0.92,
        )

        service = ClubLogoService(
            volleybox_scraper=mock_vb,
            wikipedia_provider=mock_wiki,
        )
        res = service.resolve_logo(
            nom="TOURS VOLLEY-BALL",
            ville="TOURS",
        )

        assert res is not None
        assert res.source == "wikipedia"
        assert res.logo_url == "https://upload.wikimedia.org/wikipedia/fr/logo.svg"
        assert res.confidence == 0.92

    def test_resolve_logo_badge_fallback(self):
        mock_vb = MagicMock(spec=VolleyboxLogoScraper)
        mock_vb.find_logo_for_club.return_value = None

        mock_wiki = MagicMock(spec=WikipediaLogoProvider)
        mock_wiki.find_logo.return_value = None

        service = ClubLogoService(
            volleybox_scraper=mock_vb,
            wikipedia_provider=mock_wiki,
        )
        res = service.resolve_logo(
            nom="PETIT CLUB DE VILLAGE",
            ville="VILLAGE",
            couleurs="Jaune / Noir",
            enable_badge_fallback=True,
        )

        assert res is not None
        assert res.source == "generated_badge"
        assert res.is_fallback is True
        assert res.logo_url.startswith("data:image/svg+xml;base64,")

    def test_prefer_wikipedia_flag(self):
        mock_vb = MagicMock(spec=VolleyboxLogoScraper)
        mock_vb.find_logo_for_club.return_value = LogoCandidate(
            team_url="https://volleybox.net/fr/tours-t1",
            slug="tours",
            score=0.75,
            logo_url="https://volleybox.net/logo_vb.png",
        )

        mock_wiki = MagicMock(spec=WikipediaLogoProvider)
        mock_wiki.find_logo.return_value = WikipediaLogoResult(
            logo_url="https://upload.wikimedia.org/wikipedia/fr/logo_wiki.svg",
            page_title="Tours Volley-Ball",
            file_name="Logo_wiki.svg",
            score=0.95,
        )

        service = ClubLogoService(
            volleybox_scraper=mock_vb,
            wikipedia_provider=mock_wiki,
        )
        res = service.resolve_logo(
            nom="TOURS VOLLEY-BALL",
            prefer_wikipedia=True,
        )

        assert res is not None
        assert res.source == "wikipedia"
        assert res.logo_url == "https://upload.wikimedia.org/wikipedia/fr/logo_wiki.svg"
