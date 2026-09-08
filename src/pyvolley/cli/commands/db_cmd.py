"""Commandes de gestion et maintenance de la base de données (`pyvolley db` et `pyvolley init`)."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pyvolley.cli.commands.compute_cmd import compute_rollups
from pyvolley.cli.db_explorer import explore_app
from pyvolley.core.config import settings

console = Console()
db_app = typer.Typer(help="🗄️ Gestion de la base de données")
db_app.add_typer(explore_app, name="explore")


@db_app.command("init")
def init_database():
    """🔧 Initialise la base de données."""
    from pyvolley.database.connection import init_db

    console.print("[blue]Initialisation de la base de données...[/blue]")
    init_db()
    console.print(f"[green]✓ Base créée : {settings.database_url}[/green]")


@db_app.command("stats")
def db_stats():
    """📊 Statistiques de contenu de la base (matchs, joueurs, équipes, clubs)."""
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


@db_app.command("status")
def db_status():
    """📊 Statut de la base et des migrations."""
    from pyvolley.database.migrations import get_database_status

    status_info = get_database_status()

    if status_info.get("connected"):
        console.print("[green]✓ Connecté[/green]")
        console.print(f"  Type : [cyan]{status_info['database_type']}[/cyan]")
        console.print(f"  Tables : [cyan]{status_info['table_count']}[/cyan]")
        console.print(
            f"  Révision : [cyan]{status_info['current_revision'] or 'aucune'}[/cyan]"
        )
        if status_info['pending_migrations'] > 0:
            console.print(
                f"  [yellow]⚠ {status_info['pending_migrations']} migration(s) en attente[/yellow]"
            )
        else:
            console.print("  [green]✓ À jour[/green]")
    else:
        console.print(f"[red]✗ Erreur : {status_info.get('error')}[/red]")


@db_app.command("migrate")
def db_migrate(
    message: str = typer.Argument(..., help="Description de la migration."),
    autogenerate: bool = typer.Option(
        True, "--auto/--manual", help="Détection automatique.",
    ),
):
    """📝 Crée une nouvelle migration."""
    from pyvolley.database.migrations import create_migration

    console.print(f"[blue]Migration : {message}...[/blue]")
    try:
        path = create_migration(message, autogenerate=autogenerate)
        if path:
            console.print(f"[green]✓ {path}[/green]")
        else:
            console.print("[yellow]Aucun changement détecté[/yellow]")
    except Exception as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)


@db_app.command("upgrade")
def db_upgrade(
    revision: str = typer.Argument("head", help="Révision cible."),
):
    """⬆️ Applique les migrations en attente."""
    from pyvolley.database.migrations import upgrade, get_pending_migrations

    pending = get_pending_migrations()
    if not pending and revision == "head":
        console.print("[green]✓ Déjà à jour[/green]")
        return

    console.print(f"[blue]Migration vers {revision}...[/blue]")
    try:
        upgrade(revision)
        console.print("[green]✓ Migrations appliquées[/green]")
    except Exception as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)


@db_app.command("downgrade")
def db_downgrade(
    revision: str = typer.Argument("-1", help="Révision cible."),
):
    """⬇️ Annule des migrations."""
    from pyvolley.database.migrations import downgrade

    console.print(f"[yellow]Annulation vers {revision}...[/yellow]")
    try:
        downgrade(revision)
        console.print("[green]✓ Migrations annulées[/green]")
    except Exception as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)


@db_app.command("reset")
def db_reset(
    force: bool = typer.Option(False, "--force", "-f", help="Sans confirmation."),
    full: bool = typer.Option(
        False, "--full", help="Réinitialise aussi les migrations.",
    ),
):
    """
    🔄 Réinitialise la base de données.

    ⚠️ Supprime toutes les données ! ``--full`` réinitialise aussi les migrations.
    """
    from pyvolley.database.connection import reset_db, reset_db_with_migrations

    action = "COMPLÈTEMENT" if full else "complètement"

    if not force:
        confirm = typer.confirm(
            f"⚠️ Supprimer toutes les données {action} ?"
        )
        if not confirm:
            console.print("[yellow]Annulé[/yellow]")
            raise typer.Exit(0)

    try:
        if full:
            reset_db_with_migrations()
        else:
            reset_db()
        console.print("[green]✓ Base réinitialisée[/green]")
    except Exception as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)


@db_app.command("history")
def db_history():
    """📜 Historique des migrations."""
    from pyvolley.database.migrations import get_migration_history

    history = get_migration_history()
    if not history:
        console.print("[yellow]Aucune migration[/yellow]")
        return

    table = Table(title="📜 Historique des migrations")
    table.add_column("Révision", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Statut", justify="center")

    for mig in history:
        if mig["is_current"]:
            st = "[blue]◀ Actuelle[/blue]"
        elif mig["is_applied"]:
            st = "[green]✓[/green]"
        else:
            st = "[yellow]En attente[/yellow]"
        table.add_row(mig["revision"][:12], mig["description"] or "—", st)

    console.print(table)


@db_app.command("import-history")
def db_import_history(
    limit: int = typer.Option(20, "--limit", "-n", help="Nombre d'entrées."),
    operation: Optional[str] = typer.Option(
        None, "--operation", "-o", help="Filtrer par opération.",
    ),
):
    """📋 Historique des opérations d'import."""
    from pyvolley.database.connection import get_db
    from pyvolley.database.models import ImportLogDB
    from sqlalchemy import select

    try:
        with get_db() as session:
            stmt = (
                select(ImportLogDB)
                .order_by(ImportLogDB.started_at.desc())
                .limit(limit)
            )
            if operation:
                stmt = stmt.where(ImportLogDB.operation == operation)

            logs = list(session.scalars(stmt).all())

        if not logs:
            console.print("[yellow]Aucun historique[/yellow]")
            return

        table = Table(title="📋 Historique des imports")
        table.add_column("Date", style="cyan", no_wrap=True)
        table.add_column("Opération", style="white")
        table.add_column("Source", style="dim", max_width=30)
        table.add_column("Importés", justify="right", style="green")
        table.add_column("Doublons", justify="right", style="yellow")
        table.add_column("Erreurs", justify="right", style="red")
        table.add_column("Statut", justify="center")

        status_map = {
            "running": "[yellow]⏳[/yellow]",
            "success": "[green]✓[/green]",
            "partial": "[yellow]⚠[/yellow]",
            "failed": "[red]✗[/red]",
        }

        for log in logs:
            started = (
                log.started_at.strftime("%Y-%m-%d %H:%M")
                if log.started_at else "?"
            )
            table.add_row(
                started,
                log.operation,
                (log.source or "")[-30:] or "—",
                str(log.imported),
                str(log.duplicates),
                str(log.errors),
                status_map.get(log.status, log.status),
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)


@db_app.command("vacuum")
def db_vacuum():
    """Nettoie et compacte la base de donnees SQLite (recupere l'espace libre)."""
    from pyvolley.database.connection import vacuum_db

    console.print("[cyan][...] Demarrage du VACUUM de la base de donnees...[/cyan]")
    res = vacuum_db()
    if res.get("status") == "success":
        console.print(
            Panel(
                f"[bold green]Base compactee avec succes ![/bold green]\n"
                f"Taille avant : [bold]{res['size_before_mb']} Mo[/bold]\n"
                f"Taille apres : [bold]{res['size_after_mb']} Mo[/bold]\n"
                f"Espace libere : [bold cyan]{res['freed_mb']} Mo[/bold cyan]",
                title="Resultat VACUUM",
            )
        )
    else:
        console.print(f"[yellow]Ignore : {res.get('reason')}[/yellow]")


@db_app.command("compute-rollups")
def db_compute_rollups(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Code de la saison (ex: 2025-2026)."
    ),
):
    """Calcule et genere les statistiques agglomerees (joueur-saison, equipes, carrieres)."""
    compute_rollups(saison=saison)
