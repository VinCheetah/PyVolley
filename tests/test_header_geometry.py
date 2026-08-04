"""
Tests unitaires pour l'extracteur déterministe d'entête (Header Extractor - Section 1).
"""

import glob
from pathlib import Path
import pymupdf
import pytest

from pyvolley.parsers.extractors.header_geometry import extract_header_geometry, HeaderData
from pyvolley.parsers.layout_config import DEFAULT_FFVB_LAYOUT


def test_header_extraction_on_sample_pdfs():
    pdfs = sorted(glob.glob("data/pdfs/**/*.pdf", recursive=True))
    if not pdfs:
        pytest.skip("Aucun fichier PDF disponible dans data/pdfs/")

    sample_pdf = pdfs[0]
    doc = pymupdf.open(sample_pdf)
    page = doc[0]
    raw_words = page.get_text("words")
    words = [
        {
            "x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3],
            "text": w[4], "block": w[5], "line": w[6], "word": w[7]
        }
        for w in raw_words
    ]

    header_data = extract_header_geometry(words, DEFAULT_FFVB_LAYOUT)

    assert isinstance(header_data, HeaderData)
    assert header_data.code_match is not None, "Code match ne doit pas être None"
    assert len(header_data.code_match) >= 3
    assert header_data.date is not None, "Date ne doit pas être None"
    assert header_data.heure is not None, "Heure ne doit pas être None"
    assert header_data.equipe_a_nom != "Équipe A", "Nom de l'équipe A doit être extrait"
    assert header_data.equipe_b_nom != "Équipe B", "Nom de l'équipe B doit être extrait"
    print(f"Header extrait avec succès : {header_data.code_match} | {header_data.date} {header_data.heure} | A: {header_data.equipe_a_nom} vs B: {header_data.equipe_b_nom}")
