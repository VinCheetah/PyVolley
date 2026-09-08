"""
Tests unitaires pour LNVScraper.

Vérifie le wrapper des compétitions professionnelles LNV et sa bonne
délégation vers FFVBScraper.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pyvolley.scrapers.base import MatchInfo, ScrapeResult
from pyvolley.scrapers.ffvb import PouleInfo
from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo
from pyvolley.scrapers.lnv import LNVScraper, PRO_COMPETITIONS, PRO_ENTITY_CODE


@pytest.fixture
def mock_ffvb_scraper():
    scraper = MagicMock()
    scraper._get_current_saison.return_value = "2025/2026"
    return scraper


@pytest.fixture
def lnv_scraper(mock_ffvb_scraper):
    return LNVScraper(ffvb_scraper=mock_ffvb_scraper)


class TestLNVScraper:
    def test_get_pro_competitions(self):
        comps = LNVScraper.get_pro_competitions()
        assert len(comps) == len(PRO_COMPETITIONS)
        codes = [c.code for c in comps]
        assert "MSL" in codes
        assert "SPS" in codes
        assert "LBM" in codes

    def test_discover_competitions(self, lnv_scraper, mock_ffvb_scraper):
        mock_ffvb_scraper.discover_poules.return_value = [
            PouleInfo(code="MSL", nom="Poule MSL", entity_code="AALNV", saison="2025/2026"),
            PouleInfo(code="SPS", nom="Poule SPS", entity_code="AALNV", saison="2025/2026"),
        ]

        poules = lnv_scraper.discover_competitions("2025/2026")
        mock_ffvb_scraper.discover_poules.assert_called_once_with(PRO_ENTITY_CODE, "2025/2026")
        assert len(poules) == 2
        assert poules[0].code == "MSL"

    def test_get_matches(self, lnv_scraper, mock_ffvb_scraper):
        mock_ffvb_scraper.scrape_entity.return_value = [
            ExportMatchInfo(
                code_match="MSLA001",
                entite_code=PRO_ENTITY_CODE,
                saison="2025/2026",
                poule_code="MSL",
                journee="01",
                feuille_match_url="https://example.com/pdf",
            )
        ]

        matches = list(lnv_scraper.get_matches("MSL", "2025/2026"))
        mock_ffvb_scraper.scrape_entity.assert_called_once_with(
            PRO_ENTITY_CODE, "2025/2026", poule="MSL"
        )
        assert len(matches) == 1
        assert isinstance(matches[0], MatchInfo)
        assert matches[0].code == "MSLA001"
        assert matches[0].pdf_url == "https://example.com/pdf"

    def test_get_all_pro_matches(self, lnv_scraper, mock_ffvb_scraper):
        mock_ffvb_scraper.scrape_entity.return_value = [
            ExportMatchInfo(code_match="MSLA001", entite_code=PRO_ENTITY_CODE, saison="2025/2026", poule_code="MSL"),
            ExportMatchInfo(code_match="SPSA001", entite_code=PRO_ENTITY_CODE, saison="2025/2026", poule_code="SPS"),
        ]

        matches = list(lnv_scraper.get_all_pro_matches("2025/2026"))
        mock_ffvb_scraper.scrape_entity.assert_called_once_with(PRO_ENTITY_CODE, "2025/2026")
        assert len(matches) == 2
        assert matches[0].code == "MSLA001"
        assert matches[1].code == "SPSA001"

    def test_download_match(self, lnv_scraper, mock_ffvb_scraper):
        match = MatchInfo(code="MSLA001", entite_code=PRO_ENTITY_CODE, saison="2025/2026")
        mock_ffvb_scraper.download_match_pdf.return_value = ScrapeResult(success=True, message="Downloaded")

        dest = Path("data/pdfs")
        result = lnv_scraper.download_match(match, dest, overwrite=True)
        mock_ffvb_scraper.download_match_pdf.assert_called_once_with(match, dest, overwrite=True)
        assert result.success is True

    def test_count_matches(self, lnv_scraper, mock_ffvb_scraper):
        mock_ffvb_scraper.scrape_entity.return_value = [
            ExportMatchInfo(code_match="MSLA001", entite_code=PRO_ENTITY_CODE, saison="2025/2026", poule_code="MSL"),
            ExportMatchInfo(code_match="MSLA002", entite_code=PRO_ENTITY_CODE, saison="2025/2026", poule_code="MSL"),
            ExportMatchInfo(code_match="SPSA001", entite_code=PRO_ENTITY_CODE, saison="2025/2026", poule_code="SPS"),
        ]

        counts = lnv_scraper.count_matches("2025/2026")
        mock_ffvb_scraper.scrape_entity.assert_called_once_with(PRO_ENTITY_CODE, "2025/2026")
        assert counts["MSL"] == 2
        assert counts["SPS"] == 1
        assert counts["LBM"] == 0
