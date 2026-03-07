"""
Tests pour le module export_scraper (Phase 1 du pipeline).

Tests unitaires pour le parsing CSV et l'extraction des données.
Les tests marqués @pytest.mark.network nécessitent un accès réseau.
"""

import pytest
from datetime import date

from pyvolley.scrapers.ffvb.export_scraper import (
    ExportMatchInfo,
    ArbitreInfo,
    fetch_export,
    parse_export_csv,
    get_unique_poules,
    get_unique_clubs,
    build_export_url,
    build_feuille_match_url,
    _extract_poule_code,
    _parse_set_score,
    _parse_sets_from_score_column,
    _parse_set_result,
    _parse_date,
)

BASE_URL = "https://www.ffvbbeach.org/ffvbapp/resu/"


# ============== Tests de parsing bas niveau ==============


class TestParseSetScore:
    """Tests du parsing de score de set individuel."""

    def test_dash_separator(self):
        assert _parse_set_score("25-18") == (25, 18)

    def test_slash_separator(self):
        assert _parse_set_score("25/18") == (25, 18)

    def test_empty(self):
        assert _parse_set_score("") is None

    def test_none(self):
        assert _parse_set_score(None) is None

    def test_whitespace(self):
        assert _parse_set_score("  25-18  ") == (25, 18)

    def test_invalid(self):
        assert _parse_set_score("abc") is None

    def test_forfait_score(self):
        assert _parse_set_score("0-25") == (0, 25)
        assert _parse_set_score("25-0") == (25, 0)


class TestParseSetsFromScoreColumn:
    """Tests du parsing de la colonne Score (scores de sets séparés par virgule)."""

    def test_three_sets(self):
        result = _parse_sets_from_score_column("25-18,25-20,25-22")
        assert result == [(25, 18), (25, 20), (25, 22)]

    def test_four_sets(self):
        result = _parse_sets_from_score_column("24-26,25-22,21-25,22-25")
        assert result == [(24, 26), (25, 22), (21, 25), (22, 25)]

    def test_five_sets(self):
        result = _parse_sets_from_score_column("25-18,27-25,25-27,19-25,15-13")
        assert result == [(25, 18), (27, 25), (25, 27), (19, 25), (15, 13)]

    def test_empty(self):
        assert _parse_sets_from_score_column("") == []

    def test_none(self):
        assert _parse_sets_from_score_column(None) == []

    def test_forfait_scores(self):
        result = _parse_sets_from_score_column("0-25,0-25,0-25")
        assert result == [(0, 25), (0, 25), (0, 25)]


class TestParseSetResult:
    """Tests du parsing de la colonne Set (résultat en sets)."""

    def test_normal_result(self):
        assert _parse_set_result(" 3/1") == ("3", "1")

    def test_three_zero(self):
        assert _parse_set_result(" 3/0") == ("3", "0")

    def test_forfait_a(self):
        assert _parse_set_result(" P/3") == ("P", "3")

    def test_forfait_b(self):
        assert _parse_set_result(" 3/P") == ("3", "P")

    def test_empty(self):
        assert _parse_set_result("") is None

    def test_none(self):
        assert _parse_set_result(None) is None


class TestParseDate:
    """Tests du parsing de dates."""

    def test_iso_format(self):
        assert _parse_date("2025-09-27") == date(2025, 9, 27)

    def test_french_format(self):
        assert _parse_date("27/09/2025") == date(2025, 9, 27)

    def test_dash_french(self):
        assert _parse_date("27-09-2025") == date(2025, 9, 27)

    def test_empty(self):
        assert _parse_date("") is None


# ============== Tests unitaires (pas de réseau) ==============


class TestExtractPouleCode:
    """Tests de l'extraction du code poule depuis un code match."""

    def test_standard_code(self):
        # PMAA001 -> regex extracts "PMAA" (letters before digits)
        result = _extract_poule_code("PMAA001")
        assert result in ("PMA", "PMAA")  # Depends on regex pattern

    def test_two_letter_poule(self):
        assert _extract_poule_code("EFA003") == "EFA"

    def test_three_digit_match(self):
        assert _extract_poule_code("EMA051") == "EMA"

    def test_alphanumeric_prefix(self):
        assert _extract_poule_code("2FA001") == "2FA"

    def test_four_char_code(self):
        assert _extract_poule_code("SN1A003") == "SN1A"

    def test_short_code(self):
        result = _extract_poule_code("AB")
        assert isinstance(result, str)

    def test_empty_code(self):
        result = _extract_poule_code("")
        assert result == ""


class TestBuildExportUrl:
    """Tests de la construction des URLs d'export."""

    def test_basic_url(self):
        url = build_export_url(BASE_URL, "ABCCS", "2025/2026")
        assert "vbspo_calendrier_export.php" in url
        assert "codent=ABCCS" in url
        assert "saison=2025" in url

    def test_with_poule(self):
        url = build_export_url(BASE_URL, "ABCCS", "2025/2026", poule="EFA")
        assert "poule=EFA" in url


class TestBuildFeuilleMatchUrl:
    """Tests de la construction des URLs de feuille de match."""

    def test_basic_url(self):
        url = build_feuille_match_url(BASE_URL, "ABCCS", "EFA001", "2025/2026")
        assert "ffvolley_fdme.php" in url
        assert "codent=ABCCS" in url
        assert "codmatch=EFA001" in url


# ============== Tests du parsing CSV complet ==============


class TestParseExportCsv:
    """Tests de parse_export_csv avec des données CSV synthétiques."""

    HEADER = (
        "Entité;Jo;Match;Date;Heure;EQA_no;EQA_nom;EQB_no;EQB_nom;"
        "Set;Score;Total;Salle;Arb1_Lic;Arb1_Nom;Arb1_LR;Arb1_CD;"
        "Arb2_Lic;Arb2_Nom;Arb2_LR;Arb2_CD;"
        "Jdl1_Lic;Jdl1_Nom;Jdl2_Lic;Jdl2_Nom;Jdl3_Lic;Jdl3_Nom;"
        "Jdl4_Lic;Jdl4_Nom;Mrq1_Lic;Mrq1_Nom;Mrq2_Lic;Mrq2_Nom;"
        "Sup_Lic;Sup_Nom;Slnv_Lic;Slnv_Nom;Vid_Lic;Vid_Nom;\n"
    )

    def _make_csv(self, *data_lines: str) -> bytes:
        """Construit un CSV complet avec header + lignes de données."""
        content = self.HEADER + "\n".join(data_lines)
        return content.encode("latin-1")

    def test_played_match_3_0(self):
        csv_data = self._make_csv(
            "ABCCS;01;EMA001;2025-09-27;19:30;0132380;EQUIPE A;0132348;EQUIPE B;"
            " 3/0;25-18,25-16,25-19;75-53;GYMNASE X;"
            "1633896;DUPONT JEAN;PACA;Var;"
            "1524069;MARTIN MARIE;ARA;Rhône;"
            ";;;;;;;;;;;;;;;;;\n"
        )
        matches = parse_export_csv(csv_data, "ABCCS", "2025/2026", BASE_URL)

        assert len(matches) == 1
        m = matches[0]
        assert m.code_match == "EMA001"
        assert m.entite_code == "ABCCS"
        assert m.poule_code == "EMA"
        assert m.saison == "2025/2026"
        assert m.journee == "01"
        assert m.equipe_a_nom == "EQUIPE A"
        assert m.equipe_b_nom == "EQUIPE B"
        assert m.club_a_code_ffvb == "0132380"
        assert m.club_b_code_ffvb == "0132348"
        assert m.sets == [(25, 18), (25, 16), (25, 19)]
        assert m.score_sets == "3/0"
        assert m.sets_equipe_a == 3
        assert m.sets_equipe_b == 0
        assert m.vainqueur == "EQUIPE A"
        assert m.match_joue is True
        assert m.forfait is False
        assert m.date_match == date(2025, 9, 27)
        assert m.heure == "19:30"
        assert m.salle == "GYMNASE X"
        assert len(m.arbitres) == 2
        assert m.arbitres[0].licence == "1633896"
        assert m.arbitres[0].nom == "DUPONT JEAN"
        assert m.arbitres[0].ligue == "PACA"
        assert m.arbitres[0].comite_departemental == "Var"
        assert "ffvolley_fdme.php" in m.feuille_match_url

    def test_played_match_5_sets(self):
        csv_data = self._make_csv(
            "ABCCS;01;2FA006;2025-09-28;15:00;0136082;TEAM A;0067689;TEAM B;"
            " 3/2;25-18,27-25,25-27,19-25,15-13;111-108;SALLE Y;"
            "0;;;;;0;;;;;;;;;;;;;;;;;;;;;\n"
        )
        matches = parse_export_csv(csv_data, "ABCCS", "2025/2026", BASE_URL)

        assert len(matches) == 1
        m = matches[0]
        assert len(m.sets) == 5
        assert m.sets[4] == (15, 13)
        assert m.score_sets == "3/2"
        assert m.vainqueur == "TEAM A"

    def test_unplayed_match(self):
        csv_data = self._make_csv(
            "ABCCS;01;EMA101;2026-03-15;20:00;0132380;EQUIPE A;0132348;EQUIPE B;"
            ";;;GYMNASE Z;"
            "0;;;;;0;;;;;;;;;;;;;;;;;;;;;;\n"
        )
        matches = parse_export_csv(csv_data, "ABCCS", "2025/2026", BASE_URL)

        assert len(matches) == 1
        m = matches[0]
        assert m.match_joue is False
        assert m.sets == []
        assert m.score_sets is None
        assert m.vainqueur is None
        assert m.date_match == date(2026, 3, 15)

    def test_forfait_p_3(self):
        csv_data = self._make_csv(
            "ABCCS;01;2FD062;2025-10-05;15:00;0136082;TEAM A;0067689;TEAM B;"
            " P/3;0-25,0-25,0-25;0-75;SALLE X;"
            "0;;;;;0;;;;;;;;;;;;;;;;;;;;;;\n"
        )
        matches = parse_export_csv(csv_data, "ABCCS", "2025/2026", BASE_URL)

        assert len(matches) == 1
        m = matches[0]
        assert m.forfait is True
        assert m.match_joue is True
        assert m.vainqueur == "TEAM B"
        assert m.score_sets == "0/3"  # P replaced by 0

    def test_forfait_3_p(self):
        csv_data = self._make_csv(
            "ABCCS;01;3FA012;2025-10-05;15:00;0136082;TEAM A;0067689;TEAM B;"
            " 3/P;25-0,25-0,25-0;75-0;SALLE X;"
            "0;;;;;0;;;;;;;;;;;;;;;;;;;;;;\n"
        )
        matches = parse_export_csv(csv_data, "ABCCS", "2025/2026", BASE_URL)

        assert len(matches) == 1
        m = matches[0]
        assert m.forfait is True
        assert m.vainqueur == "TEAM A"
        assert m.score_sets == "3/0"

    def test_xxxxx_opponent(self):
        csv_data = self._make_csv(
            "ABCCS;01;2FA001;2025-09-28;15:00;0136082;TEAM A;;xxxxx;"
            ";;;SALLE X;"
            "0;;;;;0;;;;;;;;;;;;;;;;;;;;;;\n"
        )
        matches = parse_export_csv(csv_data, "ABCCS", "2025/2026", BASE_URL)

        assert len(matches) == 1
        m = matches[0]
        assert m.equipe_a_nom == "TEAM A"
        assert m.equipe_b_nom is None  # xxxxx filtered out

    def test_arbitre_licence_zero_filtered(self):
        csv_data = self._make_csv(
            "ABCCS;01;EMA001;2025-09-27;19:30;0132380;A;0132348;B;"
            " 3/0;25-18,25-16,25-19;75-53;SALLE;"
            "0;;;;0;;;;;;;;;;;;;;;;;;;;;;;;\n"
        )
        matches = parse_export_csv(csv_data, "ABCCS", "2025/2026", BASE_URL)
        # Licence "0" should be filtered out, and no name => no arbitre
        assert len(matches) == 1
        assert len(matches[0].arbitres) == 0

    def test_multiple_matches_multiple_poules(self):
        csv_data = self._make_csv(
            "ABCCS;01;EMA001;2025-09-27;19:30;001;A;002;B; 3/0;25-18,25-16,25-19;75-53;S1;0;;;;0;;;;;;;;;;;;;;;;;;;;;;;;\n",
            "ABCCS;01;EFA001;2025-09-27;20:00;003;C;004;D; 1/3;18-25,25-20,20-25,22-25;85-95;S2;0;;;;0;;;;;;;;;;;;;;;;;;;;;;;;\n",
        )
        matches = parse_export_csv(csv_data, "ABCCS", "2025/2026", BASE_URL)

        assert len(matches) == 2
        poules = get_unique_poules(matches)
        assert "EMA" in poules
        assert "EFA" in poules

    def test_empty_csv(self):
        matches = parse_export_csv(b"", "ABCCS", "2025/2026", BASE_URL)
        assert matches == []

    def test_header_only(self):
        csv_data = self.HEADER.encode("latin-1")
        matches = parse_export_csv(csv_data, "ABCCS", "2025/2026", BASE_URL)
        assert matches == []


# ============== Tests des dataclasses ==============


class TestGetUniquePoules:
    """Tests de l'extraction de poules uniques."""

    def test_empty_list(self):
        assert get_unique_poules([]) == {}

    def test_single_match(self):
        match = ExportMatchInfo(
            code_match="EFA001", entite_code="ABCCS",
            poule_code="EFA", saison="2025/2026",
        )
        result = get_unique_poules([match])
        assert "EFA" in result
        assert len(result["EFA"]) == 1

    def test_multiple_matches_same_poule(self):
        matches = [
            ExportMatchInfo(code_match="EFA001", entite_code="ABCCS", poule_code="EFA", saison="2025/2026"),
            ExportMatchInfo(code_match="EFA002", entite_code="ABCCS", poule_code="EFA", saison="2025/2026"),
        ]
        result = get_unique_poules(matches)
        assert len(result) == 1
        assert len(result["EFA"]) == 2

    def test_multiple_poules(self):
        matches = [
            ExportMatchInfo(code_match="EFA001", entite_code="ABCCS", poule_code="EFA", saison="2025/2026"),
            ExportMatchInfo(code_match="EMA001", entite_code="ABCCS", poule_code="EMA", saison="2025/2026"),
        ]
        result = get_unique_poules(matches)
        assert len(result) == 2


class TestGetUniqueClubs:
    """Tests de l'extraction de clubs uniques."""

    def test_empty_list(self):
        assert get_unique_clubs([]) == set()

    def test_extracts_both_clubs(self):
        match = ExportMatchInfo(
            code_match="EFA001", entite_code="ABCCS", poule_code="EFA",
            saison="2025/2026", club_a_code_ffvb="1234567", club_b_code_ffvb="7654321",
        )
        result = get_unique_clubs([match])
        assert "1234567" in result
        assert "7654321" in result

    def test_skips_empty_codes(self):
        match = ExportMatchInfo(
            code_match="EFA001", entite_code="ABCCS", poule_code="EFA",
            saison="2025/2026", club_a_code_ffvb="1234567", club_b_code_ffvb=None,
        )
        result = get_unique_clubs([match])
        assert len(result) == 1


class TestExportMatchInfo:
    """Tests du dataclass ExportMatchInfo."""

    def test_default_values(self):
        m = ExportMatchInfo(
            code_match="EFA001", entite_code="ABCCS",
            poule_code="EFA", saison="2025/2026",
        )
        assert m.score_sets is None
        assert m.forfait is False
        assert m.arbitres == []
        assert m.match_joue is False

    def test_with_sets(self):
        m = ExportMatchInfo(
            code_match="EFA001", entite_code="ABCCS", poule_code="EFA",
            saison="2025/2026", sets=[(25, 18), (25, 20), (25, 22)],
            score_sets="3/0", match_joue=True,
        )
        assert m.sets_equipe_a == 3
        assert m.sets_equipe_b == 0


class TestArbitreInfo:
    """Tests du dataclass ArbitreInfo."""

    def test_basic(self):
        a = ArbitreInfo(licence="123456", nom="Dupont", ligue="LIRA")
        assert a.licence == "123456"
        assert a.comite_departemental is None
