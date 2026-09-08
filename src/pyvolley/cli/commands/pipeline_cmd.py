"""Commandes de gestion du cycle de vie du pipeline (`status`, `cleanup`, `serve`, `simulate`, `stats`)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pyvolley.cli.helpers import saisons_to_db_codes
from pyvolley.shared.pdf_storage import extract_match_code_from_pdf_path

console = Console()


def status(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s",
        help="Filtrer par saison (ex: 23/24 ou plage 22/25).",
    ),
    entity: Optional[str] = typer.Option(
        None, "--entity", "-e",
        help="Filtrer par entité (ex: ABCCS).",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Détail par saison.",
    ),
):
    """
    📊 Tableau de bord du pipeline d'import.

    Affiche la répartition des matchs par statut (discovered, downloaded,
    parsed, error) et les statistiques associées.

    Exemples :

        pyvolley status
        pyvolley status -s 23/24
        pyvolley status -v
    """
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import (
        MatchDB, SaisonDB, CompetitionDB, EntiteFFVBDB,
    )
    from sqlalchemy import select, func

    init_db()

    with DatabaseSession() as session:
        base_filter = select(MatchDB)
        filter_label = ""

        if saison:
            try:
                normalized = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)

            saisons_db = session.scalars(
                select(SaisonDB).where(SaisonDB.code.in_(normalized))
            ).all()
            saison_ids = [s.id for s in saisons_db]
            if saison_ids:
                base_filter = base_filter.where(MatchDB.saison_id.in_(saison_ids))
                filter_label += f" | Saison: {saison}"
            else:
                console.print(f"[yellow]Saison '{saison}' non trouvée[/yellow]")
                raise typer.Exit(1)

        if entity:
            entite_db = session.scalars(
                select(EntiteFFVBDB).where(EntiteFFVBDB.code == entity)
            ).first()
            if entite_db:
                comp_ids = [
                    c.id for c in session.scalars(
                        select(CompetitionDB).where(
                            CompetitionDB.entite_id == entite_db.id,
                        )
                    ).all()
                ]
                if comp_ids:
                    base_filter = base_filter.where(
                        MatchDB.competition_id.in_(comp_ids),
                    )
                filter_label += f" | Entité: {entite_db.code}"
            else:
                console.print(f"[yellow]Entité '{entity}' non trouvée[/yellow]")
                raise typer.Exit(1)

        # Comptages par statut
        status_counts: dict[str, int] = {}
        for st in ["discovered", "downloaded", "parsed", "error"]:
            count = session.scalar(
                select(func.count()).select_from(
                    base_filter.where(MatchDB.parsing_status == st).subquery()
                )
            )
            status_counts[st] = count or 0

        total = sum(status_counts.values())
        played = session.scalar(
            select(func.count()).select_from(
                base_filter.where(MatchDB.match_joue == True).subquery()  # noqa: E712
            )
        ) or 0

        # PDFs locaux
        pdf_base = Path("data/pdfs")
        pdf_count = 0
        pdf_total_size = 0
        if pdf_base.exists():
            for f in pdf_base.glob("**/*.pdf"):
                pdf_count += 1
                pdf_total_size += f.stat().st_size

        pdf_display = (
            f"{pdf_total_size / (1024**3):.2f} Go"
            if pdf_total_size > 1024**3
            else f"{pdf_total_size / (1024**2):.0f} Mo"
        )

        # Tableau principal
        table = Table(
            title=f"📊 Statut du pipeline{filter_label}",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Statut", style="bold")
        table.add_column("Nombre", justify="right")
        table.add_column("Proportion", justify="right")

        info = {
            "discovered": ("🔍 Découvert", "cyan"),
            "downloaded": ("📥 Téléchargé", "blue"),
            "parsed": ("✅ Parsé", "green"),
            "error": ("❌ Erreur", "red"),
        }

        for st, count in status_counts.items():
            label, color = info.get(st, (st, "white"))
            pct = f"{count / total * 100:.1f}%" if total > 0 else "—"
            table.add_row(f"[{color}]{label}[/{color}]", str(count), pct)

        table.add_section()
        table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]", "100%")
        table.add_row("[dim]Joués[/dim]", f"[dim]{played}[/dim]", "")
        table.add_row(
            "[dim]PDFs locaux[/dim]",
            f"[dim]{pdf_count}[/dim]",
            f"[dim]{pdf_display}[/dim]",
        )

        console.print(table)

        # Barre de progression
        if total > 0:
            pct = status_counts["parsed"] / total * 100
            console.print(
                f"\n[bold]Progression :[/bold] "
                f"[green]{'█' * int(pct // 2)}[/green]"
                f"[dim]{'░' * (50 - int(pct // 2))}[/dim] "
                f"[bold]{pct:.1f}%[/bold]"
            )

        # Détail par saison (verbose)
        if verbose:
            console.print("\n[bold]Par saison :[/bold]")
            saisons_db = session.scalars(
                select(SaisonDB).order_by(SaisonDB.code)
            ).all()

            detail = Table(show_header=True, header_style="bold")
            detail.add_column("Saison")
            detail.add_column("Total", justify="right")
            detail.add_column("Joués", justify="right")
            detail.add_column("Discovered", justify="right", style="cyan")
            detail.add_column("Downloaded", justify="right", style="blue")
            detail.add_column("Parsed", justify="right", style="green")
            detail.add_column("Error", justify="right", style="red")

            for s in saisons_db:
                counts = {}
                s_total = 0
                for st in ["discovered", "downloaded", "parsed", "error"]:
                    c = session.scalar(
                        select(func.count(MatchDB.id)).where(
                            MatchDB.saison_id == s.id,
                            MatchDB.parsing_status == st,
                        )
                    ) or 0
                    counts[st] = c
                    s_total += c
                if s_total == 0:
                    continue
                s_played = session.scalar(
                    select(func.count(MatchDB.id)).where(
                        MatchDB.saison_id == s.id,
                        MatchDB.match_joue == True,  # noqa: E712
                    )
                ) or 0
                detail.add_row(
                    s.code, str(s_total), str(s_played),
                    str(counts["discovered"]), str(counts["downloaded"]),
                    str(counts["parsed"]), str(counts["error"]),
                )

            console.print(detail)

        # Suggestions
        if status_counts["discovered"] > 0:
            console.print(
                f"\n[yellow]💡 {status_counts['discovered']} matchs à télécharger → "
                f"pyvolley import --only download[/yellow]"
            )
        if status_counts["downloaded"] > 0:
            console.print(
                f"[yellow]💡 {status_counts['downloaded']} matchs à parser → "
                f"pyvolley import --only parse[/yellow]"
            )
        if status_counts["error"] > 0:
            console.print(
                f"[yellow]💡 {status_counts['error']} matchs en erreur → "
                f"pyvolley import --only parse[/yellow]"
            )


def cleanup(
    target: str = typer.Argument(
        "pdfs",
        help="Cible : 'pdfs' (parsés), 'orphans' (sans match en DB), 'all'.",
    ),
    saison: Optional[List[str]] = typer.Option(
        None, "--saison", "-s", help="Filtrer par saison (YY/YY ou plage 22/25).",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Afficher sans supprimer.",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Ne pas demander confirmation.",
    ),
):
    """
    🧹 Nettoyer les fichiers PDF téléchargés.

    Modes :
    - **pdfs** : supprime les PDFs des matchs déjà parsés (données en base).
    - **orphans** : supprime les PDFs sans match correspondant en base.
    - **all** : combine les deux.

    Exemples :

        pyvolley cleanup pdfs --dry-run
        pyvolley cleanup orphans --force
        pyvolley cleanup all -s 23/24
    """
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import MatchDB
    from sqlalchemy import select

    init_db()

    pdf_base = Path("data/pdfs")
    if not pdf_base.exists():
        console.print("[yellow]Aucun dossier PDF trouvé[/yellow]")
        raise typer.Exit(0)

    all_pdfs = list(pdf_base.glob("**/*.pdf"))
    if not all_pdfs:
        console.print("[yellow]Aucun PDF trouvé[/yellow]")
        raise typer.Exit(0)

    # Filtrer par saison
    if saison:
        try:
            normalized = saisons_to_db_codes(saison)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        all_pdfs = [f for f in all_pdfs if any(ns in str(f) for ns in normalized)]

    total_size = sum(f.stat().st_size for f in all_pdfs)
    console.print(
        f"[blue]📁 {len(all_pdfs)} PDFs ({total_size / (1024**3):.2f} Go)[/blue]"
    )

    with DatabaseSession() as session:
        all_codes = set(session.scalars(select(MatchDB.code_match)).all())
        parsed_codes = set(session.scalars(
            select(MatchDB.code_match).where(MatchDB.parsing_status == "parsed")
        ).all())

    to_delete_parsed: list[Path] = []
    to_delete_orphan: list[Path] = []

    for pdf_file in all_pdfs:
        stem = pdf_file.stem
        code = extract_match_code_from_pdf_path(pdf_file)
        is_in_db = code in all_codes or stem in all_codes
        is_parsed = code in parsed_codes or stem in parsed_codes

        if target in ("pdfs", "all") and is_parsed:
            to_delete_parsed.append(pdf_file)
        elif target in ("orphans", "all") and not is_in_db:
            to_delete_orphan.append(pdf_file)

    to_delete = to_delete_parsed + to_delete_orphan
    if not to_delete:
        console.print("[green]Rien à nettoyer[/green]")
        raise typer.Exit(0)

    delete_size = sum(f.stat().st_size for f in to_delete)

    table = Table(title="🧹 Nettoyage prévu")
    table.add_column("Catégorie", style="white")
    table.add_column("Fichiers", justify="right", style="cyan")
    table.add_column("Taille", justify="right", style="yellow")

    if to_delete_parsed:
        sz = sum(f.stat().st_size for f in to_delete_parsed)
        table.add_row("PDFs parsés", str(len(to_delete_parsed)), f"{sz / (1024**2):.1f} Mo")
    if to_delete_orphan:
        sz = sum(f.stat().st_size for f in to_delete_orphan)
        table.add_row("PDFs orphelins", str(len(to_delete_orphan)), f"{sz / (1024**2):.1f} Mo")
    table.add_section()
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{len(to_delete)}[/bold]",
        f"[bold]{delete_size / (1024**2):.1f} Mo[/bold]",
    )
    console.print(table)

    if dry_run:
        console.print("\n[yellow]Mode dry-run : aucun fichier supprimé[/yellow]")
        raise typer.Exit(0)

    if not force:
        confirm = typer.confirm(
            f"Supprimer {len(to_delete)} fichiers ({delete_size / (1024**2):.1f} Mo) ?"
        )
        if not confirm:
            console.print("[yellow]Annulé[/yellow]")
            raise typer.Exit(0)

    deleted = 0
    freed = 0
    for f in to_delete:
        try:
            size = f.stat().st_size
            f.unlink()
            deleted += 1
            freed += size
        except Exception as e:
            console.print(f"  [red]{f}: {e}[/red]")

    # Nettoyer les dossiers vides
    for dirpath in sorted(pdf_base.glob("**"), reverse=True):
        if dirpath.is_dir() and dirpath != pdf_base:
            try:
                if not any(dirpath.iterdir()):
                    dirpath.rmdir()
            except Exception:
                pass

    console.print(Panel(
        f"[green]🗑 {deleted} fichiers supprimés — "
        f"{freed / (1024**2):.1f} Mo libérés[/green]",
        title="Nettoyage terminé",
    ))


def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Adresse d'écoute."),
    port: int = typer.Option(8000, "--port", "-p", help="Port d'écoute."),
    reload: bool = typer.Option(False, "--reload", "-r", help="Rechargement auto."),
):
    """🌐 Lance le serveur web."""
    import uvicorn

    try:
        console.print(f"[blue]🏐 PyVolley sur http://{host}:{port}[/blue]")
    except UnicodeEncodeError:
        console.print(f"[blue]PyVolley sur http://{host}:{port}[/blue]")
    uvicorn.run("pyvolley.web.app:web_app", host=host, port=port, reload=reload)


def simulate(
    source: Path = typer.Argument(
        ..., help="Chemin vers un PDF ou un JSON de match.",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Chemin du HTML généré.",
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Ne pas ouvrir le navigateur.",
    ),
    parser: Optional[str] = typer.Option(
        None, "--parser", "-p", help="Parser à utiliser.",
    ),
):
    """🎬 Simulation interactive d'un match en HTML."""
    if not source.exists():
        console.print(f"[red]Erreur : {source} n'existe pas[/red]")
        raise typer.Exit(1)

    try:
        from pyvolley.simulation import launch_viewer

        console.print(f"[blue]Traitement de {source.name}...[/blue]")
        html_path = launch_viewer(
            source,
            output=str(output) if output else None,
            open_browser=not no_browser,
            parser_name=parser,
        )
        console.print(f"[green]✓ Simulation : {html_path}[/green]")
    except Exception as e:
        console.print(f"[red]Erreur : {e}[/red]")
        raise typer.Exit(1)


def stats():
    """📊 Statistiques de la base de données."""
    from pyvolley.database.connection import get_db, init_db
    from pyvolley.database.repositories import (
        JoueurRepository, ClubRepository, EquipeRepository, MatchRepository,
    )

    init_db()

    with get_db() as session:
        table = Table(title="📊 Statistiques PyVolley")
        table.add_column("Entité", style="cyan")
        table.add_column("Nombre", justify="right", style="green")

        table.add_row("Matchs", str(MatchRepository(session).count()))
        table.add_row("Joueurs", str(JoueurRepository(session).count()))
        table.add_row("Équipes", str(EquipeRepository(session).count()))
        table.add_row("Clubs", str(ClubRepository(session).count()))

        console.print(table)
