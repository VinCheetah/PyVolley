"""Test parser improvements by parsing real PDFs."""
import os
import sys
import glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pyvolley.parsers.parser import MatchSheetParser

parser = MatchSheetParser()

pdfs = []
base = 'data/pdfs/2025-2026'
orgs = ['ABCCS', 'LIIDF', 'PTIDF75', 'PTIDF92', 'LIFL', 'PTFL59', 'LIRA', 'PTRA69', 'LIAQ', 'ACJEUNES']
for org in orgs:
    org_path = os.path.join(base, org)
    if os.path.isdir(org_path):
        found = sorted(glob.glob(os.path.join(org_path, '**', '*.pdf'), recursive=True))
        if found:
            pdfs.append(found[0])

for pdf_path in pdfs:
    result = parser.parse(pdf_path)
    if result.success and result.match:
        m = result.match
        org_dir = pdf_path.split('/')[-3]
        print(f'=== {org_dir} ===')
        print(f'  Competition: {m.competition}')
        print(f'  Niveau: {m.niveau}')
        print(f'  Organisateur: {m.organisateur}')
        print(f'  Equipe A: nom={m.equipe_a.nom}, club={m.equipe_a.club_nom}, num={m.equipe_a.numero_equipe}')
        print(f'  Equipe B: nom={m.equipe_b.nom}, club={m.equipe_b.club_nom}, num={m.equipe_b.numero_equipe}')
        print(f'  Score: {m.score_final} | Vainqueur: {m.vainqueur_nom}')
        diag_count = len(result.diagnostics)
        warn_count = result.warnings_count
        print(f'  Diagnostics: {diag_count} total, {warn_count} warnings')
        print()
    else:
        print(f'FAILED: {pdf_path}')
        for e in result.errors:
            print(f'  Error: {e[:200]}')
        print()
