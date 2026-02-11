"""Batch test v4 parser across seasons."""
import sys
sys.path.insert(0, 'src')
import glob
import signal
from pathlib import Path
from pyvolley.parsers.v5 import MatchSheetParserV5


class TimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("Timeout")


parser = MatchSheetParserV5()

for season in ['2025-2026', '2024-2025', '2023-2024']:
    pdfs = sorted(glob.glob(f'data/pdfs/{season}/ABCCS/**/*.pdf', recursive=True))
    if not pdfs:
        continue
    ok, fail, warns, timeouts = 0, 0, 0, 0
    issues = []
    for p in pdfs:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(10)  # 10 second timeout per PDF
        try:
            r = parser.parse(Path(p))
            signal.alarm(0)
            if r.success:
                ok += 1
                warns += len(r.warnings)
            else:
                fail += 1
                issues.append(f"  {Path(p).name}: {r.errors[0][:80]}")
        except TimeoutError:
            timeouts += 1
            issues.append(f"  {Path(p).name}: TIMEOUT")
        except Exception as e:
            fail += 1
            issues.append(f"  {Path(p).name}: {str(e)[:80]}")
    print(f"{season}: {len(pdfs)} PDFs | OK={ok} FAIL={fail} TIMEOUT={timeouts} Warnings={warns}")
    for i in issues[:5]:
        print(i)
