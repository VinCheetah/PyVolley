"""Sous-commandes CLI `pyvolley list` (consultation FFVB)."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from pyvolley.cli.helpers import resolve_saisons, display_entities


list_app = typer.Typer(help="📋 Consulter les données FFVB disponibles")
console = Console()


@list_app.command("entities")
def list_entities():
    """📋 Liste toutes les entités FFVB (ligues, comités, nationales)."""
    from pyvolley.scrapers.ffvb import FFVBScraper

    display_entities(FFVBScraper(), console)


@list_app.command("poules")
def list_poules(
    entity: str = typer.Argument(
        ..., help="Code de l'entité (ex: ABCCS, LIIFDF).",
    ),
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Saison YY/YY (ex: 23/24).",
    ),
):
    """📋 Liste les poules disponibles pour une entité."""
    from pyvolley.scrapers.ffvb import FFVBScraper

    scraper = FFVBScraper()

    try:
        saison_values = resolve_saisons(scraper, [saison] if saison else None)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if len(saison_values) != 1:
        console.print("[red]La commande 'list poules' accepte une seule saison.[/red]")
        raise typer.Exit(1)
    saison_resolved = saison_values[0]

    with console.status(f"[bold blue]Récupération des poules pour {entity}..."):
        poules = scraper.discover_poules(entity, saison_resolved)

    if not poules:
        console.print(f"[yellow]Aucune poule trouvée pour {entity}[/yellow]")
        return

    table = Table(title=f"📋 Poules — {entity} — {saison_resolved}")
    table.add_column("Code", style="cyan", no_wrap=True)
    table.add_column("Nom", style="white")

    for p in sorted(poules, key=lambda x: x.code):
        table.add_row(p.code, p.nom)

    console.print(table)
    console.print(f"\n[green]{len(poules)} poule(s)[/green]")


@list_app.command("matches")
def list_matches(
    entity: str = typer.Argument(..., help="Code de l'entité."),
    poule: Optional[str] = typer.Option(
        None, "--poule", "-p", help="Filtrer par poule.",
    ),
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Saison YY/YY (ex: 23/24).",
    ),
    limit: int = typer.Option(
        50, "--limit", "-n", help="Nombre max à afficher.",
    ),
):
    """📋 Liste les matchs disponibles pour une entité."""
    from pyvolley.scrapers.ffvb import FFVBScraper

    scraper = FFVBScraper()
    try:
        saison_values = resolve_saisons(scraper, [saison] if saison else None)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if len(saison_values) != 1:
        console.print("[red]La commande 'list matches' accepte une seule saison.[/red]")
        raise typer.Exit(1)
    saison_resolved = saison_values[0]

    with console.status(f"[bold blue]Récupération des matchs pour {entity}..."):
        export_matches = scraper.scrape_entity(entity, saison_resolved, poule=poule)

    if not export_matches:
        console.print("[yellow]Aucun match trouvé[/yellow]")
        return

    table = Table(title=f"📋 Matchs — {entity} — {saison_resolved}")
    table.add_column("Code", style="cyan", no_wrap=True)
    table.add_column("Poule", style="white")
    table.add_column("Date", style="dim")
    table.add_column("Équipe A", style="white")
    table.add_column("Équipe B", style="white")
    table.add_column("Score", style="green")
    table.add_column("PDF", style="green")

    for m in export_matches[:limit]:
        date_str = m.date_match.strftime("%d/%m/%Y") if m.date_match else "—"
        score = m.score_sets or "—"
        has_pdf = "✓" if m.feuille_match_url else "✗"
        table.add_row(
            m.code_match, m.poule_code or "—", date_str,
            m.equipe_a_nom or "—", m.equipe_b_nom or "—", score, has_pdf,
        )

    console.print(table)

    if len(export_matches) > limit:
        console.print(
            f"\n[dim]... et {len(export_matches) - limit} autres matchs[/dim]"
        )
    console.print(f"\n[green]{len(export_matches)} match(s)[/green]")
