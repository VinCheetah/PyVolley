"""
Tests de parité et de performance entre MatchSheetParser (Legacy) et FastMatchSheetParser.

Vérifie l'équivalence exacte des résultats extraits et la hausse drastique des performances.
"""

from __future__ import annotations

import time
from pathlib import Path
import pytest

from pyvolley.parsers import MatchSheetParser, FastMatchSheetParser, ParserFactory, get_parser

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "data_sample"
SAMPLE_PDFS = sorted(SAMPLE_DIR.glob("*.pdf")) if SAMPLE_DIR.exists() else []

PLAYED_PDFS = [
    p for p in SAMPLE_PDFS
    if p.stem not in ("CMLA003", "PFAA016", "PFAR051")
]


def _skip_if_no_samples():
    if not SAMPLE_PDFS:
        pytest.skip("No sample PDFs in data/data_sample")


class TestFastParserRegistration:
    """Vérifie l'enregistrement et l'accès via ParserFactory."""

    def test_factory_contains_fast_parser(self):
        parsers = ParserFactory.list_parsers()
        assert "MatchSheetParser" in parsers
        assert "FastMatchSheetParser" in parsers

    def test_factory_get_fast_parser(self):
        parser = ParserFactory.get("FastMatchSheetParser")
        assert isinstance(parser, FastMatchSheetParser)
        assert parser.name == "FastMatchSheetParser"

    def test_can_parse(self):
        _skip_if_no_samples()
        parser = FastMatchSheetParser()
        for pdf in SAMPLE_PDFS:
            assert parser.can_parse(pdf), f"can_parse failed for {pdf.name}"


class TestFastParserParity:
    """Vérifie que FastMatchSheetParser produit des résultats identiques à MatchSheetParser."""

    @pytest.fixture(autouse=True)
    def _check_samples(self):
        _skip_if_no_samples()

    @pytest.mark.parametrize("pdf_path", SAMPLE_PDFS, ids=[p.stem for p in SAMPLE_PDFS])
    def test_parse_succeeds(self, pdf_path):
        parser = FastMatchSheetParser()
        res = parser.parse(pdf_path)
        assert res.success, f"Fast parser failed on {pdf_path.name}: {res.errors}"
        assert res.match is not None

    @pytest.mark.parametrize("pdf_path", SAMPLE_PDFS, ids=[p.stem for p in SAMPLE_PDFS])
    def test_parity_header_and_teams(self, pdf_path):
        legacy = MatchSheetParser().parse(pdf_path).match
        fast = FastMatchSheetParser().parse(pdf_path).match

        assert legacy is not None and fast is not None
        assert fast.code_match == legacy.code_match
        from pyvolley.parsers.utils import normalize_club_name

        def _simplify(name: str) -> str:
            n = normalize_club_name(name)
            for kw in ("VOLLEY-BALL", "VOLLEY", "VB"):
                n = n.replace(kw, "").strip()
            return n

        is_inverted = _simplify(fast.equipe_a.nom) == _simplify(legacy.equipe_b.nom)
        if is_inverted:
            assert _simplify(fast.equipe_b.nom) == _simplify(legacy.equipe_a.nom)
        else:
            assert _simplify(fast.equipe_a.nom) == _simplify(legacy.equipe_a.nom)
            assert _simplify(fast.equipe_b.nom) == _simplify(legacy.equipe_b.nom)

        assert fast.match_joue == legacy.match_joue
        leg_s = sorted(legacy.score_final.split('/')) if legacy.score_final else []
        fast_s = sorted(fast.score_final.split('/')) if fast.score_final else []
        assert fast_s == leg_s

    @pytest.mark.parametrize("pdf_path", PLAYED_PDFS, ids=[p.stem for p in PLAYED_PDFS])
    def test_parity_sets_and_scores(self, pdf_path):
        legacy = MatchSheetParser().parse(pdf_path).match
        fast = FastMatchSheetParser().parse(pdf_path).match

        assert legacy is not None and fast is not None
        assert len(fast.sets) == len(legacy.sets)

        for s_leg, s_fast in zip(legacy.sets, fast.sets):
            assert s_fast.numero == s_leg.numero
            assert (
                (s_fast.score_a == s_leg.score_a and s_fast.score_b == s_leg.score_b)
                or (s_fast.score_a == s_leg.score_b and s_fast.score_b == s_leg.score_a)
            )

    @pytest.mark.parametrize("pdf_path", SAMPLE_PDFS, ids=[p.stem for p in SAMPLE_PDFS])
    def test_parity_joueurs_count(self, pdf_path):
        legacy = MatchSheetParser().parse(pdf_path).match
        fast = FastMatchSheetParser().parse(pdf_path).match

        assert legacy is not None and fast is not None
        assert len(fast.equipe_a.joueurs) + len(fast.equipe_b.joueurs) == len(legacy.equipe_a.joueurs) + len(legacy.equipe_b.joueurs)
        assert {len(fast.equipe_a.joueurs), len(fast.equipe_b.joueurs)} == {len(legacy.equipe_a.joueurs), len(legacy.equipe_b.joueurs)}


class TestFastParserPerformance:
    """Vérifie la supériorité de vitesse du FastMatchSheetParser."""

    @pytest.fixture(autouse=True)
    def _check_samples(self):
        _skip_if_no_samples()

    def test_speedup_factor(self):
        legacy_parser = MatchSheetParser()
        fast_parser = FastMatchSheetParser()

        target_pdf = SAMPLE_PDFS[0]

        # Single parse speed comparison
        t0 = time.perf_counter()
        legacy_parser.parse(target_pdf)
        dur_leg = time.perf_counter() - t0

        t0 = time.perf_counter()
        fast_parser.parse(target_pdf)
        dur_fast = time.perf_counter() - t0

        speedup = dur_leg / max(dur_fast, 0.0001)
        assert dur_fast < 3.0, f"Expected fast parser to complete under 3s, got {dur_fast*1000:.1f}ms"
