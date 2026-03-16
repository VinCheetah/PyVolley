"""
Benchmark and robustness tests for the PDF parser.

Uses pytest-benchmark for performance measurement and validates parsing
quality across all sample PDFs in the data/data_sample directory.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from pyvolley.parsers import MatchSheetParser
from pyvolley.parsers.base import ParseResult


# ── Paths ──────────────────────────────────────────────────────────────

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "data_sample"
SAMPLE_PDFS = sorted(SAMPLE_DIR.glob("*.pdf")) if SAMPLE_DIR.exists() else []

# PDFs that are known to contain a played match with detailed scores
PLAYED_PDFS = [
    p for p in SAMPLE_PDFS
    if p.stem not in ("CMLA003", "PFAA016", "PFAR051")
]


def _skip_if_no_samples():
    if not SAMPLE_PDFS:
        pytest.skip("No sample PDFs in data/data_sample")


# =====================================================================
# Benchmark tests (use pytest --benchmark-enable to run benchmarks)
# =====================================================================


class TestParserBenchmark:
    """Performance benchmarks for the parser."""

    @pytest.fixture(autouse=True)
    def _check_samples(self):
        _skip_if_no_samples()

    def test_benchmark_parse_single(self, benchmark):
        """Benchmark parsing a single PDF file."""
        parser = MatchSheetParser()
        pdf = SAMPLE_PDFS[0]
        result = benchmark(parser.parse, pdf)
        assert result.success

    @pytest.mark.parametrize(
        "pdf_path",
        SAMPLE_PDFS,
        ids=[p.stem for p in SAMPLE_PDFS],
    )
    def test_benchmark_parse_each(self, benchmark, pdf_path):
        """Benchmark each sample PDF individually."""
        parser = MatchSheetParser()
        result = benchmark(parser.parse, pdf_path)
        assert result.success

    def test_benchmark_parse_batch(self, benchmark):
        """Benchmark parsing all sample PDFs sequentially."""
        parser = MatchSheetParser()

        def _parse_all():
            return [parser.parse(p) for p in SAMPLE_PDFS]

        results = benchmark(_parse_all)
        assert all(r.success for r in results)


# =====================================================================
# Robustness tests – validate parsing quality
# =====================================================================


class TestParserQuality:
    """Validate parsing quality across all sample PDFs."""

    @pytest.fixture(autouse=True)
    def _check_samples(self):
        _skip_if_no_samples()

    @pytest.mark.parametrize(
        "pdf_path",
        SAMPLE_PDFS,
        ids=[p.stem for p in SAMPLE_PDFS],
    )
    def test_parse_succeeds(self, pdf_path):
        """Every sample PDF must parse successfully."""
        parser = MatchSheetParser()
        result = parser.parse(pdf_path)
        assert result.success, f"Parse failed for {pdf_path.name}: {result.errors}"
        assert result.match is not None

    @pytest.mark.parametrize(
        "pdf_path",
        SAMPLE_PDFS,
        ids=[p.stem for p in SAMPLE_PDFS],
    )
    def test_team_names_not_garbled(self, pdf_path):
        """Team names must not contain timing/set data artifacts."""
        parser = MatchSheetParser()
        result = parser.parse(pdf_path)
        assert result.match is not None
        for label, eq in [("A", result.match.equipe_a), ("B", result.match.equipe_b)]:
            assert eq is not None, f"Equipe {label} is None for {pdf_path.name}"
            name = eq.nom or ""
            # Team names must not contain set/timing artifacts
            assert "Début:" not in name, (
                f"Equipe {label} name contains 'Début:' for {pdf_path.name}: {name!r}"
            )
            assert "Fin:" not in name, (
                f"Equipe {label} name contains 'Fin:' for {pdf_path.name}: {name!r}"
            )
            assert "S E T" not in name, (
                f"Equipe {label} name contains 'S E T' for {pdf_path.name}: {name!r}"
            )
            # Team names should not be excessively long (garbled)
            assert len(name) < 60, (
                f"Equipe {label} name too long for {pdf_path.name}: {name!r}"
            )

    @pytest.mark.parametrize(
        "pdf_path",
        SAMPLE_PDFS,
        ids=[p.stem for p in SAMPLE_PDFS],
    )
    def test_joueurs_extracted(self, pdf_path):
        """Each team should have at least some players."""
        parser = MatchSheetParser()
        result = parser.parse(pdf_path)
        assert result.match is not None
        for label, eq in [("A", result.match.equipe_a), ("B", result.match.equipe_b)]:
            assert eq is not None
            assert len(eq.joueurs) >= 1, (
                f"Equipe {label} has no joueurs for {pdf_path.name}"
            )

    @pytest.mark.parametrize(
        "pdf_path",
        PLAYED_PDFS,
        ids=[p.stem for p in PLAYED_PDFS],
    )
    def test_played_match_has_details(self, pdf_path):
        """Played matches should have set details."""
        parser = MatchSheetParser()
        result = parser.parse(pdf_path)
        assert result.match is not None
        assert result.match.has_details, (
            f"Played match {pdf_path.name} should have details"
        )

    @pytest.mark.parametrize(
        "pdf_path",
        PLAYED_PDFS,
        ids=[p.stem for p in PLAYED_PDFS],
    )
    def test_played_match_has_sets(self, pdf_path):
        """Played matches should have at least 2 sets."""
        parser = MatchSheetParser()
        result = parser.parse(pdf_path)
        assert result.match is not None
        assert len(result.match.sets) >= 2, (
            f"Played match {pdf_path.name} has only {len(result.match.sets)} sets"
        )

    @pytest.mark.parametrize(
        "pdf_path",
        PLAYED_PDFS,
        ids=[p.stem for p in PLAYED_PDFS],
    )
    def test_played_match_has_score(self, pdf_path):
        """Played matches should have a score final."""
        parser = MatchSheetParser()
        result = parser.parse(pdf_path)
        assert result.match is not None
        assert result.match.score_final, (
            f"Played match {pdf_path.name} has no score_final"
        )
        parts = result.match.score_final.split("/")
        assert len(parts) == 2, (
            f"Invalid score format: {result.match.score_final}"
        )
        sa, sb = int(parts[0]), int(parts[1])
        assert sa + sb > 0, (
            f"Score is 0/0 for played match {pdf_path.name}"
        )

    @pytest.mark.parametrize(
        "pdf_path",
        SAMPLE_PDFS,
        ids=[p.stem for p in SAMPLE_PDFS],
    )
    def test_header_fields_extracted(self, pdf_path):
        """Basic header fields should be extracted."""
        parser = MatchSheetParser()
        result = parser.parse(pdf_path)
        assert result.match is not None
        m = result.match
        assert m.competition, f"No competition for {pdf_path.name}"
        assert m.code_match, f"No code_match for {pdf_path.name}"

    @pytest.mark.parametrize(
        "pdf_path",
        SAMPLE_PDFS,
        ids=[p.stem for p in SAMPLE_PDFS],
    )
    def test_no_parsing_errors(self, pdf_path):
        """Parser should not produce errors in diagnostics."""
        parser = MatchSheetParser()
        result = parser.parse(pdf_path)
        parse_errors = [
            d for d in result.diagnostics
            if d.level.value == "error" and d.origin.value == "parsing"
        ]
        assert not parse_errors, (
            f"Parsing errors for {pdf_path.name}: "
            + "; ".join(str(d) for d in parse_errors)
        )

    @pytest.mark.parametrize(
        "pdf_path",
        SAMPLE_PDFS,
        ids=[p.stem for p in SAMPLE_PDFS],
    )
    def test_field_sources_populated(self, pdf_path):
        """ParseResult.field_sources should be populated with source labels."""
        parser = MatchSheetParser()
        result = parser.parse(pdf_path)
        assert result.field_sources, (
            f"No field_sources for {pdf_path.name}"
        )
        # At minimum, we should have team and header sources
        assert "equipe_a" in result.field_sources
        assert "equipe_b" in result.field_sources
        assert "code_match" in result.field_sources
        # All source values should be non-empty strings
        for key, val in result.field_sources.items():
            assert isinstance(val, str) and val, (
                f"Invalid source for {key}: {val!r}"
            )


# =====================================================================
# Unit tests for header-based team name extraction
# =====================================================================


class TestExtractTeamsFromHeader:
    """Tests for the _extract_teams_from_header_line helper."""

    def test_nationale_header(self):
        from pyvolley.parsers.extractors.equipes import _extract_teams_from_header_line
        lines = [
            "3FE - NATIONALE 3 FEMININE POULE E Match: 3FE011 - Jour: 02",
            "Ville: CHERBOURG-EN-COTENTIN Dimanche 05 Octobre 2025 à 14h00",
            "Salle: GYMNASE BAGATELLE SENIOR | FEMININE",
            "Compétitions Nationales SENIORS AS HAINNEVILLAISE VOLLEY VOLLEY-BALL GUIGNEN",
        ]
        result = _extract_teams_from_header_line(lines)
        assert len(result) == 2
        assert "HAINNEVILLAISE" in result[0]
        assert "GUIGNEN" in result[1]

    def test_regionale_header(self):
        from pyvolley.parsers.extractors.equipes import _extract_teams_from_header_line
        lines = [
            "PFAA - CHAMPIONNAT PRE-NATIONAL SENIOR FEMININ : POULE A Match: PFAA016",
            "Ville: CALUIRE Samedi 12 Octobre 2025 à 20h00",
            "Salle: GYMNASE BERTOLA SENIOR | FEMININE",
            "Ligue Auvergne Rhône Alpes AS CALUIRE VB OF ST-CYPRIEN VB",
        ]
        result = _extract_teams_from_header_line(lines)
        assert len(result) == 2

    def test_empty_lines(self):
        from pyvolley.parsers.extractors.equipes import _extract_teams_from_header_line
        result = _extract_teams_from_header_line([])
        assert result == []

    def test_no_org_line(self):
        from pyvolley.parsers.extractors.equipes import _extract_teams_from_header_line
        lines = ["Some random text", "Another line"]
        result = _extract_teams_from_header_line(lines)
        assert result == []


class TestSplitTwoTeams:
    """Tests for the _split_two_teams helper."""

    def test_two_teams(self):
        from pyvolley.parsers.extractors.equipes import _split_two_teams
        result = _split_two_teams("AS HAINNEVILLAISE VOLLEY VOLLEY-BALL GUIGNEN")
        assert len(result) == 2

    def test_single_word(self):
        from pyvolley.parsers.extractors.equipes import _split_two_teams
        result = _split_two_teams("TEAM")
        assert result == ["TEAM"]

    def test_empty(self):
        from pyvolley.parsers.extractors.equipes import _split_two_teams
        result = _split_two_teams("")
        assert result == [""]
