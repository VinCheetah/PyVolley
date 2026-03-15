"""Tests de régression pour l'association match ↔ PDF dans le CLI."""

from types import SimpleNamespace

import pytest

from pyvolley.cli.helpers import (
    build_pdf_index,
    find_pdf_for_match,
    expand_saison_inputs,
    format_saison_short,
    saisons_to_db_codes,
)
from pyvolley.shared.pdf_storage import build_pdf_storage_path


def _make_match(code_match: str, saison_code: str | None, source_pdf: str | None = None):
    saison = SimpleNamespace(code=saison_code) if saison_code else None
    return SimpleNamespace(code_match=code_match, source_pdf=source_pdf, saison=saison)


def test_find_pdf_for_match_prefers_same_season(tmp_path):
    pdf_base = tmp_path / "pdfs"
    season_a = pdf_base / "2023-2024"
    season_b = pdf_base / "2024-2025"
    season_a.mkdir(parents=True)
    season_b.mkdir(parents=True)

    pdf_a = season_a / "EMA001.pdf"
    pdf_b = season_b / "EMA001.pdf"
    pdf_a.write_bytes(b"%PDF-1.4\n")
    pdf_b.write_bytes(b"%PDF-1.4\n")

    index = build_pdf_index(pdf_base)
    match = _make_match("EMA001", "2024-2025")

    found = find_pdf_for_match(match, pdf_base, index)

    assert found == pdf_b


def test_find_pdf_for_match_uses_legacy_unscoped_fallback(tmp_path):
    pdf_base = tmp_path / "pdfs"
    pdf_base.mkdir(parents=True)

    legacy_pdf = pdf_base / "LIRA_EMA002.pdf"
    legacy_pdf.write_bytes(b"%PDF-1.4\n")

    index = build_pdf_index(pdf_base)
    match = _make_match("EMA002", "2025-2026")

    found = find_pdf_for_match(match, pdf_base, index)

    assert found == legacy_pdf


def test_find_pdf_for_match_supports_structured_storage_format(tmp_path):
    pdf_base = tmp_path / "pdfs"
    structured_pdf = build_pdf_storage_path(
        pdf_base,
        saison_code="2025-2026",
        entite_code="LIRA",
        poule_code="EMA",
        match_code="EMA007",
        journee="12",
        unique_hint=123,
    )
    structured_pdf.parent.mkdir(parents=True, exist_ok=True)
    structured_pdf.write_bytes(b"%PDF-1.4\n")

    index = build_pdf_index(pdf_base)
    match = _make_match("EMA007", "2025-2026")

    found = find_pdf_for_match(match, pdf_base, index)

    assert found == structured_pdf


def test_expand_saison_inputs_single_short_format():
    assert expand_saison_inputs(["23/24"]) == ["2023/2024"]


def test_expand_saison_inputs_range_short_format():
    assert expand_saison_inputs(["22/25"]) == [
        "2022/2023",
        "2023/2024",
        "2024/2025",
    ]


def test_saisons_to_db_codes_from_range():
    assert saisons_to_db_codes(["22/25"]) == [
        "2022-2023",
        "2023-2024",
        "2024-2025",
    ]


def test_format_saison_short_accepts_legacy_long_code():
    assert format_saison_short("2024-2025") == "24/25"


def test_expand_saison_inputs_rejects_invalid_token():
    with pytest.raises(ValueError):
        expand_saison_inputs(["2024"])
