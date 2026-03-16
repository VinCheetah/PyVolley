"""Script de synchronisation des logos clubs depuis Volleybox.

Usage:
  /path/to/python scripts/fetch_volleybox_logos.py --limit 100 --min-score 0.35
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from pyvolley.database.connection import DatabaseSession, init_db
from pyvolley.database.models import ClubDB
from pyvolley.scrapers.volleybox import VolleyboxLogoScraper


def main() -> None:
    parser = argparse.ArgumentParser(description="Récupérer les logos clubs depuis Volleybox")
    parser.add_argument("--limit", type=int, default=0, help="Nombre max de clubs (0 = tous)")
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.35,
        help="Score minimal de matching nom↔club Volleybox",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Ne traite que les clubs sans logo_url",
    )
    args = parser.parse_args()

    init_db()
    scraper = VolleyboxLogoScraper()

    with DatabaseSession() as session:
        stmt = select(ClubDB).where(ClubDB.code_ffvb.is_not(None)).order_by(ClubDB.nom.asc())
        if args.only_missing:
            stmt = stmt.where(ClubDB.logo_url.is_(None))

        clubs = session.execute(stmt).scalars().all()
        if args.limit and args.limit > 0:
            clubs = clubs[: args.limit]

        updated = 0
        skipped = 0

        for club in clubs:
            names = [club.nom]
            if club.nom_court:
                names.append(club.nom_court)
            names.extend(alias.alias for alias in (club.aliases or []) if alias.alias)

            candidate = scraper.find_logo_for_club(names)
            if not candidate or candidate.score < args.min_score:
                skipped += 1
                print(f"[SKIP] {club.nom}: aucun logo fiable")
                continue

            club.logo_url = candidate.logo_url
            updated += 1
            print(
                f"[OK] {club.nom} -> {candidate.logo_url} "
                f"(score={candidate.score:.3f}, team={candidate.team_url})"
            )

        session.commit()

    print(f"Terminé: {updated} logos mis à jour, {skipped} ignorés")


if __name__ == "__main__":
    main()
