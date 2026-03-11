"""Script to fix merged poule codes in the database.

Due to a regex bug in _extract_poule_code() and extract_competition_code(),
poule codes like "CX1", "CX2", "BG5" were incorrectly extracted as "CX", "BG"
etc., causing all matches from different poules to be merged into a single
PouleDB record.

This script:
1. Finds all 2-letter poule codes in youth competitions
2. Groups their matches by the correct 3-char prefix from code_match
3. Creates new PouleDB records for each distinct prefix
4. Reassigns matches to the correct poule
5. Removes the old merged poule record
"""

import re
import sqlite3
import sys
from pathlib import Path


def fix_merged_poules(db_path: str, dry_run: bool = False) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    # Find all 2-char poule codes
    merged_poules = conn.execute("""
        SELECT p.id, p.code, p.competition_id, p.nom, p.tour,
               p.url_calendrier, p.url_classement
        FROM poules p
        WHERE LENGTH(p.code) <= 2
    """).fetchall()

    if not merged_poules:
        print("No merged poules found. Database is clean.")
        conn.close()
        return

    print(f"Found {len(merged_poules)} merged poule(s) to fix.\n")

    total_new = 0
    total_moved = 0

    for poule_id, code, comp_id, nom, tour, url_cal, url_cls in merged_poules:
        # Get all match codes for this poule
        matches = conn.execute("""
            SELECT id, code_match
            FROM matchs
            WHERE poule_id = ?
            ORDER BY code_match
        """, (poule_id,)).fetchall()

        if not matches:
            print(f"  Poule {code} (id={poule_id}): no matches, skipping.")
            continue

        # Group matches by correct 3-char prefix
        groups: dict[str, list[int]] = {}
        for match_id, code_match in matches:
            if code_match and len(code_match) >= 4:
                # Extract correct prefix: everything before the last 3 digits
                m = re.match(r'^(.+?)(\d{3})$', code_match)
                prefix = m.group(1) if m else code_match[:3]
            else:
                prefix = code
            groups.setdefault(prefix, []).append(match_id)

        if len(groups) <= 1 and list(groups.keys())[0] == code:
            print(f"  Poule {code} (id={poule_id}): only 1 group '{code}', no split needed.")
            continue

        print(f"  Poule {code} (id={poule_id}, comp={comp_id}): "
              f"{len(matches)} matches -> {len(groups)} sub-poules")

        if dry_run:
            for prefix, match_ids in sorted(groups.items()):
                print(f"    {prefix}: {len(match_ids)} matches")
            total_new += len(groups)
            total_moved += len(matches)
            continue

        # Check if there are other references to this poule
        # Delete any related data that references the old poule
        for ref_table in ['classements']:
            try:
                conn.execute(f"DELETE FROM {ref_table} WHERE poule_id = ?", (poule_id,))
            except sqlite3.OperationalError:
                pass  # Table doesn't exist

        # Create new poule for each group and reassign matches
        for prefix, match_ids in sorted(groups.items()):
            # Check if a poule with this code already exists for this competition
            existing = conn.execute("""
                SELECT id FROM poules
                WHERE code = ? AND competition_id = ?
            """, (prefix, comp_id)).fetchone()

            if existing:
                new_poule_id = existing[0]
                print(f"    {prefix}: reusing existing poule id={new_poule_id}")
            else:
                conn.execute("""
                    INSERT INTO poules (code, nom, tour, url_calendrier, url_classement, competition_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (prefix, nom, tour, url_cal, url_cls, comp_id))
                new_poule_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                total_new += 1
                print(f"    {prefix}: created poule id={new_poule_id}, "
                      f"{len(match_ids)} matches")

            # Reassign matches
            for mid in match_ids:
                conn.execute(
                    "UPDATE matchs SET poule_id = ? WHERE id = ?",
                    (new_poule_id, mid)
                )
                total_moved += 1

        # Delete the old merged poule
        remaining = conn.execute(
            "SELECT COUNT(*) FROM matchs WHERE poule_id = ?", (poule_id,)
        ).fetchone()[0]
        if remaining == 0:
            conn.execute("DELETE FROM poules WHERE id = ?", (poule_id,))
            print(f"    Deleted old merged poule {code} (id={poule_id})")
        else:
            print(f"    WARNING: {remaining} matches still reference old poule {poule_id}")

    conn.commit()
    conn.close()

    print(f"\nDone! Created {total_new} new poules, moved {total_moved} matches.")


if __name__ == "__main__":
    db_path = str(Path(__file__).parent.parent / "data" / "pyvolley.db")

    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if args:
        db_path = args[0]

    if dry_run:
        print("=== DRY RUN (no changes) ===\n")

    print(f"Database: {db_path}\n")
    fix_merged_poules(db_path, dry_run=dry_run)
