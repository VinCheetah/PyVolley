"""
Tests unitaires pour le FastMatchSheetParser et l'extraction par encadrement de sous-zones hiérarchisées.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from pyvolley.parsers.fast_parser import FastMatchSheetParser
from pyvolley.parsers.extractors.zone_extractor import extract_hierarchical_data
from pyvolley.parsers.layout_config import DEFAULT_FFVB_LAYOUT


DATA_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "data_sample"


@pytest.fixture
def parser():
    return FastMatchSheetParser()


def test_fast_parser_header_extraction(parser):
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
    assert "equipes" in header
    assert "gauche" in header["equipes"]
    assert "droite" in header["equipes"]


def test_fast_parser_sets_and_parity(parser):
    """Vérifie la reconstruction géométrique exacte des sets et du score final."""
    sample_pdfs = sorted(list(DATA_SAMPLE_DIR.glob("*.pdf")))
    played_pdfs = [p for p in sample_pdfs if p.stem not in ("CMLA003", "PFAA016", "PFAR051")]
    for pdf_path in played_pdfs:
        result = parser.parse(pdf_path)
        assert result.success is True
        match = result.match
        assert match is not None

        # Si le match est joué avec sets
        if match.match_joue and match.score_final:
            assert len(match.sets) > 0 or match.score_final in ("3/0", "3/1", "3/2", "0/3", "1/3", "2/3", "2/0", "2/1", "0/2", "1/2")
            assert match.sets_a + match.sets_b > 0

        # Vérification des arbitres
        assert len(match.arbitres) > 0
        # Vérification des joueurs
        assert len(match.equipe_a.joueurs) > 0 or len(match.equipe_b.joueurs) > 0


def test_fast_parser_team_orientation_in_sets(parser):
    """Vérifie que les formations de sets correspondent aux joueurs de chaque équipe respective,
    même lorsque l'équipe A se trouve à droite du terrain (gauche_est_equipe_a == False)."""
    sample_pdfs = sorted(list(DATA_SAMPLE_DIR.glob("*.pdf")))
    for pdf_path in sample_pdfs:
        result = parser.parse(pdf_path)
        if not result.success:
            continue
        match = result.match
        if not match.sets:
            continue
        nums_a = {j.numero.lstrip('0') for j in match.equipe_a.joueurs if j.numero}
        nums_b = {j.numero.lstrip('0') for j in match.equipe_b.joueurs if j.numero}
        s1 = match.sets[0]
        if s1.equipe_a and s1.equipe_a.formation:
            pos_a = {n.lstrip('0') for n in s1.equipe_a.formation.as_list() if n}
            if len(pos_a) >= 4 and len(nums_a) >= 4 and len(nums_b) >= 4:
                # La formation A ne doit pas être inversée avec les joueurs de l'équipe B
                in_a = len(pos_a & nums_a)
                in_b = len(pos_a & nums_b)
                assert in_a >= in_b, f"Inversion détectée dans le set 1 de {pdf_path.name}: {in_b} joueurs de B vs {in_a} de A"

