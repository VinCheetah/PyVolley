"""Commande CLI `pyvolley parse` (analyse autonome de feuilles de match PDF)."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from pyvolley.cli.helpers import make_progress, configure_parser_plausibility
from pyvolley.cli.plausibility_cli import (
    build_plausibility_reviewer,
    display_plausibility_summary,
)

console = Console()


def parse(
    input_path: Path = typer.Argument(
        ..., help="Chemin vers un PDF ou un dossier de PDFs.",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Fichier JSON de sortie.",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n", help="Nombre max de fichiers.",
    ),
    parser_name: str = typer.Option(
        "fast", "--parser", "-p",
        help="Parser à utiliser : 'fast' (FastMatchSheetParser, ~20ms) ou 'legacy' (MatchSheetParser, ~1200ms).",
    ),
    jobs: int = typer.Option(
        min(8, os.cpu_count() or 4), "--jobs", "-j",
        help="Nombre de threads de parsing en parallèle (1 = séquentiel).",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Afficher les détails.",
    ),
    plausibility: bool = typer.Option(
        True, "--plausibility/--no-plausibility",
        help="Activer les contrôles de vraisemblance.",
    ),
    plausibility_policy: str = typer.Option(
        "auto", "--plausibility-policy",
        help="Politique: auto, report-only, strict.",
    ),
    review_fixes: bool = typer.Option(
        False, "--review-fixes",
        help="Valider manuellement les corrections proposées.",
    ),
):
    """
    📄 Analyser des feuilles de match PDF.

    Parse un ou plusieurs fichiers PDF et affiche les résultats.
    Cette commande est indépendante de la base de données — pour importer
    des données en base, utilisez ``pyvolley import``.

    Exemples :

        pyvolley parse match.pdf
        pyvolley parse data/pdfs/ -n 10 --parser legacy
        pyvolley parse match.pdf -o resultat.json -v
        pyvolley parse data/pdfs/ -j 8
    """
    from pyvolley.parsers.factory import ParserFactory

    if not input_path.exists():
        console.print(f"[red]Erreur : {input_path} n'existe pas[/red]")
        raise typer.Exit(1)

    if input_path.is_dir():
        pdf_files = sorted(input_path.glob("**/*.pdf"))
    else:
        pdf_files = [input_path]

    if not pdf_files:
        console.print("[yellow]Aucun fichier PDF trouvé[/yellow]")
        raise typer.Exit(0)

    if limit:
        pdf_files = pdf_files[:limit]

    if review_fixes and jobs > 1:
        console.print("[dim]Mode validation manuelle activé : exécution séquentielle forcée.[/dim]")
        jobs = 1

    parser = ParserFactory.get(parser_name)
    approval_cb = None
    if review_fixes:
        approval_cb = build_plausibility_reviewer(console)
    configure_parser_plausibility(
        parser,
        enabled=plausibility,
        policy=plausibility_policy,
        approval=approval_cb,
    )
    console.print(
        f"[blue]Parser : {parser.name} v{parser.version} — "
        f"{len(pdf_files)} fichier(s)"
        f"{f' ({jobs} threads)' if jobs > 1 and len(pdf_files) > 1 else ''}[/blue]\n"
    )

    results = []
    successful = 0
    failed = 0

    with make_progress(console) as progress:
        task = progress.add_task("Parsing...", total=len(pdf_files))

        def _process_one_result(pdf_file, result, exc=None):
            nonlocal successful, failed
            if exc:
                failed += 1
                progress.update(
                    task, advance=1,
                    description=f"[red]ERR {pdf_file.name[:30]}[/red]",
                )
                return

            if result and result.success and result.match:
                successful += 1
                results.append({
                    'file': str(pdf_file),
                    'match': result.match,
                    'parse_time_ms': result.parse_time_ms,
                    'diagnostics': result.diagnostics,
                    'plausibility_report': (
                        result.plausibility_report.to_dict()
                        if result.plausibility_report else None
                    ),
                })

                if verbose:
                    m = result.match
                    progress.console.print(
                        f"  [green]OK[/green] {pdf_file.name}: "
                        f"{m.equipe_a.nom if m.equipe_a else '?'} vs "
                        f"{m.equipe_b.nom if m.equipe_b else '?'}"
                    )
                    if result.diagnostics:
                        for d in result.diagnostics:
                            progress.console.print(
                                f"      [yellow][!] {d}[/yellow]"
                            )

                progress.update(
                    task, advance=1,
                    description=f"[green]OK {pdf_file.name[:30]}[/green]",
                )
            else:
                failed += 1
                msg = result.errors[0][:60] if result and result.errors else "Erreur"
                if verbose:
                    progress.console.print(
                        f"  [red]ERR[/red] {pdf_file.name}: {msg}"
                    )
                progress.update(
                    task, advance=1,
                    description=f"[red]ERR {pdf_file.name[:30]}[/red]",
                )

        if jobs > 1 and len(pdf_files) > 1:
            def _worker(f):
                try:
                    return f, parser.parse(f), None
                except Exception as exc:
                    return f, None, exc

            with ThreadPoolExecutor(max_workers=jobs) as executor:
                for pdf_file, result, exc in executor.map(_worker, pdf_files, chunksize=8):
                    _process_one_result(pdf_file, result, exc)
        else:
            for pdf_file in pdf_files:
                try:
                    result = parser.parse(pdf_file)
                    _process_one_result(pdf_file, result, None)
                except Exception as exc:
                    _process_one_result(pdf_file, None, exc)

    console.print(Panel(
        f"[green]Succes : {successful}[/green]\n"
        f"[red]Echecs : {failed}[/red]",
        title="Resultat",
    ))

    if results:
        display_plausibility_summary(console, results)

    # Export JSON
    if output and results:
        export_data = [
            {
                'file': r['file'],
                'parse_time_ms': r['parse_time_ms'],
                'plausibility_report': r.get('plausibility_report'),
                'match': (
                    r['match'].model_dump()
                    if hasattr(r['match'], 'model_dump')
                    else r['match'].dict()
                ),
            }
            for r in results
        ]
        with open(output, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
        console.print(f"\n[blue]📁 Résultats : {output}[/blue]")
