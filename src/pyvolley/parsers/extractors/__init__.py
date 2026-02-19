"""
Sous-modules d'extraction pour le parsing des feuilles de match FFVB.

Chaque module est responsable d'extraire un groupe logique de données
depuis les tables, mots et texte brut du PDF.
"""

from pyvolley.parsers.extractors.header import extract_header
from pyvolley.parsers.extractors.equipes import (
    extract_equipes,
    extract_joueurs,
    extract_liberos,
    extract_officiels,
    detect_capitaines,
    recover_joueurs_from_sets,
)
from pyvolley.parsers.extractors.sets import (
    extract_all_sets,
    extract_resultats_table,
    build_sets,
)
from pyvolley.parsers.extractors.resultats import (
    extract_resultat,
    extract_arbitres,
    extract_sanctions,
    extract_remarques,
    extract_demande_non_fondee,
)

__all__ = [
    "extract_header",
    "extract_equipes",
    "extract_joueurs",
    "extract_liberos",
    "extract_officiels",
    "detect_capitaines",
    "recover_joueurs_from_sets",
    "extract_all_sets",
    "extract_resultats_table",
    "build_sets",
    "extract_resultat",
    "extract_arbitres",
    "extract_sanctions",
    "extract_remarques",
    "extract_demande_non_fondee",
]
