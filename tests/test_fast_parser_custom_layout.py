"""
Tests pour FastMatchSheetParser avec configuration de layout personnalisée.
"""

from pathlib import Path
import pytest

from pyvolley.parsers.fast_parser import FastMatchSheetParser
from pyvolley.parsers.layout_config import ParserLayoutConfig, LayoutRegion


def test_fast_parser_initialization_with_layout():
    custom_cfg = ParserLayoutConfig(name="Unit Test Layout")
    parser = FastMatchSheetParser(layout_config=custom_cfg)

    assert parser.name == "FastMatchSheetParser"
    assert parser._layout_config.name == "Unit Test Layout"


def test_fast_parser_parse_with_custom_layout_override():
    base_dir = Path(__file__).resolve().parent.parent / "data" / "pdfs"
    pdfs = list(base_dir.rglob("*.pdf")) if base_dir.exists() else []

    if not pdfs:
        pytest.skip("Aucun fichier PDF exemple trouvé dans data/pdfs/")

    sample_pdf = pdfs[0]
    parser = FastMatchSheetParser()

    # Parse standard
    result_std = parser.parse(sample_pdf)
    assert result_std.success

    # Parse avec layout personnalisé
    custom_layout = ParserLayoutConfig(name="Custom Adjust")
    custom_layout.bboxes["header"] = LayoutRegion("header", 10.0, 10.0, 835.0, 75.0)

    result_custom = parser.parse(sample_pdf, layout_config=custom_layout)
    assert result_custom.success
    assert result_custom.match is not None
