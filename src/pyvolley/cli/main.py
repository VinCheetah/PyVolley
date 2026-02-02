"""
Interface CLI principale pour PyVolley.

Utilise Typer pour une interface moderne et bien documentée.
"""

import json
import time
from pathlib import Path
from typing import Optional, List
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout

from pyvolley.core.config import settings


app = typer.Typer(
    name="pyvolley",
    help="🏐 PyVolley - Outils pour les données volleyball FFVB",
    add_completion=False,
)
console = Console()


# ============== Commandes Download ==============

@app.command()
def download(
    output_dir: Path = typer.Option(
        Path("data/pdfs"),
        "--output", "-o",
        help="Dossier de sortie pour les PDFs"
    ),
    entity: Optional[List[str]] = typer.Option(
        None,
        "--entity", "-e",
        help="Code de l'entité (ex: ABCCS, LIRA). Répétable: -e ABCCS -e LIRA"
    ),
    poule: Optional[str] = typer.Option(
        None,
        "--poule", "-p",
        help="Code de la poule (ex: EFA, PMA)"
    ),
    saison: Optional[List[str]] = typer.Option(
        None,
        "--saison", "-s",
        help="Saison au format YYYY/YYYY. Répétable: -s 2024/2025 -s 2025/2026"
    ),
    all_entities: bool = typer.Option(
        False,
        "--all",
        help="Télécharge pour TOUTES les entités (ligues, comités, nationales)"
    ),
    entity_type: Optional[str] = typer.Option(
        None,
        "--type", "-t",
        help="Filtrer par type d'entité: nationale, ligue, comite"
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit", "-n",
        help="Nombre maximum de feuilles à télécharger (aucune limite par défaut)"
    ),
    delay: float = typer.Option(
        0.5,
        "--delay", "-d",
        help="Délai entre chaque téléchargement (en secondes)"
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Affiche les matchs sans télécharger"
    ),
    organize: bool = typer.Option(
        True,
        "--organize/--flat",
        help="Organise les fichiers par saison/compétition"
    ),
    report: bool = typer.Option(
        False,
        "--report",
        help="Génère un rapport JSON à la fin du téléchargement"
    ),
):
    """
    📥 Télécharge massivement les feuilles de match depuis le site FFVB.
    
    Exemples:
    
        # Télécharger tous les matchs des Nationales Seniors
        pyvolley download -e ABCCS
        
        # Télécharger plusieurs entités
        pyvolley download -e ABCCS -e LIRA -e LIIFDF
        
        # Télécharger une poule spécifique
        pyvolley download -e ABCCS -p EFA
        
        # Télécharger plusieurs saisons
        pyvolley download -e ABCCS -s 2024/2025 -s 2025/2026
        
        # Télécharger toutes les ligues
        pyvolley download --type ligue -n 100
        
        # Télécharger TOUT (attention: très long!)
        pyvolley download --all --dry-run
        
        # Limiter à 10 téléchargements avec aperçu
        pyvolley download -e ABCCS -p EFA -n 10 --dry-run
    """
    from pyvolley.scrapers.ffvb import FFVBScraper
    
    scraper = FFVBScraper()
    
    # Déterminer les saisons à traiter
    if saison is None or len(saison) == 0:
        saisons = [scraper._get_current_saison()]
    else:
        saisons = list(saison)
    
    # Déterminer les entités à traiter
    entities_to_process = []
    
    if all_entities:
        # Récupérer toutes les entités
        all_ents = scraper.get_entities()
        if entity_type:
            all_ents = [e for e in all_ents if e.type == entity_type.lower()]
        entities_to_process = [e.code for e in all_ents]
    elif entity_type and not entity:
        # Filtrer par type
        all_ents = scraper.get_entities()
        entities_to_process = [e.code for e in all_ents if e.type == entity_type.lower()]
    elif entity:
        entities_to_process = list(entity)
    
    # Afficher la configuration
    entities_display = ', '.join(entities_to_process[:5])
    if len(entities_to_process) > 5:
        entities_display += f"... (+{len(entities_to_process) - 5})"
    
    saisons_display = ', '.join(saisons)
    
    console.print(Panel(
        f"[bold blue]🏐 PyVolley - Téléchargement des feuilles de match[/bold blue]\n\n"
        f"Saison(s): [cyan]{saisons_display}[/cyan]\n"
        f"Entité(s): [cyan]{entities_display or 'Aucune'}[/cyan] ({len(entities_to_process)} au total)\n"
        f"Poule: [cyan]{poule or 'Toutes'}[/cyan]\n"
        f"Sortie: [cyan]{output_dir}[/cyan]\n"
        f"Mode: [cyan]{'Aperçu (dry-run)' if dry_run else 'Téléchargement'}[/cyan]",
        title="Configuration"
    ))
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Si pas d'entité spécifiée, afficher les entités disponibles
    if not entities_to_process:
        console.print("\n[yellow]Aucune entité spécifiée. Voici les entités disponibles:[/yellow]\n")
        _list_entities(scraper)
        console.print("\n[blue]Utilisez -e CODE pour spécifier une entité, --type TYPE pour un type, ou --all pour tout[/blue]")
        raise typer.Exit(0)
    
    # Collecter tous les matchs pour toutes les entités et saisons
    all_matches = []
    total_poules = 0
    
    for current_saison in saisons:
        for current_entity in entities_to_process:
            console.print(f"\n[blue]📂 {current_entity} - Saison {current_saison}[/blue]")
            
            # Récupérer les poules
            with console.status(f"[bold blue]Récupération des poules pour {current_entity}..."):
                poules_list = scraper.get_poules_for_entity(current_entity, current_saison)
            
            if not poules_list:
                console.print(f"  [yellow]Aucune poule trouvée[/yellow]")
                continue
            
            # Filtrer par poule si spécifiée
            if poule:
                poules_list = [p for p in poules_list if p.code == poule]
                if not poules_list:
                    console.print(f"  [yellow]Poule {poule} non trouvée[/yellow]")
                    continue
            
            total_poules += len(poules_list)
            console.print(f"  [green]✓ {len(poules_list)} poule(s) trouvée(s)[/green]")
            
            # Collecter les matchs
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("Récupération des matchs...", total=len(poules_list))
                
                for p in poules_list:
                    matches = list(scraper.get_matches_for_poule(current_entity, p.code, current_saison))
                    for m in matches:
                        m.poule_nom = p.nom
                        m.entity_code = current_entity  # Ajouter le code entité
                        m.saison = current_saison       # Ajouter la saison
                    all_matches.extend(matches)
                    progress.update(task, advance=1, description=f"  {p.code}: {len(matches)} match(s)")
            
            # Si on a atteint la limite globale, on s'arrête
            if limit and len(all_matches) >= limit:
                all_matches = all_matches[:limit]
                console.print(f"[yellow]Limite de {limit} matchs atteinte[/yellow]")
                break
        
        if limit and len(all_matches) >= limit:
            break
    
    console.print(f"\n[green]✓ Total: {len(all_matches)} match(s) à traiter[/green]")
    
    if not all_matches:
        console.print("[yellow]Aucun match trouvé[/yellow]")
        raise typer.Exit(0)
    
    # Mode dry-run: afficher les matchs
    if dry_run:
        # Afficher un résumé par entité
        from collections import Counter
        entity_counts = Counter(getattr(m, 'entity_code', 'unknown') for m in all_matches)
        console.print("\n[bold]Résumé par entité:[/bold]")
        for ent, count in sorted(entity_counts.items()):
            console.print(f"  {ent}: {count} match(s)")
        
        if len(all_matches) <= 50:
            _display_matches_table(all_matches, saisons[0] if len(saisons) == 1 else "Multi")
        else:
            console.print(f"\n[yellow]Trop de matchs pour afficher le tableau ({len(all_matches)})[/yellow]")
        
        console.print(f"\n[yellow]Mode dry-run: aucun fichier téléchargé[/yellow]")
        console.print(f"[blue]Pour télécharger, relancez sans --dry-run[/blue]")
        raise typer.Exit(0)
    
    # Téléchargement
    downloaded = 0
    skipped = 0
    errors = 0
    error_list = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        "[",
        TextColumn("{task.completed}/{task.total}"),
        "]",
        console=console,
    ) as progress:
        task = progress.add_task("Téléchargement...", total=len(all_matches))
        
        for match in all_matches:
            # Récupérer l'entité du match
            match_entity = getattr(match, 'entity_code', entity[0] if entity else 'unknown')
            match_saison = getattr(match, 'saison', saisons[0])
            
            # Construire le chemin de sortie
            if organize:
                # Organiser par saison/entité/poule
                saison_folder = match_saison.replace("/", "-")
                poule_nom_safe = _sanitize_filename(getattr(match, 'poule_nom', match.competition_code or 'autres'))
                match_dir = output_dir / saison_folder / match_entity / poule_nom_safe
            else:
                match_dir = output_dir
            
            match_dir.mkdir(parents=True, exist_ok=True)
            filepath = match_dir / match.filename
            
            # Skip si déjà téléchargé
            if filepath.exists():
                skipped += 1
                progress.update(task, advance=1, description=f"[yellow]Skippé: {match.code}[/yellow]")
                continue
            
            # Télécharger
            try:
                result = scraper.download_match_pdf(match, match_dir)
                
                if result.success:
                    downloaded += 1
                    progress.update(task, advance=1, description=f"[green]✓ {match.code}[/green]")
                else:
                    errors += 1
                    error_list.append({"code": match.code, "error": result.message})
                    progress.update(task, advance=1, description=f"[red]✗ {match.code}: {result.message}[/red]")
                    
            except Exception as e:
                errors += 1
                error_list.append({"code": match.code, "error": str(e)})
                progress.update(task, advance=1, description=f"[red]✗ {match.code}: {e}[/red]")
            
            # Délai pour éviter de surcharger le serveur
            if delay > 0:
                time.sleep(delay)
    
    # Résumé
    console.print("\n" + "=" * 50)
    console.print(Panel(
        f"[green]✓ Téléchargés: {downloaded}[/green]\n"
        f"[yellow]⏭ Skippés (existants): {skipped}[/yellow]\n"
        f"[red]✗ Erreurs: {errors}[/red]\n\n"
        f"📁 Fichiers dans: {output_dir.absolute()}",
        title="Résumé du téléchargement"
    ))
    
    # Générer le rapport si demandé
    if report:
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "saisons": saisons,
            "entities": entities_to_process,
            "poule_filter": poule,
            "downloaded": downloaded,
            "skipped": skipped,
            "errors": errors,
            "error_details": error_list,
            "output_dir": str(output_dir.absolute()),
        }
        report_path = output_dir / f"download_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        console.print(f"\n[blue]📊 Rapport généré: {report_path}[/blue]")


@app.command("list-entities")
def list_entities():
    """
    📋 Liste toutes les entités FFVB disponibles (ligues, comités, nationales).
    """
    from pyvolley.scrapers.ffvb import FFVBScraper
    scraper = FFVBScraper()
    _list_entities(scraper)


@app.command("list-poules")
def list_poules(
    entity: str = typer.Argument(..., help="Code de l'entité (ex: ABCCS, LIIFDF)"),
    saison: Optional[str] = typer.Option(None, "--saison", "-s", help="Saison YYYY/YYYY"),
):
    """
    📋 Liste les poules disponibles pour une entité.
    """
    from pyvolley.scrapers.ffvb import FFVBScraper
    
    scraper = FFVBScraper()
    
    if saison is None:
        saison = scraper._get_current_saison()
    
    with console.status(f"[bold blue]Récupération des poules pour {entity}..."):
        poules = scraper.get_poules_for_entity(entity, saison)
    
    if not poules:
        console.print(f"[yellow]Aucune poule trouvée pour {entity}[/yellow]")
        return
    
    table = Table(title=f"📋 Poules pour {entity} - Saison {saison}")
    table.add_column("Code", style="cyan", no_wrap=True)
    table.add_column("Nom", style="white")
    
    for p in sorted(poules, key=lambda x: x.code):
        table.add_row(p.code, p.nom)
    
    console.print(table)
    console.print(f"\n[green]Total: {len(poules)} poule(s)[/green]")


@app.command("list-matches")
def list_matches(
    entity: str = typer.Argument(..., help="Code de l'entité"),
    poule: str = typer.Argument(..., help="Code de la poule"),
    saison: Optional[str] = typer.Option(None, "--saison", "-s", help="Saison YYYY/YYYY"),
    limit: int = typer.Option(50, "--limit", "-n", help="Nombre max de matchs à afficher"),
):
    """
    📋 Liste les matchs disponibles pour une poule.
    """
    from pyvolley.scrapers.ffvb import FFVBScraper
    
    scraper = FFVBScraper()
    
    if saison is None:
        saison = scraper._get_current_saison()
    
    with console.status(f"[bold blue]Récupération des matchs pour {entity}/{poule}..."):
        matches = list(scraper.get_matches_for_poule(entity, poule, saison))
    
    if not matches:
        console.print(f"[yellow]Aucun match trouvé[/yellow]")
        return
    
    _display_matches_table(matches[:limit], saison)
    
    if len(matches) > limit:
        console.print(f"\n[yellow]... et {len(matches) - limit} autres matchs[/yellow]")
    console.print(f"\n[green]Total: {len(matches)} match(s)[/green]")


def _list_entities(scraper):
    """Affiche les entités disponibles."""
    with console.status("[bold blue]Récupération des entités..."):
        entities = scraper.get_entities()
    
    # Trier par type
    nationales = [e for e in entities if e.type == "nationale"]
    ligues = [e for e in entities if e.type == "ligue"]
    comites = [e for e in entities if e.type == "comite"]
    
    console.print(f"\n[bold]🏆 Nationales ({len(nationales)})[/bold]")
    table_nat = Table(show_header=True)
    table_nat.add_column("Code", style="cyan", width=12)
    table_nat.add_column("Nom", style="white")
    for e in sorted(nationales, key=lambda x: x.code):
        table_nat.add_row(e.code, e.nom)
    console.print(table_nat)
    
    console.print(f"\n[bold]🏛️ Ligues ({len(ligues)})[/bold]")
    table_lig = Table(show_header=True)
    table_lig.add_column("Code", style="cyan", width=12)
    table_lig.add_column("Nom", style="white")
    for e in sorted(ligues, key=lambda x: x.code):
        table_lig.add_row(e.code, e.nom)
    console.print(table_lig)
    
    console.print(f"\n[bold]🏠 Comités ({len(comites)})[/bold]")
    table_com = Table(show_header=True)
    table_com.add_column("Code", style="cyan", width=12)
    table_com.add_column("Nom", style="white")
    for e in sorted(comites, key=lambda x: x.code):
        table_com.add_row(e.code, e.nom)
    console.print(table_com)
    
    console.print(f"\n[green]Total: {len(entities)} entités[/green]")


def _display_matches_table(matches, saison: str):
    """Affiche un tableau de matchs."""
    table = Table(title=f"📋 Matchs - Saison {saison}")
    table.add_column("Code", style="cyan", no_wrap=True)
    table.add_column("Compétition", style="white")
    table.add_column("PDF", style="green")
    
    for m in matches:
        has_pdf = "✓" if m.pdf_url else "✗"
        table.add_row(m.code, m.competition_code or "-", has_pdf)
    
    console.print(table)


def _sanitize_filename(name: str) -> str:
    """Nettoie un nom pour l'utiliser comme nom de fichier/dossier."""
    # Remplacer les caractères problématiques
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Limiter la longueur
    return name[:100].strip()


# ============== Commandes Scrape (Legacy) ==============

@app.command("scrape", hidden=True)
def scrape(
    output_dir: Path = typer.Option(Path("data/pdfs"), "--output", "-o"),
    competition: Optional[str] = typer.Option(None, "--competition", "-c"),
    limit: int = typer.Option(10, "--limit", "-n"),
):
    """
    📥 [Déprécié] Utiliser 'download' à la place.
    """
    console.print("[yellow]⚠ La commande 'scrape' est dépréciée. Utilisez 'download' à la place.[/yellow]")
    console.print("[blue]Exemple: pyvolley download -e ABCCS -p EFA[/blue]")
    raise typer.Exit(0)


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
