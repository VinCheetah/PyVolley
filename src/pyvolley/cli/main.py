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
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
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
        help="Chemin vers un PDF, un dossier, ou 'data/pdfs' pour tout parser"
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Fichier JSON de sortie pour les résultats"
    ),
    parser_version: str = typer.Option(
        "v5",
        "--parser", "-p",
        help="Version du parser (v2, v3, v4, v5)"
    ),
    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive", "-r",
        help="Parcourir les sous-dossiers récursivement"
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit", "-n",
        help="Nombre maximum de fichiers à parser"
    ),
    skip_parsed: bool = typer.Option(
        True,
        "--skip-parsed/--force",
        help="Ignorer les fichiers déjà parsés (vérifiés par hash ou cache)"
    ),
    save_db: bool = typer.Option(
        False,
        "--save-db", "-d",
        help="Enregistrer les résultats directement dans la base de données"
    ),
    report: bool = typer.Option(
        False,
        "--report",
        help="Générer un rapport détaillé"
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Afficher ce qui serait fait sans parser"
    ),
    saison: Optional[str] = typer.Option(
        None,
        "--saison", "-s",
        help="Filtrer par saison (ex: 2024-2025)"
    ),
    entity: Optional[List[str]] = typer.Option(
        None,
        "--entity", "-e",
        help="Filtrer par entité (ex: ABCCS, LIRA)"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Afficher les détails de chaque parsing"
    ),
):
    """
    📄 Parse intelligemment les feuilles de match PDF.
    
    Exemples:
    
        # Parser tous les PDFs récursivement
        pyvolley parse data/pdfs
        
        # Parser avec limite et sauvegarde en base
        pyvolley parse data/pdfs -n 100 --save-db
        
        # Parser une saison spécifique
        pyvolley parse data/pdfs --saison 2024-2025
        
        # Parser seulement certaines entités
        pyvolley parse data/pdfs -e ABCCS -e LIRA
        
        # Exporter en JSON
        pyvolley parse data/pdfs -o results.json
        
        # Mode dry-run pour voir ce qui serait parsé
        pyvolley parse data/pdfs --dry-run -n 50
    """
    from pyvolley.parsers.factory import ParserFactory, get_parser
    from pyvolley.parsers.base import ParseResult
    from hashlib import md5
    
    if not input_path.exists():
        console.print(f"[red]Erreur: {input_path} n'existe pas[/red]")
        raise typer.Exit(1)
    
    # Récupérer les fichiers PDF
    if input_path.is_dir():
        if recursive:
            pdf_files = list(input_path.glob("**/*.pdf"))
        else:
            pdf_files = list(input_path.glob("*.pdf"))
    else:
        pdf_files = [input_path]
    
    if not pdf_files:
        console.print("[yellow]Aucun fichier PDF trouvé[/yellow]")
        raise typer.Exit(0)
    
    # Appliquer les filtres
    if saison:
        saison_normalized = saison.replace("/", "-")
        pdf_files = [f for f in pdf_files if saison_normalized in str(f)]
    
    if entity:
        pdf_files = [f for f in pdf_files if any(e in str(f) for e in entity)]
    
    # Appliquer la limite
    if limit:
        pdf_files = pdf_files[:limit]
    
    if not pdf_files:
        console.print("[yellow]Aucun fichier PDF après filtres[/yellow]")
        raise typer.Exit(0)
    
    # Afficher le résumé
    console.print(Panel(
        f"[bold blue]🏐 PyVolley - Parsing des feuilles de match[/bold blue]\n\n"
        f"Source: [cyan]{input_path}[/cyan]\n"
        f"Fichiers: [cyan]{len(pdf_files)}[/cyan]\n"
        f"Parser: [cyan]{parser_version.upper()}[/cyan]\n"
        f"Mode: [cyan]{'Aperçu (dry-run)' if dry_run else 'Parsing'}[/cyan]\n"
        f"Sauvegarde DB: [cyan]{'Oui' if save_db else 'Non'}[/cyan]",
        title="Configuration"
    ))
    
    # Mode dry-run
    if dry_run:
        # Afficher la distribution
        from collections import Counter
        
        # Par saison
        saisons = Counter()
        entities_count = Counter()
        for f in pdf_files:
            parts = f.parts
            for p in parts:
                if p and len(p) == 9 and p[4] == '-':
                    saisons[p] += 1
                if p and (p.startswith("LI") or p.startswith("PT") or p.startswith("AB") or p.startswith("AC")):
                    entities_count[p] += 1
        
        if saisons:
            console.print("\n[bold]Distribution par saison:[/bold]")
            for s, c in sorted(saisons.items()):
                console.print(f"  {s}: {c}")
        
        if entities_count:
            console.print("\n[bold]Distribution par entité (top 10):[/bold]")
            for e, c in entities_count.most_common(10):
                console.print(f"  {e}: {c}")
        
        console.print(f"\n[yellow]Mode dry-run: aucun fichier parsé[/yellow]")
        raise typer.Exit(0)
    
    # Créer le parser
    try:
        parser_name = f"MatchSheetParser{parser_version.upper()}"
        parser = ParserFactory.get(parser_name)
    except KeyError:
        console.print(f"[red]Parser '{parser_version}' non trouvé[/red]")
        console.print(f"[blue]Parsers disponibles: {ParserFactory.list_parsers()}[/blue]")
        raise typer.Exit(1)
    
    console.print(f"\n[blue]Utilisation du parser: {parser.name} v{parser.version}[/blue]\n")
    
    # Cache pour skip_parsed (basé sur hash du fichier)
    cache_file = input_path / ".pyvolley_parse_cache.json" if input_path.is_dir() else None
    parsed_cache = {}
    if skip_parsed and cache_file and cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                parsed_cache = json.load(f)
            console.print(f"[dim]Cache chargé: {len(parsed_cache)} fichiers déjà parsés[/dim]")
        except Exception:
            pass
    
    # Parsing
    results = []
    successful = 0
    skipped = 0
    failed = 0
    warnings_count = 0
    error_details = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        "[",
        TextColumn("{task.completed}/{task.total}"),
        "]",
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Parsing...", total=len(pdf_files))
        
        for pdf_file in pdf_files:
            # Vérifier le cache
            if skip_parsed and cache_file:
                file_hash = md5(pdf_file.read_bytes()).hexdigest()
                if file_hash in parsed_cache:
                    skipped += 1
                    progress.update(task, advance=1, description=f"[yellow]Skip: {pdf_file.name}[/yellow]")
                    continue
            
            try:
                result = parser.parse(pdf_file)
                
                if result.success and result.match:
                    successful += 1
                    results.append({
                        'file': str(pdf_file),
                        'match': result.match,
                        'parse_time_ms': result.parse_time_ms,
                        'warnings': result.warnings,
                    })
                    
                    if result.warnings:
                        warnings_count += len(result.warnings)
                    
                    # Mettre en cache
                    if skip_parsed and cache_file:
                        file_hash = md5(pdf_file.read_bytes()).hexdigest()
                        parsed_cache[file_hash] = {
                            'file': str(pdf_file),
                            'code_match': result.match.code_match,
                            'timestamp': datetime.now().isoformat()
                        }
                    
                    if verbose:
                        m = result.match
                        progress.console.print(
                            f"  [green]✓[/green] {pdf_file.name}: {m.code_match} "
                            f"({m.equipe_a.nom[:20] if m.equipe_a else '?'} vs {m.equipe_b.nom[:20] if m.equipe_b else '?'})"
                        )
                        # Afficher les warnings en détail
                        if result.warnings:
                            for warn in result.warnings:
                                progress.console.print(f"      [yellow]⚠ {warn}[/yellow]")
                        progress.update(task, advance=1)
                    else:
                        progress.update(task, advance=1, description=f"[green]✓ {pdf_file.name[:30]}[/green]")
                else:
                    failed += 1
                    error_details.append({
                        'file': str(pdf_file),
                        'errors': result.errors,
                        'warnings': result.warnings,
                    })
                    if verbose:
                        msg = result.errors[0][:50] if result.errors else 'Erreur inconnue'
                        progress.console.print(f"  [red]✗[/red] {pdf_file.name}: {msg}...")
                        # Afficher aussi les warnings même en cas d'erreur
                        if result.warnings:
                            for warn in result.warnings:
                                progress.console.print(f"      [yellow]⚠ {warn}[/yellow]")
                        progress.update(task, advance=1)
                    else:
                        progress.update(task, advance=1, description=f"[red]✗ {pdf_file.name[:30]}[/red]")
                        
            except Exception as e:
                failed += 1
                error_details.append({
                    'file': str(pdf_file),
                    'errors': [str(e)],
                    'warnings': [],
                })
                progress.update(task, advance=1, description=f"[red]✗ {pdf_file.name[:30]}: {str(e)[:30]}[/red]")
    
    # Sauvegarder le cache
    if skip_parsed and cache_file and parsed_cache:
        try:
            with open(cache_file, "w") as f:
                json.dump(parsed_cache, f)
        except Exception:
            pass
    
    # Résumé
    console.print("\n" + "=" * 60)
    console.print(Panel(
        f"[green]✓ Parsés avec succès: {successful}[/green]\n"
        f"[yellow]⏭ Skippés (cache): {skipped}[/yellow]\n"
        f"[red]✗ Échecs: {failed}[/red]\n"
        f"[dim]⚠ Warnings: {warnings_count}[/dim]",
        title="Résumé du parsing"
    ))
    
    # Exporter en JSON si demandé
    if output and results:
        export_data = []
        for r in results:
            match = r['match']
            export_data.append({
                'file': r['file'],
                'parse_time_ms': r['parse_time_ms'],
                'match': match.model_dump() if hasattr(match, 'model_dump') else match.dict()
            })
        
        with open(output, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
        
        console.print(f"\n[blue]📁 Résultats exportés vers: {output}[/blue]")
    
    # Sauvegarder en base de données si demandé
    if save_db and results:
        console.print("\n[blue]💾 Sauvegarde en base de données...[/blue]")
        
        try:
            from pyvolley.database.connection import DatabaseSession, init_db
            from pyvolley.database.import_service import MatchImportService
            
            init_db()
            
            imported = 0
            import_errors = 0
            
            with DatabaseSession() as session:
                service = MatchImportService(session)
                
                for r in results:
                    try:
                        match_db = service.import_match(r['match'])
                        imported += 1
                    except Exception as e:
                        import_errors += 1
                        if verbose:
                            console.print(f"  [red]✗[/red] Import {r['match'].code_match}: {e}")
                
                session.commit()
            
            console.print(f"[green]✓ {imported} matchs importés en base de données[/green]")
            if import_errors:
                console.print(f"[red]✗ {import_errors} erreurs d'import[/red]")
                
        except Exception as e:
            console.print(f"[red]Erreur lors de l'import en base: {e}[/red]")
    
    # Générer le rapport si demandé
    if report:
        # Améliorer l'export JSON avec les warnings détaillés
        detailed_results = []
        for r in results:
            detailed_results.append({
                'file': r['file'],
                'match_code': r['match'].code_match if r.get('match') else None,
                'parse_time_ms': r['parse_time_ms'],
                'warnings': r.get('warnings', []),
            })
        
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "input_path": str(input_path),
            "parser": parser.name,
            "parser_version": parser.version,
            "total_files": len(pdf_files),
            "successful": successful,
            "skipped": skipped,
            "failed": failed,
            "warnings_total": warnings_count,
            "summary": {
                "success_rate_percent": successful / len(pdf_files) * 100 if pdf_files else 0,
                "avg_parse_time_ms": sum(r['parse_time_ms'] for r in results) / len(results) if results else 0,
            },
            "errors": error_details[:50],  # Limiter à 50 erreurs
            "successful_files_with_warnings": [r for r in detailed_results if r['warnings']],
        }
        
        report_path = Path(f"parse_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        
        console.print(f"\n[blue]📊 Rapport généré: {report_path}[/blue]")
        if report_data["successful_files_with_warnings"]:
            console.print(f"[yellow]⚠ {len(report_data['successful_files_with_warnings'])} fichiers avec avertissements[/yellow]")


@app.command()
def simulate(
    source: Path = typer.Argument(
        ...,
        help="Chemin vers un PDF ou un JSON de match parsé"
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Chemin de sortie pour le HTML généré (optionnel)"
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="N'ouvre pas automatiquement le navigateur"
    ),
    parser: Optional[str] = typer.Option(
        None,
        "--parser", "-p",
        help="Parser à utiliser (v5 par défaut)"
    ),
):
    """
    🎬 Lance la simulation interactive d'un match en HTML.

    Permet de visualiser le déroulé d'un match de volley-ball de manière interactive
    dans votre navigateur.

    Exemples:

        # Simuler un PDF
        pyvolley simulate data/pdfs/mon_match.pdf

        # Simuler un match JSON et ouvrir dans un navigateur
        pyvolley simulate match.json --no-browser

        # Spécifier un parser personnalisé
        pyvolley simulate match.pdf --parser v4
    """
    if not source.exists():
        console.print(f"[red]Erreur: {source} n'existe pas[/red]")
        raise typer.Exit(1)

    try:
        from pyvolley.simulation import launch_viewer

        console.print(f"[blue]📂 Traitement de {source.name}...[/blue]")
        
        html_path = launch_viewer(
            source,
            output=str(output) if output else None,
            open_browser=not no_browser,
            parser_name=parser,
        )
        
        console.print(f"[green]✓ Simulation générée: {html_path}[/green]")
        
        if not no_browser:
            console.print(f"[blue]🌐 Ouverture du navigateur...[/blue]")
        
    except FileNotFoundError as e:
        console.print(f"[red]Erreur: {e}[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]Erreur de parsing: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Erreur: {e}[/red]")
        raise typer.Exit(1)


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

# Sous-commandes d'exploration de la base de données
from pyvolley.cli.db_explorer import explore_app
db_app.add_typer(explore_app, name="explore")


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
    full: bool = typer.Option(False, "--full", help="Réinitialise complètement y compris les migrations"),
):
    """
    🔄 Réinitialise la base de données.
    
    ⚠️ ATTENTION: Supprime toutes les données!
    
    Options:
        --full: Réinitialise aussi l'historique des migrations (après des changements de schéma)
    """
    from pyvolley.database.connection import reset_db, reset_db_with_migrations
    
    if full:
        action_desc = "COMPLÈTEMENT Y COMPRIS LES MIGRATIONS"
    else:
        action_desc = "complètement"
    
    if not force:
        confirm = typer.confirm(f"⚠️ Cette action va SUPPRIMER toutes les données {action_desc}. Continuer?")
        if not confirm:
            console.print("[yellow]Annulé[/yellow]")
            raise typer.Exit(0)
    
    console.print(f"[yellow]Réinitialisation de la base de données ({action_desc})...[/yellow]")
    
    try:
        if full:
            reset_db_with_migrations()
            console.print("[green]✓ Base de données complètement réinitialisée avec migrations reset[/green]")
        else:
            reset_db()
            console.print("[green]✓ Base de données réinitialisée[/green]")
    except Exception as e:
        console.print(f"[red]✗ Erreur: {e}[/red]")
        raise typer.Exit(1)


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
