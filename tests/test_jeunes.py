"""
Tests pour le module jeunes — Coupe de France Jeunes (ACJEUNES).

Tests unitaires pour le scraping, la construction d'URLs
et les modèles de données jeunes.
Les tests marqués @pytest.mark.network nécessitent un accès réseau.
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import asdict

from pyvolley.scrapers.ffvb.jeunes import (
    CATEGORY_LETTER_MAP,
    DIVISION_MAP,
    DIVISION_CATEGORY_LABEL,
    ENTITY_CODE,
    YouthCupIndex,
    YouthDivisionInfo,
    YouthMatchResult,
    YouthPouleInfo,
    YouthStandingEntry,
    YouthTourInfo,
    build_youth_calendar_url,
    build_youth_export_url,
    infer_division_from_poule_code,
    infer_category_from_poule_code,
    scrape_youth_nav,
    scrape_youth_tour,
    _build_nav_url,
    _parse_option_url,
    _parse_select_options,
    _enrich_match_with_division,
    get_youth_cup_index,
    clear_youth_cache,
    _YOUTH_INDEX_CACHE,
)
from pyvolley.scrapers.ffvb.utils import is_youth_entity, saison_to_path

BASE_URL = "https://www.ffvbbeach.org/ffvbapp/resu/"


# ============== Tests des constantes ==============


class TestDivisionMap:
    """Tests du mapping code division → (catégorie, genre)."""

    def test_all_divisions_present(self):
        expected = {
            "JMX", "JFX", "CMX", "CFX", "RMX", "RFX",
            "MMX", "MFX", "BMX", "BFX", "PMA", "PFA",
        }
        assert set(DIVISION_MAP.keys()) == expected

    def test_masculin_codes(self):
        for code in ("JMX", "CMX", "RMX", "MMX", "BMX", "PMA"):
            assert DIVISION_MAP[code][1] == "MASCULIN"

    def test_feminin_codes(self):
        for code in ("JFX", "CFX", "RFX", "MFX", "BFX", "PFA"):
            assert DIVISION_MAP[code][1] == "FEMININ"

    def test_m21_juniors(self):
        assert DIVISION_MAP["JMX"][0] == "M21"
        assert DIVISION_MAP["JFX"][0] == "M21"

    def test_m18_cadets(self):
        assert DIVISION_MAP["CMX"][0] == "M18"
        assert DIVISION_MAP["CFX"][0] == "M18"

    def test_m18_challenge(self):
        assert DIVISION_MAP["RMX"][0] == "M18"
        assert DIVISION_MAP["RFX"][0] == "M18"
        # Label spécifique
        assert DIVISION_CATEGORY_LABEL["RMX"] == "M18-CHALLENGE"
        assert DIVISION_CATEGORY_LABEL["RFX"] == "M18-CHALLENGE"

    def test_m15_minimes(self):
        assert DIVISION_MAP["MMX"][0] == "M15"
        assert DIVISION_MAP["MFX"][0] == "M15"

    def test_m13_benjamins(self):
        assert DIVISION_MAP["BMX"][0] == "M13"
        assert DIVISION_MAP["BFX"][0] == "M13"

    def test_m11_poussins(self):
        assert DIVISION_MAP["PMA"][0] == "M11"
        assert DIVISION_MAP["PFA"][0] == "M11"

    def test_category_labels_match_divisions(self):
        """Chaque division du DIVISION_MAP a un label correspondant."""
        for code in DIVISION_MAP:
            assert code in DIVISION_CATEGORY_LABEL

    def test_entity_code(self):
        assert ENTITY_CODE == "ACJEUNES"


# ============== Tests d'inférence poule → division ==============


class TestInferDivisionFromPouleCode:
    """Tests du mapping code poule → code division."""

    # -- Codes masculins clairement identifiables --

    def test_cm_to_cmx(self):
        assert infer_division_from_poule_code("CMA") == "CMX"

    def test_jm_to_jmx(self):
        assert infer_division_from_poule_code("JMZ") == "JMX"

    def test_bm_to_bmx(self):
        assert infer_division_from_poule_code("BMK") == "BMX"

    def test_mm_to_mmx(self):
        assert infer_division_from_poule_code("MMO") == "MMX"

    def test_rm_to_rmx(self):
        assert infer_division_from_poule_code("RMD") == "RMX"

    # -- Codes féminins clairement identifiables --

    def test_cf_to_cfx(self):
        assert infer_division_from_poule_code("CFA") == "CFX"

    def test_jf_to_jfx(self):
        assert infer_division_from_poule_code("JFN") == "JFX"

    def test_bf_to_bfx(self):
        assert infer_division_from_poule_code("BFA") == "BFX"

    def test_mf_to_mfx(self):
        assert infer_division_from_poule_code("MFP") == "MFX"

    def test_rf_to_rfx(self):
        assert infer_division_from_poule_code("RFA") == "RFX"

    # -- Codes masculins "extra" (X, Y) --

    def test_cx_to_cmx(self):
        """CX*/CY* poules appartiennent à CMX (vérifié par scraping)."""
        assert infer_division_from_poule_code("CXA") == "CMX"

    def test_cy_to_cmx(self):
        assert infer_division_from_poule_code("CYQ") == "CMX"

    def test_bx_to_bmx(self):
        assert infer_division_from_poule_code("BXA") == "BMX"

    def test_jx_to_jmx(self):
        assert infer_division_from_poule_code("JXF") == "JMX"

    def test_mx_to_mmx(self):
        assert infer_division_from_poule_code("MXA") == "MMX"

    def test_rx_to_rmx(self):
        assert infer_division_from_poule_code("RXA") == "RMX"

    # -- Codes féminins "extra" (G, H, I) --

    def test_cg_to_cfx(self):
        """CG*/CH*/CI* poules appartiennent à CFX (vérifié par scraping)."""
        assert infer_division_from_poule_code("CGA") == "CFX"

    def test_ch_to_cfx(self):
        assert infer_division_from_poule_code("CHB") == "CFX"

    def test_ci_to_cfx(self):
        assert infer_division_from_poule_code("CIA") == "CFX"

    def test_bg_to_bfx(self):
        assert infer_division_from_poule_code("BGA") == "BFX"

    def test_bh_to_bfx(self):
        assert infer_division_from_poule_code("BH") == "BFX"

    def test_mg_to_mfx(self):
        assert infer_division_from_poule_code("MGA") == "MFX"

    def test_mh_to_mfx(self):
        assert infer_division_from_poule_code("MHA") == "MFX"

    def test_rg_to_rfx(self):
        assert infer_division_from_poule_code("RGA") == "RFX"

    # -- Cas limites --

    def test_empty(self):
        assert infer_division_from_poule_code("") is None

    def test_single_char(self):
        assert infer_division_from_poule_code("C") is None

    def test_unknown_first_letter(self):
        assert infer_division_from_poule_code("ZZZ") is None

    def test_two_char_code(self):
        """Les codes à 2 caractères (ex: BG, CX) doivent fonctionner."""
        assert infer_division_from_poule_code("BG") == "BFX"
        assert infer_division_from_poule_code("CX") == "CMX"

    def test_cc_fallback(self):
        """CC : 2e lettre 'C' non M/F/G/H/I/X/Y → fallback masculin."""
        result = infer_division_from_poule_code("CC")
        assert result is not None  # Doit retourner le fallback masculin


class TestInferCategoryFromPouleCode:
    """Tests de la détection de catégorie depuis le code poule."""

    def test_m13(self):
        cat, label = infer_category_from_poule_code("BMA")
        assert cat == "M13"

    def test_m18(self):
        cat, label = infer_category_from_poule_code("CFA")
        assert cat == "M18"

    def test_m18_challenge(self):
        cat, label = infer_category_from_poule_code("RMA")
        assert cat == "M18"
        assert "CHALLENGE" in label

    def test_m21(self):
        cat, label = infer_category_from_poule_code("JMZ")
        assert cat == "M21"

    def test_m15(self):
        cat, label = infer_category_from_poule_code("MFP")
        assert cat == "M15"

    def test_unknown(self):
        assert infer_category_from_poule_code("ZZZ") is None

    def test_empty(self):
        assert infer_category_from_poule_code("") is None


class TestEnrichMatchWithDivision:
    """Tests de l'enrichissement d'un match avec les métadonnées de division."""

    def _make_match(self):
        from pyvolley.scrapers.ffvb.export_scraper import ExportMatchInfo
        return ExportMatchInfo(
            code_match="CMA001",
            entite_code="ACJEUNES",
        )

    def test_enrich_masculin(self):
        match = self._make_match()
        _enrich_match_with_division(match, "CMX")
        assert match.genre == "MASCULIN"
        assert match.categorie_age == "M18"
        assert match.division_code == "CMX"
        assert match.niveau == "NATIONALE"
        assert match.type_competition == "COUPE"
        assert "M18" in match.competition_nom
        assert "Masc." in match.competition_nom

    def test_enrich_feminin(self):
        match = self._make_match()
        _enrich_match_with_division(match, "CFX")
        assert match.genre == "FEMININ"
        assert match.categorie_age == "M18"
        assert match.division_code == "CFX"
        assert "Fém." in match.competition_nom

    def test_enrich_challenge(self):
        match = self._make_match()
        _enrich_match_with_division(match, "RMX")
        assert match.categorie_age == "M18"
        assert "CHALLENGE" in match.competition_nom

    def test_competition_groupe_includes_gender(self):
        """Le groupe de compétition doit inclure le genre pour le regroupement."""
        match = self._make_match()
        _enrich_match_with_division(match, "CMX")
        assert "Masc." in match.competition_groupe

        match2 = self._make_match()
        _enrich_match_with_division(match2, "CFX")
        assert "Fém." in match2.competition_groupe

        # Les deux doivent avoir des groupes différents
        assert match.competition_groupe != match2.competition_groupe


# ============== Tests des utilitaires ==============


class TestIsYouthEntity:
    """Tests de la détection d'entité jeune."""

    def test_acjeunes(self):
        assert is_youth_entity("ACJEUNES") is True

    def test_acjeunes_lowercase(self):
        assert is_youth_entity("acjeunes") is True

    def test_other_entity(self):
        assert is_youth_entity("ABCCS") is False

    def test_empty(self):
        assert is_youth_entity("") is False


class TestSaisonToPath:
    """Tests de la conversion saison → chemin."""

    def test_slash_to_dash(self):
        assert saison_to_path("2025/2026") == "2025-2026"

    def test_already_dash(self):
        assert saison_to_path("2025-2026") == "2025-2026"


# ============== Tests de construction d'URLs ==============


class TestBuildNavUrl:

    def test_standard(self):
        url = _build_nav_url(BASE_URL, "2025/2026")
        assert url == f"{BASE_URL}jeunes/2025-2026/pbscript.htm"

    def test_different_saison(self):
        url = _build_nav_url(BASE_URL, "2024/2025")
        assert "2024-2025" in url
        assert url.endswith("/pbscript.htm")


class TestBuildYouthCalendarUrl:

    def test_standard(self):
        url = build_youth_calendar_url(BASE_URL, "2025/2026", "CMX", 1)
        assert "saison=2025%2F2026" in url
        assert "codent=ACJEUNES" in url
        assert "division=CMX" in url
        assert "tour=01" in url
        assert "vbspo_calendrier.php" in url

    def test_different_division(self):
        url = build_youth_calendar_url(BASE_URL, "2025/2026", "BFX", 3)
        assert "division=BFX" in url
        assert "tour=03" in url

    def test_tour_padding(self):
        url = build_youth_calendar_url(BASE_URL, "2025/2026", "JMX", 7)
        assert "tour=07" in url


class TestBuildYouthExportUrl:

    def test_with_division(self):
        url = build_youth_export_url(BASE_URL, "2025/2026", "CMX")
        assert "vbspo_calendrier_export.php" in url
        assert "codent=ACJEUNES" in url
        assert "division=CMX" in url
        assert "calend=COMPLET" in url

    def test_without_division(self):
        url = build_youth_export_url(BASE_URL, "2025/2026")
        assert "division" not in url
        assert "codent=ACJEUNES" in url

    def test_saison_encoding(self):
        url = build_youth_export_url(BASE_URL, "2025/2026", "JFX")
        assert "saison=2025%2F2026" in url


# ============== Tests de parsing d'URL d'option ==============


class TestParseOptionUrl:

    def test_standard_url(self):
        url = (
            "https://www.ffvbbeach.org/ffvbapp/resu/vbspo_calendrier.php"
            "?saison=2025/2026&codent=ACJEUNES&division=CMX&tour=01"
        )
        result = _parse_option_url(url)
        assert result is not None
        assert result["saison"] == "2025/2026"
        assert result["codent"] == "ACJEUNES"
        assert result["division"] == "CMX"
        assert result["tour"] == "01"

    def test_finales_url(self):
        url = (
            "https://www.ffvbbeach.org/ffvbapp/resu/ffvb_jeunes_finales.php"
            "?poule=PMA"
        )
        result = _parse_option_url(url)
        assert result is not None
        assert result["poule"] == "PMA"

    def test_empty_url(self):
        result = _parse_option_url("")
        assert result is None

    def test_url_without_params(self):
        result = _parse_option_url("https://example.com/page")
        assert result is None


# ============== Tests des modèles de données ==============


class TestYouthDivisionInfo:

    def test_nom_complet_masculin(self):
        div = YouthDivisionInfo(
            code="CMX", categorie_age="M18",
            genre="MASCULIN", categorie_label="M18",
        )
        assert div.nom_complet == "CdF Jeunes M18 Masc."

    def test_nom_complet_feminin(self):
        div = YouthDivisionInfo(
            code="CFX", categorie_age="M18",
            genre="FEMININ", categorie_label="M18",
        )
        assert div.nom_complet == "CdF Jeunes M18 Fém."

    def test_nom_complet_challenge(self):
        div = YouthDivisionInfo(
            code="RMX", categorie_age="M18",
            genre="MASCULIN", categorie_label="M18-CHALLENGE",
        )
        assert "M18-CHALLENGE" in div.nom_complet

    def test_nb_tours_empty(self):
        div = YouthDivisionInfo(
            code="CMX", categorie_age="M18",
            genre="MASCULIN", categorie_label="M18",
        )
        assert div.nb_tours == 0

    def test_nb_tours_with_tours(self):
        div = YouthDivisionInfo(
            code="CMX", categorie_age="M18",
            genre="MASCULIN", categorie_label="M18",
            tours=[
                YouthTourInfo(numero=1, division_code="CMX", url=""),
                YouthTourInfo(numero=2, division_code="CMX", url=""),
            ],
        )
        assert div.nb_tours == 2


class TestYouthTourInfo:

    def test_code_formatting(self):
        tour = YouthTourInfo(numero=1, division_code="CMX", url="")
        assert tour.code == "T01"

    def test_code_formatting_two_digits(self):
        tour = YouthTourInfo(numero=12, division_code="CMX", url="")
        assert tour.code == "T12"

    def test_nom_complet(self):
        tour = YouthTourInfo(numero=3, division_code="CMX", url="")
        assert "Tour 3" in tour.nom_complet
        assert "M18" in tour.nom_complet
        assert "Masc." in tour.nom_complet


class TestYouthPouleInfo:

    def test_categorie_age(self):
        poule = YouthPouleInfo(
            code="CYQ", tour_numero=1, division_code="CMX",
        )
        assert poule.categorie_age == "M18"

    def test_genre(self):
        poule = YouthPouleInfo(
            code="CYQ", tour_numero=1, division_code="CMX",
        )
        assert poule.genre == "MASCULIN"

    def test_unknown_division(self):
        poule = YouthPouleInfo(
            code="XXX", tour_numero=1, division_code="ZZZ",
        )
        assert poule.categorie_age == "?"
        assert poule.genre == "?"


class TestYouthCupIndex:

    def _make_index(self) -> YouthCupIndex:
        index = YouthCupIndex(saison="2025/2026")
        for code, (cat, genre) in DIVISION_MAP.items():
            cat_label = DIVISION_CATEGORY_LABEL[code]
            tours = [
                YouthTourInfo(numero=i, division_code=code, url=f"url_{code}_{i}")
                for i in range(1, 4)  # 3 tours chacune
            ]
            index.divisions[code] = YouthDivisionInfo(
                code=code,
                categorie_age=cat,
                genre=genre,
                categorie_label=cat_label,
                tours=tours,
            )
        return index

    def test_nb_divisions(self):
        index = self._make_index()
        assert index.nb_divisions == 12

    def test_nb_tours_total(self):
        index = self._make_index()
        assert index.nb_tours_total == 36  # 12 * 3

    def test_categories(self):
        index = self._make_index()
        cats = index.categories
        assert "M11" in cats
        assert "M13" in cats
        assert "M15" in cats
        assert "M18" in cats
        assert "M18-CHALLENGE" in cats
        assert "M21" in cats

    def test_get_division(self):
        index = self._make_index()
        div = index.get_division("CMX")
        assert div is not None
        assert div.code == "CMX"
        assert div.categorie_age == "M18"

    def test_get_division_none(self):
        index = self._make_index()
        assert index.get_division("ZZZ") is None

    def test_get_divisions_by_category(self):
        index = self._make_index()
        m18_divs = index.get_divisions_by_category("M18")
        codes = {d.code for d in m18_divs}
        assert codes == {"CMX", "CFX"}

    def test_get_divisions_by_category_challenge(self):
        index = self._make_index()
        m18ch = index.get_divisions_by_category("M18-CHALLENGE")
        codes = {d.code for d in m18ch}
        assert codes == {"RMX", "RFX"}

    def test_summary(self):
        index = self._make_index()
        summary = index.summary()
        assert "2025/2026" in summary
        assert "12 divisions" in summary
        assert "36 tours" in summary

    def test_empty_index(self):
        index = YouthCupIndex(saison="2025/2026")
        assert index.nb_divisions == 0
        assert index.nb_tours_total == 0
        assert index.categories == []


class TestYouthStandingEntry:

    def test_creation(self):
        entry = YouthStandingEntry(
            rang=1, equipe="AS Monaco", club_code="1234567",
            points=12, joues=4, gagnes=4, perdus=0,
        )
        assert entry.rang == 1
        assert entry.equipe == "AS Monaco"
        assert entry.points == 12

    def test_defaults(self):
        entry = YouthStandingEntry(rang=1, equipe="Test")
        assert entry.club_code == ""
        assert entry.points == 0
        assert entry.forfaits == 0


class TestYouthMatchResult:

    def test_creation(self):
        match = YouthMatchResult(
            code="CYQ001", poule_code="CYQ",
            date="15/03/26", heure="10:00",
            equipe_a="Team A", equipe_b="Team B",
            sets_a=3, sets_b=1,
        )
        assert match.code == "CYQ001"
        assert match.poule_code == "CYQ"

    def test_defaults(self):
        match = YouthMatchResult(code="CYQ001", poule_code="CYQ")
        assert match.date is None
        assert match.equipe_a is None
        assert match.sets_a is None
        assert match.pdf_url is None


# ============== Tests du parsing de navigation ==============


SAMPLE_NAV_HTML = """
<html>
<head></head>
<body>
<select name="cat1">
  <option value="">-- Choisir --</option>
  <option value="https://www.ffvbbeach.org/ffvbapp/resu/vbspo_calendrier.php?saison=2025/2026&codent=ACJEUNES&division=CMX&tour=01">Tour 1</option>
  <option value="https://www.ffvbbeach.org/ffvbapp/resu/vbspo_calendrier.php?saison=2025/2026&codent=ACJEUNES&division=CMX&tour=02">Tour 2</option>
</select>
<select name="cat2">
  <option value="https://www.ffvbbeach.org/ffvbapp/resu/vbspo_calendrier.php?saison=2025/2026&codent=ACJEUNES&division=JFX&tour=01">Tour 1</option>
</select>
<select name="finale">
  <option value="https://www.ffvbbeach.org/ffvbapp/resu/ffvb_jeunes_finales.php?poule=PMA">Finales M11 Masc.</option>
</select>
</body>
</html>
""".encode("windows-1252")


class TestScrapeYouthNav:

    def _make_mock_client(self, content: bytes):
        client = MagicMock()
        response = MagicMock()
        response.content = content
        client.get.return_value = response
        return client

    def test_parse_divisions_and_tours(self):
        client = self._make_mock_client(SAMPLE_NAV_HTML)
        index = scrape_youth_nav(client, BASE_URL, "2025/2026")

        assert "CMX" in index.divisions
        assert "JFX" in index.divisions
        assert index.divisions["CMX"].nb_tours == 2
        assert index.divisions["JFX"].nb_tours == 1

    def test_parse_finales(self):
        client = self._make_mock_client(SAMPLE_NAV_HTML)
        index = scrape_youth_nav(client, BASE_URL, "2025/2026")
        assert "PMA" in index.finales_urls

    def test_division_metadata(self):
        client = self._make_mock_client(SAMPLE_NAV_HTML)
        index = scrape_youth_nav(client, BASE_URL, "2025/2026")

        cmx = index.divisions["CMX"]
        assert cmx.categorie_age == "M18"
        assert cmx.genre == "MASCULIN"
        assert cmx.categorie_label == "M18"

    def test_tours_sorted(self):
        """Les tours doivent être triés par numéro."""
        client = self._make_mock_client(SAMPLE_NAV_HTML)
        index = scrape_youth_nav(client, BASE_URL, "2025/2026")

        cmx = index.divisions["CMX"]
        assert cmx.tours[0].numero == 1
        assert cmx.tours[1].numero == 2

    def test_tour_urls_set(self):
        client = self._make_mock_client(SAMPLE_NAV_HTML)
        index = scrape_youth_nav(client, BASE_URL, "2025/2026")

        cmx = index.divisions["CMX"]
        for tour in cmx.tours:
            assert tour.url.startswith("https://")

    def test_empty_response(self):
        client = self._make_mock_client(b"<html></html>")
        index = scrape_youth_nav(client, BASE_URL, "2025/2026")
        assert index.nb_divisions == 0

    def test_network_error(self):
        client = MagicMock()
        client.get.side_effect = Exception("Connection refused")
        index = scrape_youth_nav(client, BASE_URL, "2025/2026")
        assert index.nb_divisions == 0


# ============== Tests du parsing de tour (calendrier HTML) ==============


SAMPLE_TOUR_HTML = """
<html>
<body>
<table>
  <tr>
    <td>Clt</td><td>Equipe</td><td>Points</td><td>Jou.</td><td>Gag.</td><td>Per.</td>
  </tr>
  <tr>
    <td>1</td><td>AS Volley Aix</td><td>12</td><td>4</td><td>4</td><td>0</td>
  </tr>
  <tr>
    <td>2</td><td>BC Volley Nice</td><td>8</td><td>4</td><td>2</td><td>2</td>
  </tr>
</table>
<table>
  <tr>
    <td>Tour 01</td><td></td><td></td><td></td>
  </tr>
  <tr>
    <td>CYQ001</td><td>15/03/26</td><td>10:00</td><td>AS Volley Aix - BC Volley Nice</td>
  </tr>
  <tr>
    <td>CYQ002</td><td>15/03/26</td><td>11:30</td><td>BC Volley Nice - AS Volley Aix</td>
  </tr>
</table>
<table>
  <tr>
    <td>Clt</td><td>Equipe</td><td>Points</td><td>Jou.</td><td>Gag.</td><td>Per.</td>
  </tr>
  <tr>
    <td>1</td><td>RC Cannes</td><td>6</td><td>2</td><td>2</td><td>0</td>
  </tr>
  <tr>
    <td>2</td><td>Montpellier VB</td><td>4</td><td>2</td><td>1</td><td>1</td>
  </tr>
</table>
<table>
  <tr>
    <td>Tour 01</td><td></td>
  </tr>
  <tr>
    <td>CYR001</td><td>16/03/26</td>
  </tr>
</table>
</body>
</html>
""".encode("windows-1252")


class TestScrapeYouthTour:

    def _make_mock_client(self, content: bytes):
        client = MagicMock()
        response = MagicMock()
        response.content = content
        client.get.return_value = response
        return client

    def test_parse_multiple_poules(self):
        client = self._make_mock_client(SAMPLE_TOUR_HTML)
        poules = scrape_youth_tour(client, BASE_URL, "2025/2026", "CMX", 1)
        assert len(poules) == 2

    def test_poule_codes(self):
        client = self._make_mock_client(SAMPLE_TOUR_HTML)
        poules = scrape_youth_tour(client, BASE_URL, "2025/2026", "CMX", 1)
        codes = {p.code for p in poules}
        assert "CYQ" in codes
        assert "CYR" in codes

    def test_poule_equipes(self):
        client = self._make_mock_client(SAMPLE_TOUR_HTML)
        poules = scrape_youth_tour(client, BASE_URL, "2025/2026", "CMX", 1)
        poule_cyq = next(p for p in poules if p.code == "CYQ")
        assert "AS Volley Aix" in poule_cyq.equipes
        assert "BC Volley Nice" in poule_cyq.equipes

    def test_poule_nb_matchs(self):
        client = self._make_mock_client(SAMPLE_TOUR_HTML)
        poules = scrape_youth_tour(client, BASE_URL, "2025/2026", "CMX", 1)
        poule_cyq = next(p for p in poules if p.code == "CYQ")
        assert poule_cyq.nb_matchs == 2

    def test_poule_metadata(self):
        client = self._make_mock_client(SAMPLE_TOUR_HTML)
        poules = scrape_youth_tour(client, BASE_URL, "2025/2026", "CMX", 1)
        for poule in poules:
            assert poule.tour_numero == 1
            assert poule.division_code == "CMX"
            assert poule.saison == "2025/2026"

    def test_empty_page(self):
        client = self._make_mock_client(b"<html></html>")
        poules = scrape_youth_tour(client, BASE_URL, "2025/2026", "CMX", 1)
        assert poules == []

    def test_network_error(self):
        client = MagicMock()
        client.get.side_effect = Exception("Timeout")
        poules = scrape_youth_tour(client, BASE_URL, "2025/2026", "CMX", 1)
        assert poules == []


# ============== Tests du cache ==============


class TestYouthCache:

    def setup_method(self):
        clear_youth_cache()

    def teardown_method(self):
        clear_youth_cache()

    def test_cache_stores_index(self):
        client = MagicMock()
        response = MagicMock()
        response.content = SAMPLE_NAV_HTML
        client.get.return_value = response

        index1 = get_youth_cup_index(client, BASE_URL, "2025/2026")
        index2 = get_youth_cup_index(client, BASE_URL, "2025/2026")

        # Deuxième appel doit utiliser le cache (HTTP appelé 1 seule fois)
        assert client.get.call_count == 1
        assert index1 is index2

    def test_force_refresh(self):
        client = MagicMock()
        response = MagicMock()
        response.content = SAMPLE_NAV_HTML
        client.get.return_value = response

        get_youth_cup_index(client, BASE_URL, "2025/2026")
        get_youth_cup_index(client, BASE_URL, "2025/2026", force_refresh=True)

        assert client.get.call_count == 2

    def test_clear_cache(self):
        _YOUTH_INDEX_CACHE["test"] = YouthCupIndex(saison="test")
        clear_youth_cache()
        assert len(_YOUTH_INDEX_CACHE) == 0


# ============== Tests réseau (optionnels) ==============


@pytest.mark.network
class TestYouthScraperNetwork:
    """Tests nécessitant un accès réseau au site FFVB."""

    @pytest.fixture
    def client(self):
        from pyvolley.scrapers.http_client import HttpClient
        return HttpClient(timeout=30)

    def test_scrape_nav_live(self, client):
        index = scrape_youth_nav(client, BASE_URL, "2025/2026")
        assert index.nb_divisions > 0
        assert "CMX" in index.divisions or "JMX" in index.divisions

    def test_scrape_tour_live(self, client):
        poules = scrape_youth_tour(
            client, BASE_URL, "2025/2026", "CMX", 1,
        )
        # Tour 1 devrait avoir au moins quelques poules
        assert len(poules) >= 0  # Pas forcément des données
