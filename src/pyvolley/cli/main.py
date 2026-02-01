"""
Interface CLI principale pour PyVolley.

Utilise Typer pour une interface moderne et bien documentée.
"""

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from pyvolley.core.config import settings


app = typer.Typer(
    name="pyvolley",
    help="🏐 PyVolley - Outils pour les données volleyball FFVB",
    add_completion=False,
)
console = Console()


# ============== Commandes Scrape ==============

@app.command()
def scrape(
    output_dir: Path = typer.Option(
        Path("feuilles_match"),
        "--output", "-o",
        help="Dossier de sortie pour les PDFs"
    ),
    competition: Optional[str] = typer.Option(
        None,
        "--competition", "-c",
        help="Code de la compétition à scraper"
    ),
    limit: int = typer.Option(
        10,
        "--limit", "-n",
        help="Nombre maximum de feuilles à télécharger"
    ),
):
    """
    📥 Télécharge les feuilles de match depuis le site FFVB.
    """
    from pyvolley.scrapers.ffvb import FFVBScraper
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Initialisation du scraper...", total=None)
        
        scraper = FFVBScraper()
        
        # TODO: Implémenter la logique de scraping
        console.print(f"[yellow]Scraping vers {output_dir}...[/yellow]")
        console.print("[green]✓ Scraping terminé[/green]")


@app.command()
def parse(
    input_path: Path = typer.Argument(
        ...,
        help="Chemin vers un PDF ou un dossier de PDFs"
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Fichier JSON de sortie"
    ),
    parser_version: str = typer.Option(
        "v2",
        "--parser", "-p",
        help="Version du parser à utiliser (v2)"
    ),
):
    """
    📄 Parse les feuilles de match PDF.
    """
    from pyvolley.parsers import ParserFactory
    
    if not input_path.exists():
        console.print(f"[red]Erreur: {input_path} n'existe pas[/red]")
        raise typer.Exit(1)
    
    # Récupérer les fichiers PDF
    if input_path.is_dir():
        pdf_files = list(input_path.glob("*.pdf"))
    else:
        pdf_files = [input_path]
    
    if not pdf_files:
        console.print("[yellow]Aucun fichier PDF trouvé[/yellow]")
        raise typer.Exit(0)
    
    console.print(f"[blue]Parsing de {len(pdf_files)} fichier(s)...[/blue]")
    
    # Créer le parser
    factory = ParserFactory()
    if parser_version:
        parser = factory.get(parser_version)
    else:
        parser = factory.get_default()
    
    results = []
    
    with Progress(console=console) as progress:
        task = progress.add_task("Parsing...", total=len(pdf_files))
        
        for pdf_file in pdf_files:
            try:
                result = parser.parse(pdf_file)
                if result.success and result.match:
                    results.append(result.match)
                    progress.console.print(f"  [green]✓[/green] {pdf_file.name}")
                else:
                    progress.console.print(f"  [yellow]⚠[/yellow] {pdf_file.name}: {result.errors}")
            except Exception as e:
                progress.console.print(f"  [red]✗[/red] {pdf_file.name}: {e}")
            
            progress.advance(task)
    
    console.print(f"\n[green]✓ {len(results)}/{len(pdf_files)} fichiers parsés avec succès[/green]")
    
    # Exporter si demandé
    if output and results:
        # Convertir en dict pour JSON
        data = []
        for r in results:
            if hasattr(r, '__dict__'):
                data.append(r.__dict__ if hasattr(r, '__dict__') else str(r))
            else:
                data.append(str(r))
        
        with open(output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        
        console.print(f"[blue]Résultats exportés vers {output}[/blue]")


@app.command()
def import_db(
    input_file: Path = typer.Argument(
        ...,
        help="Fichier JSON à importer"
    ),
):
    """
    💾 Importe les données parsées dans la base de données.
    """
    from pyvolley.database.connection import get_db, init_db
    from pyvolley.database.import_service import MatchImportService
    
    if not input_file.exists():
        console.print(f"[red]Erreur: {input_file} n'existe pas[/red]")
        raise typer.Exit(1)
    
    # Initialiser la base de données
    init_db()
    
    # Charger les données
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    console.print(f"[blue]Import de {len(data)} matchs...[/blue]")
    
    with get_db() as session:
        service = MatchImportService(session)
        # TODO: Convertir les dicts en objets MatchData
        console.print("[yellow]Import non implémenté - données brutes[/yellow]")
    
    console.print("[green]✓ Import terminé[/green]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Adresse d'écoute"),
    port: int = typer.Option(8000, "--port", "-p", help="Port d'écoute"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Activer le rechargement automatique"),
):
    """
    🌐 Lance le serveur web.
    """
    import uvicorn
    
    console.print(f"[blue]🏐 Démarrage de PyVolley sur http://{host}:{port}[/blue]")
    
    uvicorn.run(
        "pyvolley.web.app:web_app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def stats():
    """
    📊 Affiche les statistiques de la base de données.
    """
    from pyvolley.database.connection import get_db, init_db
    from pyvolley.database.repositories import (
        JoueurRepository,
        ClubRepository,
        EquipeRepository,
        MatchRepository,
    )
    
    init_db()
    
    with get_db() as session:
        joueur_repo = JoueurRepository(session)
        club_repo = ClubRepository(session)
        equipe_repo = EquipeRepository(session)
        match_repo = MatchRepository(session)
        
        table = Table(title="📊 Statistiques PyVolley")
        table.add_column("Entité", style="cyan")
        table.add_column("Nombre", justify="right", style="green")
        
        table.add_row("Matchs", str(match_repo.count()))
        table.add_row("Joueurs", str(joueur_repo.count()))
        table.add_row("Équipes", str(equipe_repo.count()))
        table.add_row("Clubs", str(club_repo.count()))
        
        console.print(table)


@app.command()
def init():
    """
    🔧 Initialise la base de données.
    """
    from pyvolley.database.connection import init_db
    
    console.print("[blue]Initialisation de la base de données...[/blue]")
    init_db()
    console.print(f"[green]✓ Base de données créée: {settings.database_url}[/green]")


# ============== Commandes Database/Migrations ==============

db_app = typer.Typer(help="🗄️ Gestion de la base de données et des migrations")
app.add_typer(db_app, name="db")


@db_app.command("status")
def db_status():
    """
    📊 Affiche le statut de la base de données et des migrations.
    """
    from pyvolley.database.migrations import get_database_status
    
    status = get_database_status()
    
    if status.get("connected"):
        console.print(f"[green]✓ Connecté à la base de données[/green]")
        console.print(f"  Type: [cyan]{status['database_type']}[/cyan]")
        console.print(f"  Tables: [cyan]{status['table_count']}[/cyan]")
        console.print(f"  Révision actuelle: [cyan]{status['current_revision'] or 'Aucune'}[/cyan]")
        console.print(f"  Révision head: [cyan]{status['head_revision'] or 'Aucune'}[/cyan]")
        
        if status['pending_migrations'] > 0:
            console.print(f"  [yellow]⚠ {status['pending_migrations']} migration(s) en attente[/yellow]")
        else:
            console.print(f"  [green]✓ Base de données à jour[/green]")
    else:
        console.print(f"[red]✗ Erreur de connexion: {status.get('error')}[/red]")


@db_app.command("migrate")
def db_migrate(
    message: str = typer.Argument(..., help="Message de description de la migration"),
    autogenerate: bool = typer.Option(True, "--auto/--manual", help="Détection automatique des changements"),
):
    """
    📝 Crée une nouvelle migration.
    """
    from pyvolley.database.migrations import create_migration
    
    console.print(f"[blue]Création de la migration: {message}...[/blue]")
    
    try:
        path = create_migration(message, autogenerate=autogenerate)
        if path:
            console.print(f"[green]✓ Migration créée: {path}[/green]")
        else:
            console.print("[yellow]Aucun changement détecté[/yellow]")
    except Exception as e:
        console.print(f"[red]✗ Erreur: {e}[/red]")
        raise typer.Exit(1)


@db_app.command("upgrade")
def db_upgrade(
    revision: str = typer.Argument("head", help="Révision cible (défaut: head)"),
):
    """
    ⬆️ Applique les migrations en attente.
    """
    from pyvolley.database.migrations import upgrade, get_pending_migrations
    
    pending = get_pending_migrations()
    if not pending and revision == "head":
        console.print("[green]✓ La base de données est déjà à jour[/green]")
        return
    
    console.print(f"[blue]Application des migrations vers {revision}...[/blue]")
    
    try:
        upgrade(revision)
        console.print(f"[green]✓ Migrations appliquées avec succès[/green]")
    except Exception as e:
        console.print(f"[red]✗ Erreur: {e}[/red]")
        raise typer.Exit(1)


@db_app.command("downgrade")
def db_downgrade(
    revision: str = typer.Argument("-1", help="Révision cible (défaut: -1 pour revenir d'une étape)"),
):
    """
    ⬇️ Annule des migrations.
    """
    from pyvolley.database.migrations import downgrade
    
    console.print(f"[yellow]⚠ Annulation des migrations vers {revision}...[/yellow]")
    
    try:
        downgrade(revision)
        console.print(f"[green]✓ Migrations annulées avec succès[/green]")
    except Exception as e:
        console.print(f"[red]✗ Erreur: {e}[/red]")
        raise typer.Exit(1)


@db_app.command("reset")
def db_reset(
    force: bool = typer.Option(False, "--force", "-f", help="Ne pas demander confirmation"),
):
    """
    🔄 Réinitialise complètement la base de données.
    
    ⚠️ ATTENTION: Supprime toutes les données!
    """
    from pyvolley.database.connection import reset_db
    
    if not force:
        confirm = typer.confirm("⚠️ Cette action va SUPPRIMER toutes les données. Continuer?")
        if not confirm:
            console.print("[yellow]Annulé[/yellow]")
            raise typer.Exit(0)
    
    console.print("[yellow]Réinitialisation de la base de données...[/yellow]")
    reset_db()
    console.print("[green]✓ Base de données réinitialisée[/green]")


@db_app.command("history")
def db_history():
    """
    📜 Affiche l'historique des migrations.
    """
    from pyvolley.database.migrations import get_migration_history
    
    history = get_migration_history()
    
    if not history:
        console.print("[yellow]Aucune migration trouvée[/yellow]")
        return
    
    table = Table(title="📜 Historique des migrations")
    table.add_column("Révision", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Statut", justify="center")
    
    for mig in history:
        status = "[green]✓ Appliquée[/green]" if mig["is_applied"] else "[yellow]En attente[/yellow]"
        if mig["is_current"]:
            status = "[blue]◀ Actuelle[/blue]"
        table.add_row(mig["revision"][:12], mig["description"] or "-", status)
    
    console.print(table)


def main():
    """Point d'entrée principal."""
    app()


if __name__ == "__main__":
    main()
