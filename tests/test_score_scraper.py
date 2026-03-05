"""
Tests pour le scraper de scores FFVB amélioré.

Tests unitaires (mock HTML) + tests d'intégration (requêtes réelles).
"""

import pytest
from bs4 import BeautifulSoup

from pyvolley.scrapers.score_scraper import (
    FFVBScoreScraper,
    OnlineMatchScore,
    _CODE_MATCH_RE,
    _DATE_RE,
    _TIME_RE,
    _SET_SCORE_RE,
    _TOTAL_SCORE_RE,
    _JOURNEE_RE,
)


# ============== Fixtures ==============


def _make_calendar_html(rows_data: list[list[str]]) -> str:
    """Construit un HTML de calendrier FFVB minimal pour les tests.

    Args:
        rows_data: Liste de listes de cellules texte pour chaque <tr>.
    """
    rows_html = []
    for cells in rows_data:
        tds = "".join(f"<td>{c}</td>" for c in cells)
        rows_html.append(f"<tr>{tds}</tr>")
    table = f"<table>{''.join(rows_html)}</table>"
    return f"<html><body>{table}</body></html>"


def _make_flat_calendar(cells: list[str]) -> str:
    """Construit un HTML avec toutes les cellules dans un seul <tr>."""
    tds = "".join(f"<td>{c}</td>" for c in cells)
    return f"<html><body><table><tr>{tds}</tr></table></body></html>"


@pytest.fixture
def scraper():
    """FFVBScoreScraper sans client HTTP (pour tests unitaires)."""
    return FFVBScoreScraper.__new__(FFVBScoreScraper)


# ============== Tests des regex ==============


class TestRegexPatterns:
    """Tests des patterns regex utilisés par le scraper."""

    def test_code_match_valid(self):
        assert _CODE_MATCH_RE.match("EMA001")
        assert _CODE_MATCH_RE.match("PMA012")
        assert _CODE_MATCH_RE.match("3FE003")
        assert _CODE_MATCH_RE.match("EFA001")
        assert _CODE_MATCH_RE.match("RMA0001")  # 4 chiffres

    def test_code_match_invalid(self):
        assert not _CODE_MATCH_RE.match("123")       # pas de lettres
        assert not _CODE_MATCH_RE.match("AB")         # pas assez de chiffres
        assert not _CODE_MATCH_RE.match("TOOLONG0001")  # trop long

    def test_date_valid(self):
        assert _DATE_RE.match("28/09/24")
        assert _DATE_RE.match("01/01/2025")

    def test_date_invalid(self):
        assert not _DATE_RE.match("2024-09-28")
        assert not _DATE_RE.match("9/9/24")

    def test_time_valid(self):
        assert _TIME_RE.match("20:00")
        assert _TIME_RE.match("9:30")

    def test_time_invalid(self):
        assert not _TIME_RE.match("20h00")
        assert not _TIME_RE.match("2024")  # Year, not a time

    def test_set_score(self):
        matches = list(_SET_SCORE_RE.finditer("25:20, 22:25, 25:18"))
        assert len(matches) == 3
        assert (int(matches[0].group(1)), int(matches[0].group(2))) == (25, 20)
        assert (int(matches[1].group(1)), int(matches[1].group(2))) == (22, 25)
        assert (int(matches[2].group(1)), int(matches[2].group(2))) == (25, 18)

    def test_total_score(self):
        m = _TOTAL_SCORE_RE.match("075-047")
        assert m
        assert int(m.group(1)) == 75
        assert int(m.group(2)) == 47

    def test_journee(self):
        m = _JOURNEE_RE.match("Journée 01")
        assert m
        assert m.group(1) == "01"
        m2 = _JOURNEE_RE.match("Journée 12")
        assert m2
        assert m2.group(1) == "12"


# ============== Tests du parsing de segments ==============


class TestParseMatchSegment:
    """Tests de la méthode _parse_match_segment."""

    def test_normal_match_3_0(self, scraper):
        """Parse un match 3-0 avec toutes les infos."""
        cells = [
            "EMA002", "28/09/24", "19:00",
            "VBC CHALON SUR SAONE", "",
            "VINCENNES VOLLEY CLUB",
            "3", "0",
            "25:20, 25:11, 25:16",
            "075-047",
            "SAVOY JEAN-CLAUDE/MATHONNET THIBAUT",
            "",
        ]

        oms, consumed = FFVBScoreScraper._parse_match_segment(
            cells, 0, "ABCCS", "EMA", "2024/2025", "01",
        )

        assert oms is not None
        assert oms.code_match == "EMA002"
        assert oms.equipe_a == "VBC CHALON SUR SAONE"
        assert oms.equipe_b == "VINCENNES VOLLEY CLUB"
        assert oms.sets_a == 3
        assert oms.sets_b == 0
        assert oms.score_sets == "3/0"
        assert oms.set_scores == [(25, 20), (25, 11), (25, 16)]
        assert oms.total_points_a == 75
        assert oms.total_points_b == 47
        assert oms.arbitre_1 == "SAVOY JEAN-CLAUDE"
        assert oms.arbitre_2 == "MATHONNET THIBAUT"
        assert oms.date == "28/09/24"
        assert oms.heure == "19:00"
        assert oms.journee == "01"
        assert oms.match_joue is True
        assert oms.is_forfait is False
        assert oms.is_exempt is False
        assert oms.is_complete is True
        assert oms.vainqueur == "VBC CHALON SUR SAONE"

    def test_match_3_2(self, scraper):
        """Parse un match 3-2 avec 5 sets."""
        cells = [
            "EMA010", "05/10/24", "20:00",
            "VINCENNES VOLLEY CLUB", "",
            "RENNES ETUDIANTS CLUB",
            "3", "2",
            "18:25, 16:25, 25:23, 25:21, 17:15",
            "101-109",
            "GHENIMI NOUR'AMIR/JAKIMOV VERIKA",
            "",
        ]

        oms, _ = FFVBScoreScraper._parse_match_segment(
            cells, 0, "ABCCS", "EMA", "2024/2025", "02",
        )

        assert oms is not None
        assert oms.sets_a == 3
        assert oms.sets_b == 2
        assert len(oms.set_scores) == 5
        assert oms.set_scores[4] == (17, 15)
        assert oms.is_complete is True
        assert oms.vainqueur == "VINCENNES VOLLEY CLUB"

    def test_exempt_match(self, scraper):
        """Parse un match exempt (adversaire = xxxxx)."""
        cells = [
            "EMA001", "28/09/24", "20:00",
            "RENNES ETUDIANTS CLUB", "",
            "xxxxx", "", "", "", "",
        ]

        oms, consumed = FFVBScoreScraper._parse_match_segment(
            cells, 0, "ABCCS", "EMA", "2024/2025", "01",
        )

        assert oms is not None
        assert oms.is_exempt is True
        assert oms.equipe_a == "RENNES ETUDIANTS CLUB"
        assert oms.equipe_b is None
        assert oms.match_joue is False
        assert oms.is_complete is False

    def test_forfait_b(self, scraper):
        """Parse un match forfait côté B (marqueur P)."""
        cells = [
            "EMA017", "26/10/24", "20:00",
            "UNION SPORTIVE DE VILLEJUIF", "",
            "LOISIRS INTER SPORT ST PIERRE",
            "3", "P",
            "25:0, 25:0, 25:0",
            "075-000",
            "BENAZET JEAN-MARIE/FERNANDES LUCY",
            "",
        ]

        oms, _ = FFVBScoreScraper._parse_match_segment(
            cells, 0, "ABCCS", "EMA", "2024/2025", "04",
        )

        assert oms is not None
        assert oms.is_forfait is True
        assert oms.sets_a == 3
        assert oms.sets_b == 0
        assert oms.vainqueur == "UNION SPORTIVE DE VILLEJUIF"
        assert oms.is_complete is True  # Forfait avec score

    def test_forfait_a(self, scraper):
        """Parse un match forfait côté A (marqueur P)."""
        cells = [
            "EMA053", "11/01/25", "19:00",
            "LOISIRS INTER SPORT ST PIERRE", "",
            "AMIENS METROPOLE VOLLEY",
            "P", "3",
            "0:25, 0:25, 0:25",
            "000-075",
            "LAURENT ERIC/WIBAUX EMELYNE",
            "",
        ]

        oms, _ = FFVBScoreScraper._parse_match_segment(
            cells, 0, "ABCCS", "EMA", "2024/2025", "11",
        )

        assert oms is not None
        assert oms.is_forfait is True
        assert oms.sets_a == 0
        assert oms.sets_b == 3
        assert oms.vainqueur == "AMIENS METROPOLE VOLLEY"

    def test_forfait_f(self, scraper):
        """Parse un match forfait avec marqueur F."""
        cells = [
            "EMA072", "15/02/25", "19:00",
            "VBC CHALON SUR SAONE", "",
            "VC MICHELET HALLUIN",
            "3", "F",
            "25:0, 25:0, 25:0",
            "075-000",
            "MERCK PHILIPPE/GARRAUT LORENZO",
            "",
        ]

        oms, _ = FFVBScoreScraper._parse_match_segment(
            cells, 0, "ABCCS", "EMA", "2024/2025", "15",
        )

        assert oms is not None
        assert oms.is_forfait is True
        assert oms.vainqueur == "VBC CHALON SUR SAONE"

    def test_not_played_match(self, scraper):
        """Parse un match non encore joué (cellules vides)."""
        cells = [
            "EMA081", "01/03/25", "20:00",
            "CLUB ABC", "",
            "CLUB DEF",
            "", "", "", "",
        ]

        oms, _ = FFVBScoreScraper._parse_match_segment(
            cells, 0, "ABCCS", "EMA", "2024/2025", "17",
        )

        assert oms is not None
        assert oms.match_joue is False
        assert oms.equipe_a == "CLUB ABC"
        assert oms.equipe_b == "CLUB DEF"
        assert oms.date == "01/03/25"

    def test_false_code_no_date(self, scraper):
        """Rejette les faux codes (pas de date après)."""
        cells = [
            "EMA001", "42", "16", "14", "2",  # Ranking row, not match
        ]

        oms, consumed = FFVBScoreScraper._parse_match_segment(
            cells, 0, "ABCCS", "EMA", "2024/2025", None,
        )

        assert oms is None  # Rejected because "42" is not a date
        assert consumed == 1


# ============== Tests du parsing de page complète ==============


class TestParseCalendarPage:
    """Tests de _parse_calendar_page avec du HTML simulé."""

    def test_multiple_matches(self, scraper):
        """Parse plusieurs matchs consécutifs."""
        cells = [
            # Journée
            "Journée 01",
            # Match 1 (exempt)
            "EMA001", "28/09/24", "20:00",
            "RENNES ETUDIANTS CLUB", "", "xxxxx", "", "", "", "",
            # Match 2 (joué 3-0)
            "EMA002", "28/09/24", "19:00",
            "VBC CHALON", "", "VINCENNES VC",
            "3", "0", "25:20, 25:11, 25:16", "075-047",
            "ARBITRE1/ARBITRE2", "",
            # Journée 2
            "Journée 02",
            # Match 3 (joué 1-3)
            "EMA006", "05/10/24", "20:00",
            "CLUB A", "", "CLUB B",
            "1", "3", "25:21, 17:25, 20:25, 29:31", "091-102",
            "ARB3/ARB4", "",
        ]

        html = _make_flat_calendar(cells)
        soup = BeautifulSoup(html, "html.parser")

        results = scraper._parse_calendar_page(
            soup, "ABCCS", "EMA", "2024/2025",
        )

        assert len(results) == 3

        # Match 1: exempt
        assert results[0].code_match == "EMA001"
        assert results[0].is_exempt is True
        assert results[0].journee == "01"

        # Match 2: joué
        assert results[1].code_match == "EMA002"
        assert results[1].sets_a == 3
        assert results[1].sets_b == 0
        assert results[1].journee == "01"
        assert results[1].vainqueur == "VBC CHALON"

        # Match 3: autre journée
        assert results[2].code_match == "EMA006"
        assert results[2].journee == "02"
        assert results[2].sets_a == 1
        assert results[2].sets_b == 3
        assert results[2].vainqueur == "CLUB B"

    def test_deduplication(self, scraper):
        """Les codes en double ne sont comptés qu'une fois."""
        cells = [
            # Match real
            "EMA002", "28/09/24", "19:00",
            "VBC CHALON", "", "VINCENNES VC",
            "3", "0", "25:20, 25:11, 25:16", "075-047",
            "ARB1/ARB2", "",
            # Faux code dans un classement (pas de date après)
            "EMA002", "39", "16", "13", "3",
        ]

        html = _make_flat_calendar(cells)
        soup = BeautifulSoup(html, "html.parser")

        results = scraper._parse_calendar_page(
            soup, "ABCCS", "EMA", "2024/2025",
        )

        assert len(results) == 1
        assert results[0].code_match == "EMA002"


# ============== Tests du modèle OnlineMatchScore ==============


class TestOnlineMatchScore:
    """Tests des propriétés du modèle OnlineMatchScore."""

    def test_is_complete_normal(self):
        oms = OnlineMatchScore(
            code_match="EMA001", entity_code="ABCCS",
            poule_code="EMA", saison="2024/2025",
            sets_a=3, sets_b=1,
            set_scores=[(25, 20), (22, 25), (25, 18), (25, 15)],
        )
        assert oms.is_complete is True

    def test_is_complete_wrong_count(self):
        oms = OnlineMatchScore(
            code_match="EMA001", entity_code="ABCCS",
            poule_code="EMA", saison="2024/2025",
            sets_a=3, sets_b=1,
            set_scores=[(25, 20), (22, 25)],  # Manque 2 sets
        )
        assert oms.is_complete is False

    def test_is_complete_forfait(self):
        oms = OnlineMatchScore(
            code_match="EMA001", entity_code="ABCCS",
            poule_code="EMA", saison="2024/2025",
            sets_a=3, sets_b=0, is_forfait=True,
        )
        assert oms.is_complete is True

    def test_is_complete_exempt(self):
        oms = OnlineMatchScore(
            code_match="EMA001", entity_code="ABCCS",
            poule_code="EMA", saison="2024/2025",
            is_exempt=True,
        )
        assert oms.is_complete is False

    def test_has_result(self):
        oms = OnlineMatchScore(
            code_match="EMA001", entity_code="ABCCS",
            poule_code="EMA", saison="2024/2025",
            match_joue=True, sets_a=3, sets_b=0,
        )
        assert oms.has_result is True

    def test_arbitres_list(self):
        oms = OnlineMatchScore(
            code_match="EMA001", entity_code="ABCCS",
            poule_code="EMA", saison="2024/2025",
            arbitre_1="DUPONT JEAN", arbitre_2="MARTIN PAUL",
        )
        assert oms.arbitres_list == ["DUPONT JEAN", "MARTIN PAUL"]


# ============== Tests d'intégration (requêtes réelles) ==============


@pytest.mark.integration
class TestScoreScraperIntegration:
    """Tests avec le site FFVB réel.

    Exécuter avec: pytest -m integration tests/test_score_scraper.py
    """

    @pytest.fixture
    def live_scraper(self):
        from pyvolley.scrapers.ffvb import FFVBScraper
        ffvb = FFVBScraper(request_delay=0.5)
        return FFVBScoreScraper(ffvb)

    def test_elite_masc_2024(self, live_scraper):
        """Récupère les scores Elite Masculine 2024/2025."""
        scores = live_scraper.get_scores_for_poule("ABCCS", "EMA", "2024/2025")

        assert len(scores) >= 80  # Au moins 80 matchs
        played = [s for s in scores if s.match_joue]
        complete = [s for s in scores if s.is_complete]

        assert len(played) >= 60
        assert len(complete) >= 60

        # Vérifier qu'on a bien les données enrichies
        sample = next(s for s in scores if s.is_complete and not s.is_forfait)
        assert sample.date is not None
        assert sample.heure is not None
        assert sample.arbitres is not None
        assert sample.total_points_a is not None
        assert sample.total_points_b is not None
        assert sample.journee is not None
        assert len(sample.set_scores) == sample.sets_a + sample.sets_b

    def test_elite_masc_2022(self, live_scraper):
        """Récupère les scores Elite Masculine 2022/2023."""
        scores = live_scraper.get_scores_for_poule("ABCCS", "EMA", "2022/2023")

        assert len(scores) >= 50
        complete = sum(1 for s in scores if s.is_complete)
        assert complete >= 50  # 100% pour une saison terminée

    def test_elite_masc_2020(self, live_scraper):
        """Récupère les scores Elite Masculine 2020/2021."""
        scores = live_scraper.get_scores_for_poule("ABCCS", "EMA", "2020/2021")

        assert len(scores) >= 100
        complete = sum(1 for s in scores if s.is_complete)
        assert complete >= 100

    def test_elite_fem_2024(self, live_scraper):
        """Récupère les scores Elite Féminine 2024/2025."""
        scores = live_scraper.get_scores_for_poule("ABCCS", "EFA", "2024/2025")

        assert len(scores) >= 80
        complete = sum(1 for s in scores if s.is_complete)
        pct = complete / len(scores) * 100
        assert pct >= 80  # Au moins 80% de complétion

    def test_forfait_detection(self, live_scraper):
        """Vérifie que les forfaits sont bien détectés."""
        scores = live_scraper.get_scores_for_poule("ABCCS", "EMA", "2024/2025")

        forfeits = [s for s in scores if s.is_forfait]
        # On sait qu'il y a des forfaits en 2024/2025
        assert len(forfeits) >= 1
        for f in forfeits:
            assert f.vainqueur is not None
            assert f.is_complete is True

    def test_exempt_detection(self, live_scraper):
        """Vérifie que les exemptions sont bien détectées."""
        scores = live_scraper.get_scores_for_poule("ABCCS", "EMA", "2024/2025")

        exempts = [s for s in scores if s.is_exempt]
        assert len(exempts) >= 1
        for e in exempts:
            assert e.equipe_b is None
            assert e.is_complete is False
            assert e.match_joue is False

    def test_summary(self, live_scraper):
        """Vérifie le résumé statistique."""
        summary = live_scraper.get_summary("ABCCS", "EMA", "2024/2025")

        assert summary["total_matches"] >= 80
        assert summary["played"] >= 60
        assert summary["complete_scores"] >= 60
        assert len(summary["teams"]) >= 8
        assert summary["with_arbitres"] >= 60
        assert summary["with_date"] >= 80
        assert summary["completion_pct"] >= 80.0

    def test_get_match_score(self, live_scraper):
        """Vérifie la récupération d'un match spécifique."""
        oms = live_scraper.get_match_score(
            "EMA002", "ABCCS", "EMA", "2024/2025",
        )

        assert oms is not None
        assert oms.code_match == "EMA002"
        assert oms.is_complete is True
        assert oms.equipe_a is not None
        assert oms.equipe_b is not None
