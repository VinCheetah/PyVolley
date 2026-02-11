#!/usr/bin/env python3
"""Batch test v4 parser."""
import sys
import os
import signal
import glob
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from pyvolley.parsers.v5 import MatchSheetParserV5


class TimeoutErr(Exception):
    pass

def alarm_handler(signum, frame):
    raise TimeoutErr()

parser = MatchSheetParserV5()
base = os.path.join(os.path.dirname(__file__), '..', 'data', 'pdfs')

for season in ['2025-2026', '2024-2025']:
    pattern = os.path.join(base, season, 'ABCCS', '**', '*.pdf')
    pdfs = sorted(glob.glob(pattern, recursive=True))
    ok = fail = to_count = 0
    for p in pdfs:
        signal.signal(signal.SIGALRM, alarm_handler)
        signal.alarm(8)
        try:
            r = parser.parse(Path(p))
            signal.alarm(0)
            if r.success:
                ok += 1
            else:
                fail += 1
                print(f"  FAIL: {Path(p).name}: {r.errors[0][:60] if r.errors else '?'}")
        except TimeoutErr:
            signal.alarm(0)
            to_count += 1
            print(f"  TIMEOUT: {Path(p).name}")
        except Exception as e:
            signal.alarm(0)
            fail += 1
            print(f"  ERROR: {Path(p).name}: {str(e)[:60]}")
    print(f"{season}: {len(pdfs)} PDFs | OK={ok} FAIL={fail} TIMEOUT={to_count}")
