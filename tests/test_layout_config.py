"""
Tests pour la configuration de layout et les presets géométriques (layout_config.py).
"""

import json
from pathlib import Path
import pytest

from pyvolley.parsers.layout_config import (
    LayoutRegion, ParserLayoutConfig, DEFAULT_FFVB_LAYOUT,
)


def test_layout_region_properties():
    region = LayoutRegion(
        name="test_zone",
        x0=10.0, y0=20.0, x1=110.0, y1=220.0,
        description="Zone de test"
    )
    assert region.width == 100.0
    assert region.height == 200.0
    data = region.to_dict()
    assert data["name"] == "test_zone"

    recreated = LayoutRegion.from_dict(data)
    assert recreated.name == region.name
    assert recreated.x0 == region.x0
    assert recreated.y1 == region.y1


def test_default_parser_layout_config():
    config = ParserLayoutConfig()
    assert config.name.startswith("Standard FFVB")
    assert "header/equipes/gauche" in config.bboxes
    assert "equipes/gauche/joueurs" in config.bboxes
    assert "equipes/droite/joueurs" in config.bboxes

    rect = config.get_pymupdf_rect("main")
    assert rect is not None
    assert rect.x0 == 10.0
    assert rect.y0 == 65.0


def test_custom_layout_config_json_roundtrip(tmp_path: Path):
    config = ParserLayoutConfig(name="Custom Test Layout")
    config.bboxes["header/equipes/gauche"].x0 = 115.0
    config.x_split = 680.0

    json_str = config.to_json()
    reloaded = ParserLayoutConfig.from_json(json_str)

    assert reloaded.name == "Custom Test Layout"
    assert reloaded.bboxes["header/equipes/gauche"].x0 == 115.0
    assert reloaded.x_split == 680.0

    preset_path = tmp_path / "test_preset.json"
    config.save_preset(preset_path)
    assert preset_path.exists()

    loaded_preset = ParserLayoutConfig.load_preset(preset_path)
    assert loaded_preset.name == "Custom Test Layout"
    assert loaded_preset.bboxes["header/equipes/gauche"].x0 == 115.0
