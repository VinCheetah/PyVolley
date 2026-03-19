"""Utilitaires CLI liés aux contrôles de vraisemblance."""

from __future__ import annotations

from collections import Counter
from typing import Any

import typer
from rich.console import Console
from rich.table import Table


def apply_plausibility_core_to_match_db(
    match_db,
    core_match,
    *,
    apply_changes: bool,
) -> list[dict[str, object]]:
    """Synchronise les champs plausibilité entre Match core et MatchDB.

    Retourne la liste des champs modifiés (ou modifiables en dry-run).
    """
    target_values = {
        "date_match": core_match.date,
        "duree_totale": core_match.duree_totale,
        "score_sets": core_match.score_final,
        "sets_equipe_a": int(core_match.sets_a or 0),
        "sets_equipe_b": int(core_match.sets_b or 0),
    }

    changes: list[dict[str, object]] = []
    for field_name, new_value in target_values.items():
        old_value = getattr(match_db, field_name)
        if old_value == new_value:
            continue

        if apply_changes:
            setattr(match_db, field_name, new_value)

        changes.append(
            {
                "field": field_name,
                "old": old_value.isoformat() if hasattr(old_value, "isoformat") else old_value,
                "new": new_value.isoformat() if hasattr(new_value, "isoformat") else new_value,
            }
        )

    return changes


def display_warning_summary(
    console: Console,
    results: list[dict],
    error_details: list[dict],
    total_parsed: int,
) -> None:
    """Affiche un récapitulatif des diagnostics de parsing."""
    from pyvolley.parsers.diagnostics import (
        DiagnosticOrigin, CATEGORY_FOLDERS,
    )

    parsing_count: Counter = Counter()
    data_count: Counter = Counter()

    for r in results:
        for w in r.get('diagnostics', []):
            _, label = CATEGORY_FOLDERS.get(w.category, ("autre", "Autre"))
            if w.origin == DiagnosticOrigin.PARSING:
                parsing_count[label] += 1
            else:
                data_count[label] += 1

    for r in error_details:
        for w in r.get('diagnostics', []):
            _, label = CATEGORY_FOLDERS.get(w.category, ("autre", "Autre"))
            if w.origin == DiagnosticOrigin.PARSING:
                parsing_count[label] += 1
            else:
                data_count[label] += 1
        if r.get('errors'):
            parsing_count["Erreur de parsing"] += len(r['errors'])

    if not parsing_count and not data_count:
        console.print("\n[green]✨ Aucun warning[/green]")
        return

    if parsing_count:
        table = Table(title="⚠️ Problèmes de parsing")
        table.add_column("Catégorie", style="white")
        table.add_column("Occurrences", justify="right", style="red")
        for label, count in parsing_count.most_common():
            table.add_row(label, str(count))
        console.print()
        console.print(table)

    if data_count:
        table = Table(title="📋 Données incomplètes (source PDF)")
        table.add_column("Catégorie", style="white")
        table.add_column("Occurrences", justify="right", style="yellow")
        for label, count in data_count.most_common():
            table.add_row(label, str(count))
        console.print()
        console.print(table)


def build_plausibility_reviewer(console: Console):
    """Construit un callback interactif de validation des corrections."""

    def _approve(issue) -> bool:
        console.print(
            "\n[magenta]Revue correction plausibilité[/magenta] "
            f"({issue.rule_id})"
        )
        console.print(f"- Champ: {issue.field}")
        console.print(f"- Raison: {issue.reason}")
        console.print(f"- Ancienne valeur: {issue.old_value}")
        console.print(f"- Nouvelle valeur: {issue.new_value}")
        return typer.confirm("Valider cette action ?", default=True)

    return _approve


def display_plausibility_summary(console: Console, results: list[dict]) -> None:
    """Affiche un résumé consolidé des actions de vraisemblance."""
    action_counter: Counter[str] = Counter()
    rule_counter: Counter[str] = Counter()

    for item in results:
        report = item.get("plausibility_report")
        if not report:
            continue
        summary = report.get("summary", {})
        by_action = summary.get("by_action", {}) or {}
        by_rule = summary.get("by_rule", {}) or {}
        if isinstance(by_action, dict):
            for action, count in by_action.items():
                action_counter[str(action)] += int(count)
        if isinstance(by_rule, dict):
            for rule_id, count in by_rule.items():
                rule_counter[str(rule_id)] += int(count)

    if not action_counter and not rule_counter:
        return

    table = Table(title="🧪 Contrôles de vraisemblance")
    table.add_column("Action", style="magenta")
    table.add_column("Occurrences", justify="right", style="cyan")
    for action, count in action_counter.most_common():
        table.add_row(action, str(count))
    console.print()
    console.print(table)

    detail_table = Table(title="🧩 Règles de vraisemblance")
    detail_table.add_column("Règle", style="white")
    detail_table.add_column("Occurrences", justify="right", style="yellow")
    for rule_id, count in rule_counter.most_common():
        detail_table.add_row(rule_id, str(count))
    console.print()
    console.print(detail_table)
