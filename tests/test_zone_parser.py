"""
Tests unitaires pour le ZoneMatchSheetParser et l'extraction par encadrement de sous-zones hiérarchisées.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from pyvolley.parsers.zone_parser import ZoneMatchSheetParser
from pyvolley.parsers.extractors.zone_extractor import extract_hierarchical_data
from pyvolley.parsers.layout_config import DEFAULT_FFVB_LAYOUT


DATA_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "data_sample"


@pytest.fixture
def parser():
    return ZoneMatchSheetParser()


def test_zone_parser_header_extraction(parser):
    """Vérifie l'extraction déterministe du Header sur l'ensemble des PDFs de test."""
    sample_pdfs = sorted(list(DATA_SAMPLE_DIR.glob("*.pdf")))
    assert len(sample_pdfs) > 0, "Aucun PDF de test trouvé dans data/data_sample"

    for pdf_path in sample_pdfs:
        result = parser.parse(pdf_path)
        assert result.success is True, f"Échec du parsing pour {pdf_path.name}"
        match = result.match
        assert match is not None

        # Vérification des sous-champs obligatoires du header
        assert match.code_match != "INCONNU", f"Code match non détecté dans {pdf_path.name}"
        assert match.equipe_a.nom != "Équipe A", f"Nom Équipe A non détecté dans {pdf_path.name}"
        assert match.equipe_b.nom != "Équipe B", f"Nom Équipe B non détecté dans {pdf_path.name}"
        assert match.competition is not None, f"Compétition non détectée dans {pdf_path.name}"


def test_zone_extractor_hierarchical_structure():
    """Vérifie la génération directe de la structure de données imbriquée."""
    import pymupdf

    pdf_path = DATA_SAMPLE_DIR / "3FE011.pdf"
    if not pdf_path.exists():
        pytest.skip("3FE011.pdf absent")

    doc = pymupdf.open(pdf_path)
    words = [
        {"x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3], "text": w[4]}
        for w in doc[0].get_text("words")
    ]
    doc.close()

    h_data = extract_hierarchical_data(words, DEFAULT_FFVB_LAYOUT)
    assert "header" in h_data
    header = h_data["header"]

    assert header.get("match_code") == "3FE011"
    assert header.get("ville") == "CHERBOURG-EN-COTENTIN"
    assert header.get("salle") == "GYMNASE BAGATELLE"
    assert header.get("equipes", {}).get("gauche") == "AS HAINNEVILLAISE VOLLEY"
    assert header.get("equipes", {}).get("droite") == "VOLLEY-BALL GUIGNEN"
