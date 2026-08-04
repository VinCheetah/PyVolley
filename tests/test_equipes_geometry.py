"""
Tests unitaires pour l'extraction géométrique des effectifs (Section 2 - Joueurs, Libéros, Officiels).
"""

import glob
import pymupdf
import pytest

from pyvolley.parsers.extractors.equipes_geometry import extract_team_roster_geometry, RosterData
from pyvolley.parsers.layout_config import DEFAULT_FFVB_LAYOUT


def test_section_2_roster_extraction_2025_2026():
    pdfs = sorted(glob.glob("data/pdfs/2025-2026/**/*.pdf", recursive=True))
    if not pdfs:
        pdfs = sorted(glob.glob("data/pdfs/**/*.pdf", recursive=True))
    if not pdfs:
        pytest.skip("Aucun PDF disponible pour les tests")

    sample_pdf = pdfs[0]
    doc = pymupdf.open(sample_pdf)
    page = doc[0]
    raw_words = page.get_text("words")
    words = [
        {"x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3], "text": w[4]}
        for w in raw_words
    ]

    roster_a = extract_team_roster_geometry(words, team_suffix="a", config=DEFAULT_FFVB_LAYOUT)
    roster_b = extract_team_roster_geometry(words, team_suffix="b", config=DEFAULT_FFVB_LAYOUT)

    assert isinstance(roster_a, RosterData)
    assert len(roster_a.joueurs) > 0, "Équipe A doit contenir des joueurs extraits"
    assert len(roster_b.joueurs) > 0, "Équipe B doit contenir des joueurs extraits"

    # Vérification qu'au moins un joueur a un numéro et une licence valide
    j_sample = roster_a.joueurs[0]
    assert j_sample.numero is not None
    assert len(j_sample.licence) >= 6

    print(f"\nÉquipe A : {len(roster_a.joueurs)} joueurs, {len(roster_a.liberos)} libéros, {len(roster_a.officiels)} officiels")
    print(f"Équipe B : {len(roster_b.joueurs)} joueurs, {len(roster_b.liberos)} libéros, {len(roster_b.officiels)} officiels")
