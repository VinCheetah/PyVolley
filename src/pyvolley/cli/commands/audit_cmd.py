"""Commandes d'audit et de contrôle de vraisemblance (`plausibility-audit` ou `pyvolley audit`)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pyvolley.cli.helpers import (
    make_progress,
    add_saison_filter,
    add_entity_filter,
)
from pyvolley.cli.plausibility_cli import (
    apply_plausibility_core_to_match_db,
    build_plausibility_reviewer,
)

console = Console()
audit_app = typer.Typer(
    help="🧪 Audits de qualité des données et de vraisemblance",
    no_args_is_help=True,
)


@audit_app.command("plausibility")
def plausibility_audit(
    saison: Optional[List[str]] = typer.Option(
        None, "--saison", "-s",
        help="Restreindre à une saison (23/24) ou une plage (22/25).",
    ),
    entity: Optional[List[str]] = typer.Option(
        None, "--entity", "-e",
        help="Filtrer par code entité (ex: ABCCS). Répétable.",
    ),
    status: Optional[List[str]] = typer.Option(
        None, "--status",
        help="Filtrer par statut parsing (discovered, downloaded, parsed, error). Répétable.",
    ),
    played_only: bool = typer.Option(
        False, "--played-only",
        help="Ne traiter que les matchs joués.",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n",
        help="Nombre max de matchs à analyser.",
    ),
    policy: str = typer.Option(
        "auto", "--policy",
        help="Politique de plausibilité: auto, report-only, strict.",
    ),
    review_fixes: bool = typer.Option(
        False, "--review-fixes",
        help="Valider manuellement les corrections qui demandent revue.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Analyse sans modifier la base.",
    ),
    report_file: Optional[Path] = typer.Option(
        None, "--report-file",
        help="Chemin du rapport JSON de l'audit (par défaut dans data/reports).",
    ),
    include_issues: bool = typer.Option(
        True, "--include-issues/--summary-only",
        help="Inclure le détail des anomalies dans le rapport JSON.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Affichage détaillé par match.",
    ),
):
    """🧪 Exécute les contrôles de vraisemblance a posteriori sur les matchs en base."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.converters import match_db_to_core
    from pyvolley.database.models import ImportLogDB, MatchDB
    from pyvolley.parsers.plausibility import PlausibilityEngine

    normalized_policy = (policy or "auto").strip().lower()
    if normalized_policy not in {"auto", "report-only", "strict"}:
        console.print(
            f"[yellow]Politique '{policy}' invalide, fallback sur 'auto'[/yellow]"
        )
        normalized_policy = "auto"

    if report_file is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = Path("data/reports") / f"plausibility_audit_{stamp}.json"

    init_db()
    reviewer = build_plausibility_reviewer(console) if review_fixes else None
    engine = PlausibilityEngine()

    summary_data = {
        "checked": 0,
        "with_issues": 0,
        "with_changes": 0,
        "total_issues": 0,
        "by_action": {},
        "by_rule": {},
    }
    report_rows: list[dict[str, object]] = []

    with DatabaseSession() as session:
        stmt = (
            select(MatchDB)
            .options(joinedload(MatchDB.sets))
            .options(joinedload(MatchDB.saison))
            .options(joinedload(MatchDB.equipe_a))
            .options(joinedload(MatchDB.equipe_b))
            .order_by(MatchDB.date_match.desc(), MatchDB.id.desc())
        )

        stmt, _ = add_saison_filter(session, stmt, saison)
        stmt = add_entity_filter(session, stmt, entity)

        if status:
            stmt = stmt.where(MatchDB.parsing_status.in_(status))
        if played_only:
            stmt = stmt.where(MatchDB.match_joue == True)  # noqa: E712
        if limit:
            stmt = stmt.limit(limit)

        matches = list(session.scalars(stmt).unique().all())
        if not matches:
            console.print("[yellow]Aucun match trouvé pour cet audit[/yellow]")
            raise typer.Exit(0)

        log_entry = None
        if not dry_run:
            log_entry = ImportLogDB(
                operation="plausibility-audit",
                source=(
                    f"saison={','.join(saison or []) or '*'};"
                    f"entity={','.join(entity or []) or '*'};"
                    f"status={','.join(status or []) or '*'}"
                ),
                total_attempted=len(matches),
            )
            session.add(log_entry)
            session.flush()

        with make_progress(console) as progress:
            task = progress.add_task("Audit plausibilité...", total=len(matches))

            for idx, match_db in enumerate(matches, start=1):
                core_match = match_db_to_core(
                    match_db,
                    participants_a=[],
                    participants_b=[],
                )
                plausibility_report = engine.check(
                    core_match,
                    policy=normalized_policy,
                    approve=reviewer,
                )
                summary = plausibility_report.summary()
                changes = apply_plausibility_core_to_match_db(
                    match_db,
                    core_match,
                    apply_changes=(not dry_run),
                )

                summary_data["checked"] += 1
                total_issues_raw = summary.get("total", 0)
                total_issues = int(total_issues_raw) if isinstance(total_issues_raw, (int, float, str)) else 0
                summary_data["total_issues"] += total_issues
                if total_issues > 0:
                    summary_data["with_issues"] += 1
                if changes:
                    summary_data["with_changes"] += 1

                by_action = summary.get("by_action", {}) or {}
                if isinstance(by_action, dict):
                    for action, count in by_action.items():
                        current = int(summary_data["by_action"].get(action, 0))
                        summary_data["by_action"][action] = current + int(count)

                by_rule = summary.get("by_rule", {}) or {}
                if isinstance(by_rule, dict):
                    for rule_id, count in by_rule.items():
                        current = int(summary_data["by_rule"].get(rule_id, 0))
                        summary_data["by_rule"][rule_id] = current + int(count)

                if changes and not dry_run:
                    match_db.updated_at = datetime.now()

                if total_issues > 0 or changes:
                    row = {
                        "match_id": match_db.id,
                        "code_match": match_db.code_match,
                        "saison": match_db.saison.code if match_db.saison else None,
                        "summary": summary,
                        "changes": changes,
                    }
                    if include_issues:
                        row["issues"] = [
                            issue.to_dict() for issue in plausibility_report.issues
                        ]
                    report_rows.append(row)

                if verbose and (summary.get("total", 0) or changes):
                    progress.console.print(
                        f"  [magenta]#{match_db.id} {match_db.code_match}[/magenta] "
                        f"issues={summary.get('total', 0)} changes={len(changes)}"
                    )

                if not dry_run and idx % 200 == 0:
                    session.commit()

                progress.update(
                    task,
                    advance=1,
                    description=(
                        f"[cyan]Audit plausibilité[/cyan] "
                        f"({summary_data['checked']}/{len(matches)})"
                    ),
                )

        report_payload = {
            "generated_at": datetime.now().isoformat(),
            "config": {
                "policy": normalized_policy,
                "dry_run": dry_run,
                "review_fixes": review_fixes,
                "saison": saison or [],
                "entity": entity or [],
                "status": status or [],
                "played_only": played_only,
                "limit": limit,
            },
            "summary": summary_data,
            "matches": report_rows,
        }

        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if log_entry is not None:
            log_entry.finished_at = datetime.now()
            log_entry.imported = summary_data["with_changes"]
            log_entry.duplicates = max(summary_data["checked"] - summary_data["with_changes"], 0)
            log_entry.errors = 0
            log_entry.updated = summary_data["with_changes"]
            log_entry.summary = json.dumps(
                {
                    "plausibility": {
                        "policy": normalized_policy,
                        "checked": summary_data["checked"],
                        "with_issues": summary_data["with_issues"],
                        "with_changes": summary_data["with_changes"],
                        "total_issues": summary_data["total_issues"],
                        "by_action": summary_data["by_action"],
                        "by_rule": summary_data["by_rule"],
                        "dry_run": dry_run,
                    },
                    "report_file": str(report_file),
                },
                ensure_ascii=False,
            )
            log_entry.status = "success"
            session.commit()

    console.print(Panel(
        f"[cyan]Matchs analysés : {summary_data['checked']}[/cyan]\n"
        f"[yellow]Matchs avec anomalies : {summary_data['with_issues']}[/yellow]\n"
        f"[magenta]{'Matchs modifiables' if dry_run else 'Matchs modifiés'} : "
        f"{summary_data['with_changes']}[/magenta]\n"
        f"[green]Rapport : {report_file}[/green]",
        title="Audit de plausibilité",
    ))

    summary_table = Table(title="🧪 Actions de plausibilité")
    summary_table.add_column("Action", style="magenta")
    summary_table.add_column("Occurrences", justify="right", style="cyan")
    for action, count in sorted(
        summary_data["by_action"].items(), key=lambda i: i[1], reverse=True,
    ):
        summary_table.add_row(action, str(count))
    if summary_data["by_action"]:
        console.print(summary_table)

    rules_table = Table(title="🧩 Règles touchées")
    rules_table.add_column("Règle", style="white")
    rules_table.add_column("Occurrences", justify="right", style="yellow")
    for rule_id, count in sorted(
        summary_data["by_rule"].items(), key=lambda i: i[1], reverse=True,
    ):
        rules_table.add_row(rule_id, str(count))
    if summary_data["by_rule"]:
        console.print(rules_table)
