"""Script de synchronisation des logos clubs depuis Volleybox.

Usage:
  /path/to/python scripts/fetch_volleybox_logos.py --limit 100 --min-score 0.35
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

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
    parser.add_argument(
        "--top-candidates",
        type=int,
        default=3,
        help="Nombre de candidats Volleybox évalués par club",
    )
    parser.add_argument(
        "--report-file",
        type=str,
        default="",
        help="Chemin du rapport JSON (par défaut: ignore_data/volleybox_logo_associations_*.json)",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Demande une confirmation interactive pour chaque association proposée",
    )
    parser.add_argument(
        "--max-fr-pages",
        type=int,
        default=40,
        help="Nombre max de pages clubs FR à explorer sur Volleybox",
    )
    args = parser.parse_args()

    init_db()
    scraper = VolleyboxLogoScraper(max_fr_pages=max(1, args.max_fr_pages))

    with DatabaseSession() as session:
        stmt = select(ClubDB).where(ClubDB.code_ffvb.is_not(None)).order_by(ClubDB.nom.asc())
        if args.only_missing:
            stmt = stmt.where(ClubDB.logo_url.is_(None))

        clubs = session.execute(stmt).scalars().all()
        if args.limit and args.limit > 0:
            clubs = clubs[: args.limit]

        updated = 0
        skipped = 0
        associations: list[dict[str, object]] = []

        for club in clubs:
            names = [club.nom]
            if club.nom_court:
                names.append(club.nom_court)
            names.extend(alias.alias for alias in (club.aliases or []) if alias.alias)

            ordered_names = [name.strip() for name in names if name and name.strip()]
            unique_names: list[str] = []
            seen_names: set[str] = set()
            for name in ordered_names:
                key = name.lower()
                if key in seen_names:
                    continue
                seen_names.add(key)
                unique_names.append(name)

            candidates = scraper.find_team_candidates(
                unique_names,
                target_city=club.ville,
                limit=max(1, args.top_candidates),
                min_score=max(0.15, args.min_score * 0.5),
            )

            selected = None
            for candidate in candidates:
                if candidate.score < args.min_score:
                    continue
                candidate.logo_url = scraper.extract_logo_url(candidate.team_url)
                if candidate.logo_url:
                    selected = candidate
                    break

            report_entry: dict[str, object] = {
                "club_id": club.id,
                "club_nom": club.nom,
                "club_nom_court": club.nom_court,
                "queries": unique_names,
                "status": "skipped",
                "selected": None,
                "candidates": [
                    {
                        "team_url": candidate.team_url,
                        "slug": candidate.slug,
                        "score": round(candidate.score, 4),
                        "matched_name": candidate.matched_name,
                        "matched_city": candidate.matched_city,
                        "city_score": round(candidate.city_score, 4),
                    }
                    for candidate in candidates
                ],
            }

            if not selected:
                skipped += 1
                print(f"[SKIP] {club.nom}: aucun logo fiable")
                associations.append(report_entry)
                continue

            print(
                f"[PROPOSE] {club.nom} => {selected.team_url} "
                f"(score={selected.score:.3f}, via={selected.matched_name}, city={selected.matched_city}, city_score={selected.city_score:.3f}, logo={selected.logo_url})"
            )
            alternatives = [
                candidate
                for candidate in candidates
                if candidate.team_url != selected.team_url
            ][:3]
            if alternatives:
                print("         Alternatives:")
                for alt in alternatives:
                    print(
                        f"         - {alt.team_url} "
                        f"(score={alt.score:.3f}, via={alt.matched_name}, city={alt.matched_city}, city_score={alt.city_score:.3f})"
                    )

            if args.review:
                answer = input("         Confirmer cette association ? [Y/n] ").strip().lower()
                if answer in {"n", "no", "non"}:
                    skipped += 1
                    report_entry["status"] = "rejected_by_review"
                    report_entry["selected"] = {
                        "team_url": selected.team_url,
                        "slug": selected.slug,
                        "score": round(selected.score, 4),
                        "matched_name": selected.matched_name,
                        "matched_city": selected.matched_city,
                        "city_score": round(selected.city_score, 4),
                        "logo_url": selected.logo_url,
                    }
                    associations.append(report_entry)
                    print(f"[SKIP] {club.nom}: association rejetée en revue")
                    continue

            club.logo_url = selected.logo_url
            updated += 1
            report_entry["status"] = "matched"
            report_entry["selected"] = {
                "team_url": selected.team_url,
                "slug": selected.slug,
                "score": round(selected.score, 4),
                "matched_name": selected.matched_name,
                "matched_city": selected.matched_city,
                "city_score": round(selected.city_score, 4),
                "logo_url": selected.logo_url,
            }
            associations.append(report_entry)
            print(
                f"[OK] {club.nom} -> {selected.logo_url} "
                f"(score={selected.score:.3f}, team={selected.team_url}, via={selected.matched_name})"
            )

        session.commit()

    report_path = Path(args.report_file) if args.report_file else Path(
        f"ignore_data/volleybox_logo_associations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_payload = {
        "generated_at": datetime.now().isoformat(),
        "min_score": args.min_score,
        "top_candidates": args.top_candidates,
        "only_missing": args.only_missing,
        "updated": updated,
        "skipped": skipped,
        "associations": associations,
    }
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Terminé: {updated} logos mis à jour, {skipped} ignorés")
    print(f"Rapport associations: {report_path}")

    matched_preview = [entry for entry in associations if entry.get("status") == "matched"][:10]
    if matched_preview:
        print("\nRécapitulatif (10 premiers matchs):")
        for entry in matched_preview:
            selected_data = entry.get("selected")
            selected = selected_data if isinstance(selected_data, dict) else {}
            print(
                f"- {entry.get('club_nom')} => {selected.get('team_url')} "
                f"(score={selected.get('score')}, logo={selected.get('logo_url')})"
            )


if __name__ == "__main__":
    main()
