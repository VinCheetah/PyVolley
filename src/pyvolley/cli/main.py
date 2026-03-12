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


# ============== Commande Scrape (Phase 1 : export CSV → DB) ==============

@app.command()
def scrape(
    entity: Optional[List[str]] = typer.Option(
        None,
        "--entity", "-e",
        help="Code de l'entité (ex: ABCCS, LIRA). Répétable."
    ),
    saison: Optional[str] = typer.Option(
        None,
        "--saison", "-s",
        help="Saison au format YYYY/YYYY (défaut: saison courante)"
    ),
    all_entities: bool = typer.Option(
        False,
        "--all",
        help="Scrape toutes les entités (ligues, comités, nationales)"
    ),
    entity_type: Optional[str] = typer.Option(
        None,
        "--type", "-t",
        help="Filtrer par type d'entité: nationale, ligue, comite"
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Affiche ce qui serait importé sans modifier la base"
    ),
    enrich_clubs: bool = typer.Option(
        True,
        "--enrich-clubs/--no-enrich-clubs",
        help="Enrichit les clubs avec les données de l'adressier FFVB (coordonnées, salles, dirigeants). Activé par défaut."
    ),
):
    """
    🔄 Scrape les données FFVB et les importe en base de données (Phase 1).

    Utilise l'export CSV de la FFVB pour récupérer tous les matchs d'une
    ou plusieurs entités en une seule requête HTTP par entité. Les données
    sont importées dans la base de données avec le statut "discovered".

    Par défaut, tous les matchs sont importés en base avec enrichissement
    automatique des métadonnées de compétition (genre, niveau, catégorie,
    division) et des clubs (coordonnées, salles, dirigeants).

    Utilisez --dry-run pour prévisualiser sans modifier la base.
    Utilisez --no-enrich-clubs pour désactiver l'enrichissement des clubs.

    Exemples:

        # Scraper et importer une entité
        pyvolley scrape -e ABCCS

        # Scraper sans enrichissement des clubs
        pyvolley scrape -e ABCCS --no-enrich-clubs

        # Scraper plusieurs entités
        pyvolley scrape -e ABCCS -e LIRA

        # Scraper toutes les ligues
        pyvolley scrape --type ligue

        # Voir ce qui serait importé (dry-run)
        pyvolley scrape -e ABCCS --dry-run
    """
    from pyvolley.scrapers.ffvb import FFVBScraper
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.export_import_service import ExportImportService

    scraper = FFVBScraper()

    if saison is None:
        saison = scraper._get_current_saison()

    # Déterminer les entités à traiter
    entities_to_process = []
    if all_entities:
        all_ents = scraper.get_entities()
        if entity_type:
            all_ents = [e for e in all_ents if e.type == entity_type.lower()]
        entities_to_process = [e.code for e in all_ents]
    elif entity_type and not entity:
        all_ents = scraper.get_entities()
        entities_to_process = [e.code for e in all_ents if e.type == entity_type.lower()]
    elif entity:
        entities_to_process = list(entity)

    if not entities_to_process:
        console.print("[yellow]Aucune entité spécifiée.[/yellow]")
        from pyvolley.scrapers.ffvb import FFVBScraper as _s
        _list_entities(_s())
        console.print("\n[blue]Utilisez -e CODE, --type TYPE, ou --all[/blue]")
        raise typer.Exit(0)

    entities_display = ', '.join(entities_to_process[:5])
    if len(entities_to_process) > 5:
        entities_display += f"... (+{len(entities_to_process) - 5})"

    mode = "[yellow]DRY-RUN[/yellow]" if dry_run else "[green]IMPORT[/green]"
    enrich_label = " + [magenta]enrichissement clubs[/magenta]" if enrich_clubs and not dry_run else " [dim](clubs: désactivé)[/dim]" if not dry_run else ""
    console.print(Panel(
        f"[bold blue]🔄 Scrape FFVB (Phase 1 - Export CSV)[/bold blue]\n\n"
        f"Saison:   [cyan]{saison}[/cyan]\n"
        f"Entité(s): [cyan]{entities_display}[/cyan] ({len(entities_to_process)} au total)\n"
        f"Mode:     {mode}{enrich_label}",
        title="Configuration"
    ))

    if not dry_run:
        init_db()

    total_matches = 0
    total_imported = 0
    total_updated = 0
    total_duplicates = 0
    total_errors = 0
    total_clubs_enriched = 0

    for entite_code in entities_to_process:
        console.print(f"\n[blue]📂 {entite_code} - Saison {saison}[/blue]")

        try:
            with console.status(f"[bold blue]Récupération de l'export CSV pour {entite_code}..."):
                export_matches = scraper.scrape_entity(entite_code, saison)
        except Exception as e:
            console.print(f"  [red]Erreur: {e}[/red]")
            total_errors += 1
            continue

        if not export_matches:
            console.print(f"  [yellow]Aucun match trouvé[/yellow]")
            continue

        total_matches += len(export_matches)

        # Résumé des poules
        from pyvolley.scrapers.ffvb.export_scraper import get_unique_poules
        poules = get_unique_poules(export_matches)
        played = sum(1 for m in export_matches if m.match_joue)
        console.print(
            f"  [green]✓ {len(export_matches)} match(s) récupéré(s)[/green] "
            f"({played} joués, {len(poules)} poules)"
        )

        if dry_run:
            console.print(f"  Poules: {', '.join(sorted(poules.keys()))}")
            continue

        # Import en base de données
        try:
            with DatabaseSession() as session:
                service = ExportImportService(session)
                stats = service.import_matches(export_matches, entite_code, saison)

                imported = stats.get("imported", 0)
                updated = stats.get("updated", 0)
                duplicates = stats.get("duplicates", 0)
                errors = stats.get("errors", 0)

                total_imported += imported
                total_updated += updated
                total_duplicates += duplicates
                total_errors += errors

                parts = []
                if imported:
                    parts.append(f"[green]+{imported} créés[/green]")
                if updated:
                    parts.append(f"[cyan]~{updated} mis à jour[/cyan]")
                if duplicates:
                    parts.append(f"[dim]{duplicates} inchangés[/dim]")
                if errors:
                    parts.append(f"[red]{errors} erreurs[/red]")
                console.print(f"  DB: {' | '.join(parts) or '[dim]aucun changement[/dim]'}")

                # Enrichissement des clubs via adressier
                if enrich_clubs:
                    try:
                        from pyvolley.scrapers.ffvb.adressier_scraper import fetch_adressier
                        poule_codes = sorted(poules.keys())
                        with console.status(
                            f"[bold magenta]Téléchargement adressier pour {entite_code} "
                            f"({len(poule_codes)} poules)..."
                        ):
                            clubs_info = fetch_adressier(
                                scraper.client, scraper.base_url,
                                entite_code, saison, poule_codes,
                            )
                        if clubs_info:
                            club_stats = service.enrich_clubs(
                                clubs_info, entite_code, saison, scraper.base_url,
                            )
                            enriched = club_stats.get("enriched", 0)
                            created = club_stats.get("created", 0)
                            total_clubs_enriched += enriched + created
                            console.print(
                                f"  Clubs: [magenta]{enriched} enrichis[/magenta] | "
                                f"[green]+{created} créés[/green]"
                            )
                    except Exception as e:
                        console.print(f"  [red]Erreur enrichissement clubs: {e}[/red]")

                session.commit()
        except Exception as e:
            console.print(f"  [red]Erreur import: {e}[/red]")
            total_errors += 1

    # Résumé
    console.print()
    result_parts = [f"Matchs récupérés:  [cyan]{total_matches}[/cyan]"]
    if not dry_run:
        result_parts.append(f"Créés en base:     [green]{total_imported}[/green]")
        result_parts.append(f"Mis à jour:        [cyan]{total_updated}[/cyan]")
        if total_duplicates:
            result_parts.append(f"Inchangés:         [dim]{total_duplicates}[/dim]")
        if total_clubs_enriched:
            result_parts.append(f"Clubs enrichis:    [magenta]{total_clubs_enriched}[/magenta]")
    if total_errors:
        result_parts.append(f"Erreurs:           [red]{total_errors}[/red]")

    title = "🔍 Résultats (dry-run)" if dry_run else "✅ Résultats"
    console.print(Panel("\n".join(result_parts), title=title))

    if dry_run and total_matches:
        console.print(
            f"\n[blue]💡 Relancez sans --dry-run pour importer en base.[/blue]"
        )


# ============== Commandes Download ==============

@app.command()
def download(
    output_dir: Path = typer.Option(
        Path("data/pdfs"),
        "--output", "-o",
        help="Dossier de sortie pour les PDFs"
    ),
    from_db: bool = typer.Option(
        False,
        "--from-db",
        help="Télécharge les PDFs des matchs découverts en base (parsing_status='discovered'). "
             "Met à jour le statut en 'downloaded'. Alternative au scraping classique."
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
    pro: bool = typer.Option(
        False,
        "--pro",
        help="Télécharge uniquement les matchs pro (Marmara SpikeLigue, Saforelle Power 6, Ligue B)"
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit", "-n",
        help="Nombre maximum de feuilles à télécharger (aucune limite par défaut)"
    ),
    delay: float = typer.Option(
        0.3,
        "--delay", "-d",
        help="Délai minimum entre chaque requête HTTP (en secondes). "
             "Gère le rate limiting côté serveur."
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

    Deux modes de fonctionnement :

    1. MODE CLASSIQUE (par défaut) : scrape les exports CSV FFVB et télécharge
       les PDFs pour les entités/saisons spécifiées.

    2. MODE BASE DE DONNÉES (--from-db) : télécharge les PDFs des matchs
       déjà découverts en base (parsing_status='discovered'). Met à jour
       le statut en 'downloaded'. Utilise les URLs stockées en base.
    
    Exemples:
    
        # Télécharger tous les matchs des Nationales Seniors
        pyvolley download -e ABCCS
        
        # Mode DB : télécharger les matchs découverts mais pas téléchargés
        pyvolley download --from-db
        
        # Mode DB : avec limite
        pyvolley download --from-db -n 100
        
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
        
        # Télécharger uniquement les matchs pro (LNV)
        pyvolley download --pro
        
        # Limiter à 10 téléchargements avec aperçu
        pyvolley download -e ABCCS -p EFA -n 10 --dry-run
    """
    # ── Mode --from-db : télécharger depuis la base ─────────────────
    if from_db:
        _download_from_db(
            limit=limit,
            saison=saison,
            verbose=False,
        )
        raise typer.Exit(0)

    from pyvolley.scrapers.ffvb import FFVBScraper
    from pyvolley.scrapers.lnv import PRO_COMPETITIONS, PRO_ENTITY_CODE
    
    # Le délai CLI est passé au scraper pour éviter le double-delay :
    # HttpClient.rate_limit() gère déjà l'espacement entre requêtes.
    scraper = FFVBScraper(request_delay=delay)
    
    # Mode --pro : ne télécharger que les compétitions professionnelles
    if pro:
        if not entity:
            entity = [PRO_ENTITY_CODE]
        pro_poule_codes = [c.code for c in PRO_COMPETITIONS]
    
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
    for current_saison in saisons:
        for current_entity in entities_to_process:
            console.print(f"\n[blue]📂 {current_entity} - Saison {current_saison}[/blue]")
            
            # Récupérer les matchs via export CSV (une seule requête)
            try:
                with console.status(f"[bold blue]Récupération des matchs pour {current_entity} (export CSV)..."):
                    export_matches = scraper.scrape_entity(
                        current_entity, current_saison, poule=poule,
                    )
            except Exception as e:
                console.print(f"  [red]Erreur lors de la récupération: {e}[/red]")
                continue
            
            if not export_matches:
                console.print(f"  [yellow]Aucun match trouvé[/yellow]")
                continue
            
            # Filtrer pour le mode --pro (seulement les compétitions LNV)
            if pro:
                export_matches = [m for m in export_matches if m.poule_code in pro_poule_codes]
                if not export_matches:
                    console.print(f"  [yellow]Aucun match pro trouvé[/yellow]")
                    continue
            
            # Convertir en MatchInfo pour le téléchargement
            from pyvolley.scrapers.base import MatchInfo as _MatchInfo
            for em in export_matches:
                mi = _MatchInfo(
                    code=em.code_match,
                    entite_code=em.entite_code,
                    saison=em.saison,
                    poule_code=em.poule_code,
                    journee=em.journee,
                    pdf_url=em.feuille_match_url,
                )
                mi.poule_nom = em.poule_code
                mi.entity_code = current_entity
                all_matches.append(mi)
            
            console.print(f"  [green]✓ {len(export_matches)} match(s) trouvé(s)[/green]")
            
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
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 10  # Pause longue après N erreurs d'affilée
    
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
        task = progress.add_task("Téléchargement...", total=len(all_matches))
        
        for match in all_matches:
            # Récupérer l'entité du match
            match_entity = getattr(match, 'entity_code', entity[0] if entity else 'unknown')
            match_saison = getattr(match, 'saison', saisons[0])
            
            # Construire le chemin de sortie
            if organize:
                # Organiser par saison/entité/poule
                saison_folder = match_saison.replace("/", "-")
                poule_nom_safe = _sanitize_filename(getattr(match, 'poule_nom', match.poule_code or 'autres'))
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
                    consecutive_errors = 0
                    progress.update(task, advance=1, description=f"[green]✓ {match.code}[/green]")
                else:
                    errors += 1
                    consecutive_errors += 1
                    error_list.append({"code": match.code, "error": result.message})
                    progress.update(task, advance=1, description=f"[red]✗ {match.code}: {result.message}[/red]")
                    
            except Exception as e:
                errors += 1
                consecutive_errors += 1
                error_list.append({"code": match.code, "error": str(e)})
                progress.update(task, advance=1, description=f"[red]✗ {match.code}: {e}[/red]")
            
            # Si trop d'erreurs consécutives, faire une pause plus longue
            # (probablement un blocage temporaire type 403)
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                pause_time = 30.0
                progress.update(task, description=f"[yellow]⏸ Pause de {pause_time:.0f}s après {consecutive_errors} erreurs consécutives...[/yellow]")
                time.sleep(pause_time)
                consecutive_errors = 0
            # NOTE : pas de time.sleep(delay) ici – le rate limiting est
            # géré par HttpClient.rate_limit() dans download_match_pdf().
    
    # Résumé
    console.print("\n" + "=" * 50)
    console.print(Panel(
        f"[green]✓ Téléchargés: {downloaded}[/green]\n"
        f"[yellow]⏭ Skippés (existants): {skipped}[/yellow]\n"
        f"[red]✗ Erreurs: {errors}[/red]\n\n"
        f"📁 Fichiers dans: {output_dir.absolute()}",
        title="Résumé du téléchargement"
    ))
    
    # Générer le rapport (organisé dans data/reports/download/)
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
        report_dir = Path("data/reports/download")
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        console.print(f"\n[blue]📊 Rapport: {report_path}[/blue]")


@app.command("download-fast")
def download_fast(
    output_dir: Path = typer.Option(
        Path("data/pdfs"),
        "--output", "-o",
        help="Dossier de sortie pour les PDFs"
    ),
    entity: Optional[List[str]] = typer.Option(
        None,
        "--entity", "-e",
        help="Code de l'entité (ex: ABCCS, LIRA). Répétable."
    ),
    poule: Optional[str] = typer.Option(
        None,
        "--poule", "-p",
        help="Code de la poule (ex: EFA, PMA)"
    ),
    saison: Optional[List[str]] = typer.Option(
        None,
        "--saison", "-s",
        help="Saison au format YYYY/YYYY. Répétable."
    ),
    all_entities: bool = typer.Option(
        False, "--all",
        help="Télécharge pour TOUTES les entités"
    ),
    entity_type: Optional[str] = typer.Option(
        None, "--type", "-t",
        help="Filtrer par type d'entité: nationale, ligue, comite"
    ),
    pro: bool = typer.Option(
        False, "--pro",
        help="Télécharge uniquement les matchs pro (LNV)"
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n",
        help="Nombre maximum de feuilles à télécharger"
    ),
    delay: float = typer.Option(
        0.15,
        "--delay", "-d",
        help="Délai minimum entre chaque requête (secondes)"
    ),
    concurrent: int = typer.Option(
        5,
        "--concurrent", "-c",
        help="Nombre de téléchargements simultanés (1-20)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Affiche les matchs sans télécharger"
    ),
    organize: bool = typer.Option(
        True, "--organize/--flat",
        help="Organise les fichiers par saison/compétition"
    ),
    report: bool = typer.Option(
        False, "--report",
        help="Génère un rapport JSON"
    ),
):
    """
    ⚡ Téléchargement rapide et concurrent des feuilles de match.

    Utilise des requêtes HTTP/2 concurrentes pour une vitesse bien
    supérieure à la commande `download` classique.

    Exemples:

        # Télécharger rapidement avec 10 requêtes parallèles
        pyvolley download-fast -e ABCCS -c 10

        # Télécharger toutes les ligues avec concurrence modérée
        pyvolley download-fast --type ligue -c 5
    """
    import asyncio
    from pyvolley.scrapers.ffvb import FFVBScraper
    from pyvolley.scrapers.lnv import PRO_COMPETITIONS, PRO_ENTITY_CODE

    concurrent = max(1, min(concurrent, 20))

    scraper = FFVBScraper(request_delay=delay)

    if pro:
        if not entity:
            entity = [PRO_ENTITY_CODE]
        pro_poule_codes = [c.code for c in PRO_COMPETITIONS]

    if saison is None or len(saison) == 0:
        saisons = [scraper._get_current_saison()]
    else:
        saisons = list(saison)

    # Déterminer les entités
    entities_to_process = []
    if all_entities:
        all_ents = scraper.get_entities()
        if entity_type:
            all_ents = [e for e in all_ents if e.type == entity_type.lower()]
        entities_to_process = [e.code for e in all_ents]
    elif entity_type and not entity:
        all_ents = scraper.get_entities()
        entities_to_process = [e.code for e in all_ents if e.type == entity_type.lower()]
    elif entity:
        entities_to_process = list(entity)

    entities_display = ', '.join(entities_to_process[:5])
    if len(entities_to_process) > 5:
        entities_display += f"... (+{len(entities_to_process) - 5})"

    console.print(Panel(
        f"[bold blue]⚡ PyVolley - Téléchargement rapide concurrent[/bold blue]\n\n"
        f"Saison(s): [cyan]{', '.join(saisons)}[/cyan]\n"
        f"Entité(s): [cyan]{entities_display or 'Aucune'}[/cyan] ({len(entities_to_process)} au total)\n"
        f"Poule: [cyan]{poule or 'Toutes'}[/cyan]\n"
        f"Concurrence: [cyan]{concurrent} requêtes parallèles[/cyan]\n"
        f"Délai: [cyan]{delay}s[/cyan]\n"
        f"Sortie: [cyan]{output_dir}[/cyan]\n"
        f"Mode: [cyan]{'Aperçu (dry-run)' if dry_run else 'Téléchargement'}[/cyan]",
        title="Configuration"
    ))

    output_dir.mkdir(parents=True, exist_ok=True)

    if not entities_to_process:
        console.print("\n[yellow]Aucune entité spécifiée.[/yellow]")
        _list_entities(scraper)
        raise typer.Exit(0)

    # Phase 1 : collecte des matchs via export CSV (une requête par entité)
    all_matches = []
    for current_saison in saisons:
        for current_entity in entities_to_process:
            console.print(f"\n[blue]📂 {current_entity} - Saison {current_saison}[/blue]")
            try:
                with console.status(f"[bold blue]Récupération des matchs (export CSV)..."):
                    export_matches = scraper.scrape_entity(
                        current_entity, current_saison, poule=poule,
                    )
            except Exception as e:
                console.print(f"  [red]Erreur: {e}[/red]")
                continue

            if not export_matches:
                console.print(f"  [yellow]Aucun match trouvé[/yellow]")
                continue

            if pro:
                export_matches = [m for m in export_matches if m.poule_code in pro_poule_codes]

            # Convertir en MatchInfo pour le téléchargement
            from pyvolley.scrapers.base import MatchInfo as _MatchInfo
            for em in export_matches:
                mi = _MatchInfo(
                    code=em.code_match,
                    entite_code=em.entite_code,
                    saison=em.saison,
                    poule_code=em.poule_code,
                    journee=em.journee,
                    pdf_url=em.feuille_match_url,
                )
                mi.poule_nom = em.poule_code
                mi.entity_code = current_entity
                all_matches.append(mi)

            console.print(f"  [green]✓ {len(export_matches)} match(s) trouvé(s)[/green]")

            if limit and len(all_matches) >= limit:
                all_matches = all_matches[:limit]
                break
        if limit and len(all_matches) >= limit:
            break

    console.print(f"\n[green]✓ Total: {len(all_matches)} match(s) à traiter[/green]")

    if not all_matches:
        console.print("[yellow]Aucun match trouvé[/yellow]")
        raise typer.Exit(0)

    if dry_run:
        from collections import Counter
        entity_counts = Counter(getattr(m, 'entity_code', 'unknown') for m in all_matches)
        console.print("\n[bold]Résumé par entité:[/bold]")
        for ent, count in sorted(entity_counts.items()):
            console.print(f"  {ent}: {count} match(s)")
        console.print(f"\n[yellow]Mode dry-run: aucun fichier téléchargé[/yellow]")
        raise typer.Exit(0)

    # Phase 2 : téléchargement concurrent
    async def _run_downloads():
        from pyvolley.scrapers.async_http_client import AsyncHttpClient

        async with AsyncHttpClient(
            request_delay=delay,
            max_concurrent=concurrent,
        ) as client:
            downloaded = 0
            skipped = 0
            errors = 0
            error_list = []

            # Préparer la liste des tâches de téléchargement
            download_tasks = []
            for match in all_matches:
                match_entity = getattr(match, 'entity_code', entity[0] if entity else 'unknown')
                match_saison = getattr(match, 'saison', saisons[0])

                if organize:
                    saison_folder = match_saison.replace("/", "-")
                    poule_nom_safe = _sanitize_filename(
                        getattr(match, 'poule_nom', match.poule_code or 'autres'))
                    match_dir = output_dir / saison_folder / match_entity / poule_nom_safe
                else:
                    match_dir = output_dir

                match_dir.mkdir(parents=True, exist_ok=True)
                filepath = match_dir / match.filename

                if filepath.exists():
                    skipped += 1
                    continue

                download_tasks.append((match, filepath))

            console.print(f"[blue]⏭ {skipped} fichier(s) déjà existant(s) ignoré(s)[/blue]")
            console.print(f"[blue]⬇ {len(download_tasks)} fichier(s) à télécharger[/blue]")

            if not download_tasks:
                return downloaded, skipped, errors, error_list

            # Télécharger par lots
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                "[", TextColumn("{task.completed}/{task.total}"), "]",
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("Téléchargement concurrent...", total=len(download_tasks))

                semaphore = asyncio.Semaphore(concurrent)

                async def _download_one(match, filepath):
                    nonlocal downloaded, errors

                    async with semaphore:
                        if not match.pdf_url:
                            from pyvolley.scrapers.ffvb.utils import build_pdf_url
                            match.pdf_url = build_pdf_url(
                                scraper.base_url, match.entite_code,
                                match.code, match.saison,
                            )
                        try:
                            pdf_url = match.pdf_url
                            is_external = "lnv.fr" in pdf_url or "datavolley" in pdf_url.lower()
                            response = None

                            if is_external:
                                # LNV externe : tenter puis fallback FFVB
                                try:
                                    skip_verify = "datavolley.lnv.fr" in pdf_url
                                    if skip_verify:
                                        # Certificat invalide → httpx brut
                                        import httpx as _httpx
                                        async with _httpx.AsyncClient(verify=False, timeout=30) as raw:
                                            raw_resp = await raw.get(pdf_url)
                                            raw_resp.raise_for_status()
                                        if raw_resp.content.startswith(b"%PDF"):
                                            response = raw_resp
                                    else:
                                        response = await client.get(pdf_url)
                                        if not response.content.startswith(b"%PDF"):
                                            response = None
                                except Exception:
                                    response = None

                                if response is None:
                                    from pyvolley.scrapers.ffvb.utils import build_pdf_url
                                    ffvb_url = build_pdf_url(
                                        scraper.base_url, match.entite_code,
                                        match.code, match.saison,
                                    )
                                    response = await client.get(ffvb_url)
                            else:
                                response = await client.get(pdf_url)

                            content = response.content

                            content_type = response.headers.get("Content-Type", "")
                            if "pdf" not in content_type.lower() and not content.startswith(b"%PDF"):
                                errors += 1
                                error_list.append({"code": match.code, "error": "Not a PDF"})
                                progress.update(task_id, advance=1,
                                                description=f"[red]✗ {match.code}: Not PDF[/red]")
                                return

                            filepath.parent.mkdir(parents=True, exist_ok=True)
                            with open(filepath, "wb") as f:
                                f.write(content)

                            downloaded += 1
                            progress.update(task_id, advance=1,
                                            description=f"[green]✓ {match.code}[/green]")
                        except Exception as e:
                            errors += 1
                            error_list.append({"code": match.code, "error": str(e)})
                            progress.update(task_id, advance=1,
                                            description=f"[red]✗ {match.code}[/red]")

                await asyncio.gather(
                    *[_download_one(m, fp) for m, fp in download_tasks]
                )

            return downloaded, skipped, errors, error_list

    downloaded, skipped, errors, error_list = asyncio.run(_run_downloads())

    console.print("\n" + "=" * 50)
    console.print(Panel(
        f"[green]✓ Téléchargés: {downloaded}[/green]\n"
        f"[yellow]⏭ Skippés (existants): {skipped}[/yellow]\n"
        f"[red]✗ Erreurs: {errors}[/red]\n\n"
        f"📁 Fichiers dans: {output_dir.absolute()}",
        title="Résumé du téléchargement rapide"
    ))

    if report:
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "mode": "concurrent",
            "concurrent_workers": concurrent,
            "saisons": saisons,
            "entities": entities_to_process,
            "downloaded": downloaded,
            "skipped": skipped,
            "errors": errors,
            "error_details": error_list,
            "output_dir": str(output_dir.absolute()),
        }
        report_dir = Path("data/reports/download")
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"download_fast_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        console.print(f"\n[blue]📊 Rapport: {report_path}[/blue]")


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
        poules = scraper.discover_poules(entity, saison)
    
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
    poule: Optional[str] = typer.Option(None, "--poule", "-p", help="Code de la poule (filtre)"),
    saison: Optional[str] = typer.Option(None, "--saison", "-s", help="Saison YYYY/YYYY"),
    limit: int = typer.Option(50, "--limit", "-n", help="Nombre max de matchs à afficher"),
):
    """
    📋 Liste les matchs disponibles pour une entité (via export CSV).

    Exemples:

        # Lister tous les matchs d'une entité
        pyvolley list-matches ABCCS

        # Filtrer par poule
        pyvolley list-matches ABCCS -p PMA
    """
    from pyvolley.scrapers.ffvb import FFVBScraper

    scraper = FFVBScraper()

    if saison is None:
        saison = scraper._get_current_saison()

    with console.status(f"[bold blue]Récupération des matchs pour {entity}..."):
        export_matches = scraper.scrape_entity(entity, saison, poule=poule)

    if not export_matches:
        console.print(f"[yellow]Aucun match trouvé[/yellow]")
        return

    table = Table(title=f"📋 Matchs - {entity} - Saison {saison}")
    table.add_column("Code", style="cyan", no_wrap=True)
    table.add_column("Poule", style="white")
    table.add_column("Date", style="dim")
    table.add_column("Équipe A", style="white")
    table.add_column("Équipe B", style="white")
    table.add_column("Score", style="green")
    table.add_column("PDF", style="green")

    for m in export_matches[:limit]:
        date_str = m.date.strftime("%d/%m/%Y") if m.date else "-"
        score = f"{m.score_a}-{m.score_b}" if m.score_a is not None else "-"
        has_pdf = "✓" if m.feuille_match_url else "✗"
        table.add_row(
            m.code_match, m.poule_code or "-", date_str,
            m.equipe_a_nom or "-", m.equipe_b_nom or "-", score, has_pdf,
        )

    console.print(table)

    if len(export_matches) > limit:
        console.print(f"\n[yellow]... et {len(export_matches) - limit} autres matchs[/yellow]")
    console.print(f"\n[green]Total: {len(export_matches)} match(s)[/green]")


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
    """Affiche un tableau de matchs (MatchInfo)."""
    table = Table(title=f"📋 Matchs - Saison {saison}")
    table.add_column("Code", style="cyan", no_wrap=True)
    table.add_column("Poule", style="white")
    table.add_column("PDF", style="green")

    for m in matches:
        has_pdf = "✓" if m.pdf_url else "✗"
        table.add_row(m.code, m.poule_code or "-", has_pdf)

    console.print(table)


def _sanitize_filename(name: str) -> str:
    """Nettoie un nom pour l'utiliser comme nom de fichier/dossier."""
    # Remplacer les caractères problématiques
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Limiter la longueur
    return name[:100].strip()


# ============== Commande Parse ==============

@app.command()
def parse(
    input_path: Optional[Path] = typer.Argument(
        None,
        help="Chemin vers un PDF ou un dossier. Ignoré avec --from-db."
    ),
    from_db: bool = typer.Option(
        False,
        "--from-db",
        help="Parse les matchs depuis la base de données (matchs avec statut 'discovered' ou 'downloaded' "
             "dont le PDF existe localement dans data/pdfs)"
    ),
    status_filter: Optional[str] = typer.Option(
        None,
        "--status",
        help="Avec --from-db : filtrer par statut (discovered, downloaded, error). "
             "Par défaut : discovered + downloaded"
    ),
    played_only: bool = typer.Option(
        True,
        "--played-only/--all-matches",
        help="Avec --from-db : ne parser que les matchs joués (match_joue=True)"
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Fichier JSON de sortie pour les résultats"
    ),
    parser_version: str = typer.Option(
        "auto",
        "--parser", "-p",
        help="Parser à utiliser (auto = défaut)"
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
    random_order: bool = typer.Option(
        False,
        "--random",
        help="Parser les fichiers dans un ordre aléatoire (utile pour les tests)"
    ),
    skip_parsed: bool = typer.Option(
        True,
        "--skip-parsed/--force",
        help="Ignorer les fichiers déjà parsés. En mode --from-db, se base sur parsing_status. "
             "En mode fichier, utilise le cache de hashes."
    ),
    save_db: bool = typer.Option(
        False,
        "--save-db", "-d",
        help="Enregistrer les résultats dans la base de données. "
             "Avec --from-db, les matchs existants sont enrichis (Phase 2). "
             "Sans --from-db, de nouveaux matchs sont créés."
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
    saison: Optional[List[str]] = typer.Option(
        None,
        "--saison", "-s",
        help="Filtrer par saison (ex: 2024-2025). Répétable."
    ),
    entity: Optional[List[str]] = typer.Option(
        None,
        "--entity", "-e",
        help="Filtrer par entité (ex: ABCCS, LIRA). Répétable."
    ),
    clear_cache: bool = typer.Option(
        False,
        "--clear-cache",
        help="Vide le cache de parsing avant de commencer"
    ),
    collect_problems: Optional[Path] = typer.Option(
        None,
        "--collect-problems", "-C",
        help="Copie les PDFs problématiques dans ce dossier, classés par type de warning"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Afficher les détails de chaque parsing"
    ),
    verify: bool = typer.Option(
        False,
        "--verify",
        help="Avec --from-db : re-parser les matchs déjà parsés et comparer les données"
    ),
):
    """
    📄 Parse les feuilles de match PDF et enrichit la base de données.

    Deux modes de fonctionnement :

    1. MODE FICHIER (par défaut) : parse des PDFs depuis le système de fichiers.
       Un cache de hashes permet d'éviter le re-parsing. Utilisez --save-db
       pour créer de nouveaux matchs en base.

    2. MODE BASE DE DONNÉES (--from-db) : interroge la base pour trouver les
       matchs avec statut "discovered" ou "downloaded", localise leurs PDFs
       dans data/pdfs, les parse, et enrichit les enregistrements existants
       (Phase 2 du pipeline). Le --save-db est implicite.

    Exemples:

        # Mode fichier : parser tous les PDFs récursivement
        pyvolley parse data/pdfs

        # Mode fichier : parser et sauvegarder en base
        pyvolley parse data/pdfs --save-db

        # Mode DB : enrichir les matchs non encore parsés
        pyvolley parse --from-db

        # Mode DB : ne parser que les matchs d'une entité
        pyvolley parse --from-db -e ABCCS

        # Mode DB : re-parser les matchs en erreur
        pyvolley parse --from-db --status error

        # Mode DB : forcer le re-parsing de tous les matchs
        pyvolley parse --from-db --force

        # Mode DB : vérifier les données parsées
        pyvolley parse --from-db --verify

        # Parser avec limite et ordre aléatoire
        pyvolley parse data/pdfs -n 100 --random

        # Exporter en JSON
        pyvolley parse data/pdfs -o results.json

        # Mode dry-run pour voir ce qui serait parsé
        pyvolley parse data/pdfs --dry-run -n 50
    """
    if from_db:
        _parse_from_db(
            status_filter=status_filter,
            played_only=played_only,
            parser_version=parser_version,
            limit=limit,
            skip_parsed=skip_parsed,
            dry_run=dry_run,
            saison=saison,
            entity=entity,
            verbose=verbose,
            verify=verify,
            report=report,
            output=output,
            collect_problems=collect_problems,
        )
    else:
        if input_path is None:
            console.print("[red]Erreur: spécifiez un chemin ou utilisez --from-db[/red]")
            raise typer.Exit(1)
        _parse_from_files(
            input_path=input_path,
            output=output,
            parser_version=parser_version,
            recursive=recursive,
            limit=limit,
            random_order=random_order,
            skip_parsed=skip_parsed,
            save_db=save_db,
            report=report,
            dry_run=dry_run,
            saison=saison,
            entity=entity,
            clear_cache=clear_cache,
            collect_problems=collect_problems,
            verbose=verbose,
        )


def _parse_from_db(
    *,
    status_filter: Optional[str],
    played_only: bool,
    parser_version: str,
    limit: Optional[int],
    skip_parsed: bool,
    dry_run: bool,
    saison: Optional[List[str]],
    entity: Optional[List[str]],
    verbose: bool,
    verify: bool,
    report: bool,
    output: Optional[Path],
    collect_problems: Optional[Path],
) -> None:
    """Parse les matchs depuis la base de données (Phase 2 du pipeline).

    Interroge la DB pour trouver les matchs non encore parsés, localise
    leurs PDFs dans data/pdfs, les parse, et enrichit les enregistrements.
    """
    from pyvolley.parsers.factory import ParserFactory
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import MatchDB, SaisonDB, ImportLogDB
    from sqlalchemy import select

    init_db()

    # Déterminer les statuts à traiter
    if verify:
        statuses = ["parsed"]
    elif status_filter:
        statuses = [status_filter]
    elif not skip_parsed:
        statuses = ["discovered", "downloaded", "parsed", "error"]
    else:
        statuses = ["discovered", "downloaded"]

    # Créer le parser
    try:
        if parser_version == "auto":
            parser = ParserFactory.get_default()
        else:
            parser = ParserFactory.get(parser_version)
    except KeyError:
        console.print(f"[red]Parser '{parser_version}' non trouvé[/red]")
        raise typer.Exit(1)

    with DatabaseSession() as session:
        service = MatchImportService(session)

        # Construire la requête
        stmt = select(MatchDB).where(MatchDB.parsing_status.in_(statuses))
        if played_only:
            stmt = stmt.where(MatchDB.match_joue == True)  # noqa: E712

        # Filtres saison
        if saison:
            normalized = [s.replace("/", "-") for s in saison]
            saison_ids = [
                s.id for s in session.scalars(
                    select(SaisonDB).where(SaisonDB.code.in_(normalized))
                ).all()
            ]
            if saison_ids:
                stmt = stmt.where(MatchDB.saison_id.in_(saison_ids))
            else:
                console.print(f"[yellow]Aucune saison trouvée pour {saison}[/yellow]")
                raise typer.Exit(0)

        # Filtres entité (via compétition → entité)
        if entity:
            from pyvolley.database.models import EntiteFFVBDB, CompetitionDB
            entite_ids = [
                e.id for e in session.scalars(
                    select(EntiteFFVBDB).where(EntiteFFVBDB.code.in_(entity))
                ).all()
            ]
            if entite_ids:
                comp_ids = [
                    c.id for c in session.scalars(
                        select(CompetitionDB).where(CompetitionDB.entite_id.in_(entite_ids))
                    ).all()
                ]
                if comp_ids:
                    stmt = stmt.where(MatchDB.competition_id.in_(comp_ids))

        stmt = stmt.order_by(MatchDB.code_match)
        if limit:
            stmt = stmt.limit(limit)

        matches_db = list(session.scalars(stmt).all())

    if not matches_db:
        console.print(f"[yellow]Aucun match à parser (statuts: {', '.join(statuses)})[/yellow]")
        raise typer.Exit(0)

    # Localiser les PDFs
    pdf_base_dir = Path("data/pdfs")
    match_pdf_pairs: list[tuple[MatchDB, Path]] = []

    # Construire un index des PDFs locaux pour une recherche rapide
    # au lieu de faire un glob par match (148k+ fichiers)
    _pdf_index: dict[str, Path] = {}
    if pdf_base_dir.exists():
        for pdf_file in pdf_base_dir.glob("**/*.pdf"):
            # Indexer par code_match extrait du nom de fichier
            stem = pdf_file.stem  # ex: "PTIDF92_LME056" ou "LME056"
            _pdf_index[stem] = pdf_file
            # Si le nom contient un underscore, indexer aussi la partie après
            if "_" in stem:
                code_part = stem.split("_", 1)[1]
                if code_part not in _pdf_index:
                    _pdf_index[code_part] = pdf_file

    for match_db in matches_db:
        code = match_db.code_match
        pdf_path = None

        # 1. Chemin stocké en DB (source_pdf)
        if match_db.source_pdf:
            p = Path(match_db.source_pdf)
            if p.exists():
                pdf_path = p

        # 2. Format nouveau: {saison}/{code_match}.pdf
        if not pdf_path:
            p = pdf_base_dir / f"**/{code}.pdf"
            candidates = list(pdf_base_dir.glob(f"**/{code}.pdf"))
            if candidates:
                pdf_path = candidates[0]

        # 3. Index rapide (couvre ancien format {entity}_{code}.pdf)
        if not pdf_path:
            if code in _pdf_index:
                pdf_path = _pdf_index[code]

        if pdf_path:
            match_pdf_pairs.append((match_db, pdf_path))

    if not match_pdf_pairs:
        console.print(
            f"[yellow]Aucun PDF trouvé pour les {len(matches_db)} matchs "
            f"à parser. Téléchargez d'abord avec : pyvolley download[/yellow]"
        )
        raise typer.Exit(0)

    mode_label = "Vérification" if verify else "Enrichissement"
    saison_display = ", ".join(saison) if saison else "toutes"
    entity_display = ", ".join(entity) if entity else "toutes"

    console.print(Panel(
        f"[bold blue]📄 PyVolley - {mode_label} depuis la base (Phase 2)[/bold blue]\n\n"
        f"Matchs en DB:  [cyan]{len(matches_db)}[/cyan] (statuts: {', '.join(statuses)})\n"
        f"PDFs trouvés:  [cyan]{len(match_pdf_pairs)}[/cyan]\n"
        f"Saison(s):     [cyan]{saison_display}[/cyan]\n"
        f"Entité(s):     [cyan]{entity_display}[/cyan]\n"
        f"Parser:        [cyan]{parser.name} v{parser.version}[/cyan]",
        title="Configuration"
    ))

    if dry_run:
        table = Table(title="Matchs à parser")
        table.add_column("Code", style="cyan")
        table.add_column("Statut", style="white")
        table.add_column("Joué", justify="center")
        table.add_column("PDF", style="dim")
        for match_db, pdf_path in match_pdf_pairs[:50]:
            table.add_row(
                match_db.code_match,
                match_db.parsing_status,
                "✓" if match_db.match_joue else "✗",
                pdf_path.name,
            )
        console.print(table)
        if len(match_pdf_pairs) > 50:
            console.print(f"\n[dim]... et {len(match_pdf_pairs) - 50} autres[/dim]")
        console.print(f"\n[yellow]Mode dry-run: aucun fichier parsé[/yellow]")
        raise typer.Exit(0)

    # Parsing et enrichissement
    results = []
    enriched = 0
    skipped_count = 0
    failed = 0
    warnings_count = 0
    error_details = []

    with DatabaseSession() as session:
        service = MatchImportService(session)

        # Audit log
        import_log = ImportLogDB(
            operation="parse-enrich",
            source="from-db",
            total_attempted=len(match_pdf_pairs),
            status="running",
        )
        session.add(import_log)
        session.flush()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            "[", TextColumn("{task.completed}/{task.total}"), "]",
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Parsing + enrichissement...", total=len(match_pdf_pairs))

            for match_db, pdf_path in match_pdf_pairs:
                # Re-fetch le match dans cette session
                match_db_fresh = session.get(MatchDB, match_db.id)
                if not match_db_fresh:
                    skipped_count += 1
                    progress.update(task, advance=1)
                    continue

                try:
                    result = parser.parse(pdf_path)

                    if result.success and result.match:
                        # Enrichir le match en base
                        was_enriched = service.enrich_from_pdf(
                            match_db_fresh, result.match, force=verify or not skip_parsed,
                        )
                        if was_enriched:
                            enriched += 1
                        else:
                            skipped_count += 1

                        results.append({
                            'file': str(pdf_path),
                            'match': result.match,
                            'parse_time_ms': result.parse_time_ms,
                            'diagnostics': result.diagnostics,
                            'db_match_id': match_db_fresh.id,
                            'enriched': was_enriched,
                        })

                        if result.diagnostics:
                            warnings_count += result.warnings_count

                        if verbose and was_enriched:
                            m = result.match
                            progress.console.print(
                                f"  [green]✓[/green] {match_db_fresh.code_match}: "
                                f"enrichi ({m.equipe_a.nom[:20] if m.equipe_a else '?'} vs "
                                f"{m.equipe_b.nom[:20] if m.equipe_b else '?'})"
                            )

                        progress.update(task, advance=1,
                            description=f"[green]✓ {match_db_fresh.code_match}[/green]")
                    else:
                        failed += 1
                        match_db_fresh.parsing_status = "error"
                        match_db_fresh.remarques = (
                            result.errors[0][:200] if result.errors else "Parsing error"
                        )
                        error_details.append({
                            'file': str(pdf_path),
                            'errors': result.errors,
                            'diagnostics': result.diagnostics,
                        })
                        progress.update(task, advance=1,
                            description=f"[red]✗ {match_db_fresh.code_match}[/red]")

                except Exception as e:
                    failed += 1
                    match_db_fresh.parsing_status = "error"
                    match_db_fresh.remarques = str(e)[:200]
                    error_details.append({
                        'file': str(pdf_path),
                        'errors': [str(e)],
                    })
                    progress.update(task, advance=1,
                        description=f"[red]✗ {match_db_fresh.code_match}[/red]")

                # Commit par batch de 100
                if (enriched + failed) % 100 == 0 and (enriched + failed) > 0:
                    try:
                        session.commit()
                    except Exception as e:
                        session.rollback()
                        service.clear_caches()
                        console.print(f"  [red]Erreur batch commit: {e}[/red]")

        # Commit final
        import_log.finished_at = datetime.now()
        import_log.imported = enriched
        import_log.duplicates = skipped_count
        import_log.errors = failed
        import_log.status = (
            "success" if failed == 0
            else "partial" if enriched > 0
            else "failed"
        )
        try:
            session.commit()
        except Exception:
            session.rollback()

    # Résumé
    total_processed = enriched + failed
    console.print("\n" + "=" * 60)
    console.print(Panel(
        f"[green]✓ Enrichis:  {enriched}[/green]\n"
        f"[yellow]⏭ Ignorés:   {skipped_count}[/yellow]\n"
        f"[red]✗ Échecs:    {failed}[/red]\n"
        f"[dim]⚠ Warnings:  {warnings_count}[/dim]",
        title=f"Résumé du {'vérification' if verify else 'parsing'} (Phase 2)"
    ))

    if results or error_details:
        _display_warning_summary(results, error_details, total_processed, console)

    if collect_problems and (results or error_details):
        _collect_problem_files(results, error_details, collect_problems, console)

    if output and results:
        export_data = []
        for r in results:
            match = r['match']
            export_data.append({
                'file': r['file'],
                'parse_time_ms': r['parse_time_ms'],
                'enriched': r.get('enriched', False),
                'match': match.model_dump() if hasattr(match, 'model_dump') else match.dict()
            })
        with open(output, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
        console.print(f"\n[blue]📁 Résultats exportés: {output}[/blue]")

    if report:
        _generate_parse_report(
            input_path=Path("data/pdfs"),
            parser=parser,
            pdf_files=[Path(r['file']) for r in results],
            results=results,
            successful=enriched,
            skipped=skipped_count,
            failed=failed,
            warnings_count=warnings_count,
            error_details=error_details,
            saison=saison,
            entity=entity,
            import_stats={"committed": enriched, "duplicates": skipped_count, "errors": failed},
            force=True,
        )


def _parse_from_files(
    *,
    input_path: Path,
    output: Optional[Path],
    parser_version: str,
    recursive: bool,
    limit: Optional[int],
    random_order: bool,
    skip_parsed: bool,
    save_db: bool,
    report: bool,
    dry_run: bool,
    saison: Optional[List[str]],
    entity: Optional[List[str]],
    clear_cache: bool,
    collect_problems: Optional[Path],
    verbose: bool,
) -> None:
    """Parse des PDFs depuis le système de fichiers (mode original)."""
    from pyvolley.parsers.factory import ParserFactory
    from hashlib import md5

    if not input_path.exists():
        console.print(f"[red]Erreur: {input_path} n'existe pas[/red]")
        raise typer.Exit(1)

    # ── Collecte des fichiers PDF ──────────────────────────────────────
    if input_path.is_dir():
        pdf_files = list(input_path.glob("**/*.pdf" if recursive else "*.pdf"))
    else:
        pdf_files = [input_path]

    if not pdf_files:
        console.print("[yellow]Aucun fichier PDF trouvé[/yellow]")
        raise typer.Exit(0)

    # ── Filtres saison / entité ────────────────────────────────────────
    if saison:
        normalized_saisons = [s.replace("/", "-") for s in saison]
        pdf_files = [f for f in pdf_files if any(ns in str(f) for ns in normalized_saisons)]

    if entity:
        pdf_files = [f for f in pdf_files if any(e in str(f) for e in entity)]

    if not pdf_files:
        console.print("[yellow]Aucun fichier PDF après filtres[/yellow]")
        raise typer.Exit(0)

    # Tri déterministe ou aléatoire
    if random_order:
        import random
        random.shuffle(pdf_files)
    else:
        pdf_files.sort()

    if limit:
        pdf_files = pdf_files[:limit]

    # ── Cache de parsing ───────────────────────────────────────────────
    cache_dir = input_path if input_path.is_dir() else input_path.parent
    cache_file = cache_dir / ".pyvolley_parse_cache.json"
    parsed_cache: dict = {}

    if clear_cache and cache_file.exists():
        cache_file.unlink()
        console.print("[yellow]Cache de parsing vidé[/yellow]")

    if skip_parsed and cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                parsed_cache = json.load(f)
            console.print(f"[dim]Cache chargé: {len(parsed_cache)} fichiers déjà parsés[/dim]")
        except Exception:
            parsed_cache = {}

    # ── Afficher le résumé ─────────────────────────────────────────────
    saison_display = ", ".join(saison) if saison else "toutes"
    entity_display = ", ".join(entity) if entity else "toutes"

    console.print(Panel(
        f"[bold blue]📄 PyVolley - Parsing des feuilles de match[/bold blue]\n\n"
        f"Source:       [cyan]{input_path}[/cyan]\n"
        f"Fichiers:     [cyan]{len(pdf_files)}[/cyan]\n"
        f"Saison(s):    [cyan]{saison_display}[/cyan]\n"
        f"Entité(s):    [cyan]{entity_display}[/cyan]\n"
        f"Parser:       [cyan]auto[/cyan]\n"
        f"Mode:         [cyan]{'Aperçu (dry-run)' if dry_run else 'Parsing'}[/cyan]\n"
        f"Sauvegarde DB: [cyan]{'Oui' if save_db else 'Non'}[/cyan]",
        title="Configuration"
    ))

    # ── Mode dry-run ───────────────────────────────────────────────────
    if dry_run:
        from collections import Counter
        saisons_count: Counter = Counter()
        entities_count: Counter = Counter()
        for f in pdf_files:
            for p in f.parts:
                if p and len(p) == 9 and p[4] == '-':
                    saisons_count[p] += 1
                if p and (p.startswith("LI") or p.startswith("PT") or p.startswith("AB") or p.startswith("AC")):
                    entities_count[p] += 1

        if saisons_count:
            console.print("\n[bold]Distribution par saison:[/bold]")
            for s, c in sorted(saisons_count.items()):
                console.print(f"  {s}: {c}")
        if entities_count:
            console.print("\n[bold]Distribution par entité (top 10):[/bold]")
            for e, c in entities_count.most_common(10):
                console.print(f"  {e}: {c}")

        console.print(f"\n[yellow]Mode dry-run: aucun fichier parsé[/yellow]")
        raise typer.Exit(0)

    # ── Créer le parser ────────────────────────────────────────────────
    try:
        if parser_version == "auto":
            parser = ParserFactory.get_default()
        else:
            parser = ParserFactory.get(parser_version)
    except KeyError:
        console.print(f"[red]Parser '{parser_version}' non trouvé[/red]")
        console.print(f"[blue]Parsers disponibles: {ParserFactory.list_parsers()}[/blue]")
        raise typer.Exit(1)

    console.print(f"\n[blue]Utilisation du parser: {parser.name} v{parser.version}[/blue]\n")

    # ── Parsing ────────────────────────────────────────────────────────
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
            # Vérifier le cache (skip re-parsing, pas l'import DB)
            file_hash: Optional[str] = None
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
                        'diagnostics': result.diagnostics,
                    })

                    if result.diagnostics:
                        warnings_count += result.warnings_count

                    # Mettre en cache
                    if skip_parsed and cache_file:
                        if file_hash is None:
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
                        if result.diagnostics:
                            for diag_item in result.diagnostics:
                                progress.console.print(f"      [yellow]⚠ {diag_item}[/yellow]")
                        progress.update(task, advance=1)
                    else:
                        progress.update(task, advance=1, description=f"[green]✓ {pdf_file.name[:30]}[/green]")
                else:
                    failed += 1
                    error_details.append({
                        'file': str(pdf_file),
                        'errors': result.errors,
                        'diagnostics': result.diagnostics,
                    })
                    if verbose:
                        msg = result.errors[0][:50] if result.errors else 'Erreur inconnue'
                        progress.console.print(f"  [red]✗[/red] {pdf_file.name}: {msg}...")
                        if result.diagnostics:
                            for diag_item in result.diagnostics:
                                progress.console.print(f"      [yellow]⚠ {diag_item}[/yellow]")
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

    # ── Sauvegarder le cache ───────────────────────────────────────────
    if skip_parsed and cache_file and parsed_cache:
        try:
            with open(cache_file, "w") as f:
                json.dump(parsed_cache, f)
        except Exception:
            pass

    # ── Résumé ─────────────────────────────────────────────────────────
    total_parsed = successful + failed
    console.print("\n" + "=" * 60)
    console.print(Panel(
        f"[green]✓ Parsés avec succès: {successful}[/green]\n"
        f"[yellow]⏭ Skippés (cache): {skipped}[/yellow]\n"
        f"[red]✗ Échecs: {failed}[/red]\n"
        f"[dim]⚠ Warnings: {warnings_count}[/dim]",
        title="Résumé du parsing"
    ))

    # ── Récapitulatif des warnings par catégorie ───────────────────────
    if results or error_details:
        _display_warning_summary(results, error_details, total_parsed, console)

    # ── Collection des fichiers problématiques ─────────────────────────
    if collect_problems and (results or error_details):
        _collect_problem_files(results, error_details, collect_problems, console)

    # ── Exporter en JSON ───────────────────────────────────────────────
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

    # ── Import en base de données ──────────────────────────────────────
    import_stats: Optional[dict] = None
    if save_db and results:
        console.print("\n[blue]💾 Sauvegarde en base de données...[/blue]")

        try:
            from pyvolley.database.connection import DatabaseSession, init_db
            from pyvolley.database.import_service import MatchImportService
            from pyvolley.database.models import ImportLogDB

            init_db()

            committed = 0
            imported = 0
            import_errors = 0
            import_error_details: list[dict] = []
            duplicates = 0
            batch_imported = 0
            BATCH_SIZE = 200

            with DatabaseSession() as session:
                service = MatchImportService(session)

                import_log = ImportLogDB(
                    operation="parse",
                    source=str(input_path),
                    total_attempted=len(results),
                    status="running",
                )
                session.add(import_log)
                session.flush()

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                    transient=True,
                ) as db_progress:
                    db_task = db_progress.add_task("Import DB...", total=len(results))

                    for idx, r in enumerate(results):
                        try:
                            match_db = service.import_match(r['match'])
                            if match_db:
                                imported += 1
                                batch_imported += 1
                            else:
                                duplicates += 1
                        except Exception as e:
                            import_errors += 1
                            import_error_details.append({
                                "code_match": r['match'].code_match,
                                "error": str(e),
                            })
                            session.rollback()
                            service.clear_caches()
                            imported -= batch_imported
                            batch_imported = 0
                            session.add(import_log)
                            session.flush()
                            if verbose:
                                console.print(f"  [red]✗[/red] Import {r['match'].code_match}: {e}")

                        if batch_imported > 0 and (idx + 1) % BATCH_SIZE == 0:
                            try:
                                session.commit()
                                committed += batch_imported
                                batch_imported = 0
                            except Exception as e:
                                session.rollback()
                                service.clear_caches()
                                import_error_details.append({"batch_commit": str(e), "index": idx})
                                imported -= batch_imported
                                batch_imported = 0
                                session.add(import_log)
                                session.flush()

                        db_progress.update(db_task, advance=1)

                # Commit final
                if batch_imported > 0:
                    try:
                        session.commit()
                        committed += batch_imported
                    except Exception as e:
                        session.rollback()
                        service.clear_caches()
                        import_error_details.append({"final_commit": str(e)})
                        imported -= batch_imported
                        session.add(import_log)
                        session.flush()

                import_log.finished_at = datetime.now()
                import_log.imported = committed
                import_log.duplicates = duplicates
                import_log.errors = import_errors
                if import_error_details:
                    import_log.error_details = json.dumps(
                        import_error_details[:100], ensure_ascii=False
                    )
                import_log.status = (
                    "success" if import_errors == 0
                    else "partial" if committed > 0
                    else "failed"
                )
                try:
                    session.commit()
                except Exception:
                    session.rollback()

            import_stats = {
                "committed": committed,
                "duplicates": duplicates,
                "errors": import_errors,
                "error_details": import_error_details,
            }

            console.print(f"[green]✓ {committed} matchs importés en base de données[/green]")
            if duplicates:
                console.print(f"[dim]↳ {duplicates} matchs déjà existants (ignorés)[/dim]")
            if import_errors:
                console.print(f"[red]✗ {import_errors} erreurs d'import[/red]")
                for err in import_error_details[:5]:
                    code = err.get("code_match", err.get("batch_commit", "?"))
                    msg = err.get("error", err.get("batch_commit", ""))
                    console.print(f"  [red]↳ {code}: {msg[:80]}[/red]")
                if import_errors > 5:
                    console.print(f"  [dim]... et {import_errors - 5} autres erreurs[/dim]")
            if committed != imported:
                console.print(
                    f"[yellow]⚠ Note : {imported - committed} matchs traités mais non "
                    f"commités (perdus lors de rollbacks d'erreur)[/yellow]"
                )

        except Exception as e:
            console.print(f"[red]Erreur lors de l'import en base: {e}[/red]")

    # ── Rapport ────────────────────────────────────────────────────────
    _generate_parse_report(
        input_path=input_path,
        parser=parser,
        pdf_files=pdf_files,
        results=results,
        successful=successful,
        skipped=skipped,
        failed=failed,
        warnings_count=warnings_count,
        error_details=error_details,
        saison=saison,
        entity=entity,
        import_stats=import_stats,
        force=report or save_db,
    )


# ============== Commande Parse-Status ==============

@app.command("parse-status")
def parse_status(
    saison: Optional[str] = typer.Option(
        None,
        "--saison", "-s",
        help="Filtrer par saison (ex: 2024-2025)"
    ),
    entity: Optional[str] = typer.Option(
        None,
        "--entity", "-e",
        help="Filtrer par entité (ex: ABCCS)"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Afficher le détail par saison/entité"
    ),
):
    """
    📊 Affiche un tableau de bord du statut de parsing des matchs.

    Donne une vue d'ensemble du pipeline Phase 1 → Phase 2 :
    combien de matchs sont découverts, téléchargés, parsés, en erreur.

    Exemples:

        pyvolley parse-status

        pyvolley parse-status -s 2024-2025

        pyvolley parse-status --verbose
    """
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import MatchDB, SaisonDB, CompetitionDB, EntiteFFVBDB
    from sqlalchemy import select, func

    init_db()

    with DatabaseSession() as session:
        service = MatchImportService(session)

        # Filtres optionnels
        base_filter = select(MatchDB)
        saison_name = None
        entity_name = None

        if saison:
            normalized = saison.replace("/", "-")
            saison_db = session.scalars(
                select(SaisonDB).where(SaisonDB.code == normalized)
            ).first()
            if saison_db:
                base_filter = base_filter.where(MatchDB.saison_id == saison_db.id)
                saison_name = saison_db.code
            else:
                console.print(f"[yellow]Saison '{saison}' non trouvée[/yellow]")
                raise typer.Exit(1)

        if entity:
            entite_db = session.scalars(
                select(EntiteFFVBDB).where(EntiteFFVBDB.code == entity)
            ).first()
            if entite_db:
                comp_ids = [c.id for c in session.scalars(
                    select(CompetitionDB).where(CompetitionDB.entite_id == entite_db.id)
                ).all()]
                if comp_ids:
                    base_filter = base_filter.where(MatchDB.competition_id.in_(comp_ids))
                entity_name = entite_db.code
            else:
                console.print(f"[yellow]Entité '{entity}' non trouvée[/yellow]")
                raise typer.Exit(1)

        # Comptages globaux par statut
        status_counts: dict[str, int] = {}
        for status in ["discovered", "downloaded", "parsed", "error"]:
            count = session.scalar(
                select(func.count()).select_from(
                    base_filter.where(MatchDB.parsing_status == status).subquery()
                )
            )
            status_counts[status] = count or 0

        total = sum(status_counts.values())
        # Matchs joués vs non joués
        played = session.scalar(
            select(func.count()).select_from(
                base_filter.where(MatchDB.match_joue == True).subquery()  # noqa: E712
            )
        ) or 0
        not_played = total - played

        # Codes de matchs en base
        all_db_codes = set(session.scalars(select(MatchDB.code_match)).all())

        # Matchs avec PDF disponible
        pdf_base = Path("data/pdfs")
        pdf_count = 0
        pdf_total_size = 0
        pdf_codes_on_disk: set[str] = set()
        if pdf_base.exists():
            for pdf_file in pdf_base.glob("**/*.pdf"):
                pdf_count += 1
                pdf_total_size += pdf_file.stat().st_size
                stem = pdf_file.stem
                code = stem.split("_", 1)[1] if "_" in stem else stem
                pdf_codes_on_disk.add(code)
                pdf_codes_on_disk.add(stem)

        # Calculer les orphelins (PDFs sans match en DB)
        orphan_count = len(pdf_codes_on_disk - all_db_codes) if pdf_codes_on_disk else 0
        pdf_size_display = f"{pdf_total_size / (1024**3):.2f} Go" if pdf_total_size > 1024**3 else f"{pdf_total_size / (1024**2):.0f} Mo"

        # Tableau principal
        filter_label = ""
        if saison_name:
            filter_label += f" | Saison: {saison_name}"
        if entity_name:
            filter_label += f" | Entité: {entity_name}"

        table = Table(
            title=f"📊 Statut du parsing{filter_label}",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Statut", style="bold")
        table.add_column("Nombre", justify="right")
        table.add_column("Proportion", justify="right")
        table.add_column("Description")

        status_info = {
            "discovered": ("🔍 Découvert", "cyan", "Trouvé via scraping Phase 1, PDF non téléchargé"),
            "downloaded": ("📥 Téléchargé", "blue", "PDF téléchargé, pas encore parsé"),
            "parsed": ("✅ Parsé", "green", "PDF parsé et données enrichies en base"),
            "error": ("❌ Erreur", "red", "Échec du parsing ou du téléchargement"),
        }

        for status, count in status_counts.items():
            label, color, desc = status_info.get(status, (status, "white", ""))
            pct = f"{count / total * 100:.1f}%" if total > 0 else "0%"
            table.add_row(f"[{color}]{label}[/{color}]", str(count), pct, desc)

        table.add_section()
        table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]", "100%", "")
        table.add_row("[dim]↳ Joués[/dim]", f"[dim]{played}[/dim]", "", "")
        table.add_row("[dim]↳ Non joués[/dim]", f"[dim]{not_played}[/dim]", "", "")
        table.add_row(
            "[dim]↳ PDFs locaux[/dim]",
            f"[dim]{pdf_count}[/dim]",
            "",
            f"[dim]{pdf_size_display}[/dim]",
        )
        if orphan_count > 0:
            table.add_row(
                "[yellow]↳ PDFs orphelins[/yellow]",
                f"[yellow]{orphan_count}[/yellow]",
                "",
                "[yellow]Pas de match en DB[/yellow]",
            )

        console.print(table)

        # Barre de progression visuelle
        if total > 0:
            parsed_pct = status_counts["parsed"] / total * 100
            console.print(
                f"\n[bold]Progression du parsing :[/bold] "
                f"[green]{'█' * int(parsed_pct // 2)}[/green]"
                f"[dim]{'░' * (50 - int(parsed_pct // 2))}[/dim] "
                f"[bold]{parsed_pct:.1f}%[/bold]"
            )

        # Mode verbose: détail par saison
        if verbose:
            console.print("\n[bold]Détail par saison :[/bold]")
            saisons = session.scalars(select(SaisonDB).order_by(SaisonDB.code)).all()

            detail_table = Table(show_header=True, header_style="bold")
            detail_table.add_column("Saison")
            detail_table.add_column("Total", justify="right")
            detail_table.add_column("Joués", justify="right")
            detail_table.add_column("Discovered", justify="right", style="cyan")
            detail_table.add_column("Downloaded", justify="right", style="blue")
            detail_table.add_column("Parsed", justify="right", style="green")
            detail_table.add_column("Error", justify="right", style="red")
            detail_table.add_column("Progress")

            for s in saisons:
                counts = {}
                s_total = 0
                for st_key in ["discovered", "downloaded", "parsed", "error"]:
                    c = session.scalar(
                        select(func.count(MatchDB.id)).where(
                            MatchDB.saison_id == s.id,
                            MatchDB.parsing_status == st_key,
                        )
                    ) or 0
                    counts[st_key] = c
                    s_total += c

                if s_total == 0:
                    continue

                s_played = session.scalar(
                    select(func.count(MatchDB.id)).where(
                        MatchDB.saison_id == s.id,
                        MatchDB.match_joue == True,  # noqa: E712
                    )
                ) or 0

                s_pct = counts["parsed"] / s_total * 100 if s_total > 0 else 0
                bar = f"{'█' * int(s_pct // 5)}{'░' * (20 - int(s_pct // 5))}"

                detail_table.add_row(
                    s.code,
                    str(s_total),
                    str(s_played),
                    str(counts["discovered"]),
                    str(counts["downloaded"]),
                    str(counts["parsed"]),
                    str(counts["error"]),
                    f"[green]{bar}[/green] {s_pct:.0f}%",
                )

            console.print(detail_table)

        # Suggestion d'action
        if status_counts["discovered"] > 0:
            console.print(
                f"\n[yellow]💡 {status_counts['discovered']} matchs en attente de téléchargement. "
                f"Exécutez: pyvolley download --from-db[/yellow]"
            )
        if status_counts["downloaded"] > 0:
            console.print(
                f"[yellow]💡 {status_counts['downloaded']} matchs en attente de parsing. "
                f"Exécutez: pyvolley parse --from-db[/yellow]"
            )
        if status_counts["error"] > 0:
            console.print(
                f"[yellow]💡 {status_counts['error']} matchs en erreur. "
                f"Exécutez: pyvolley parse --from-db --status error --force[/yellow]"
            )
        if status_counts["parsed"] > 0 and pdf_count > 0:
            console.print(
                f"[yellow]💡 Des PDFs peuvent être nettoyés. "
                f"Exécutez: pyvolley cleanup pdfs --dry-run[/yellow]"
            )
        if orphan_count > 0:
            console.print(
                f"[yellow]💡 {orphan_count} PDFs orphelins (pas de match en DB). "
                f"Exécutez: pyvolley cleanup orphans --dry-run[/yellow]"
            )


# ============== Commande Pipeline ==============

@app.command()
def pipeline(
    entity: Optional[List[str]] = typer.Option(
        None,
        "--entity", "-e",
        help="Entité(s) à traiter. Répétable."
    ),
    saison: Optional[List[str]] = typer.Option(
        None,
        "--saison", "-s",
        help="Saison(s) à traiter. Répétable."
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit", "-n",
        help="Nombre maximum de matchs à traiter"
    ),
    skip_scrape: bool = typer.Option(
        False,
        "--skip-scrape",
        help="Sauter l'étape de scraping (Phase 1)"
    ),
    skip_download: bool = typer.Option(
        False,
        "--skip-download",
        help="Sauter l'étape de téléchargement"
    ),
    skip_parse: bool = typer.Option(
        False,
        "--skip-parse",
        help="Sauter l'étape de parsing"
    ),
    keep_pdfs: bool = typer.Option(
        True,
        "--keep-pdfs/--no-keep-pdfs",
        help="Conserver les PDFs après parsing. Avec --no-keep-pdfs, les PDFs "
             "sont supprimés une fois parsés et stockés en DB (économise l'espace disque)."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="N'effectuer aucune action, afficher le plan d'exécution"
    ),
    enrich_clubs: bool = typer.Option(
        True,
        "--enrich-clubs/--no-enrich-clubs",
        help="Enrichit les clubs avec les données de l'adressier FFVB lors du scraping. Activé par défaut."
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Affichage détaillé"
    ),
):
    """
    🔄 Pipeline complet : scrape → download → parse.

    Exécute les trois phases du pipeline de données dans l'ordre :
    1. Scrape (Phase 1) : récupère les données CSV depuis les exports FFVB
    2. Download : télécharge les PDFs des feuilles de match
    3. Parse (Phase 2) : parse les PDFs et enrichit la base de données

    Avec --no-keep-pdfs, les PDFs sont supprimés après avoir été parsés
    et stockés en base. C'est le mode recommandé si vous ne souhaitez pas
    conserver les fichiers intermédiaires (économise plusieurs Go d'espace).

    Exemples:

        # Pipeline complet pour une saison
        pyvolley pipeline -s 2024-2025

        # Pipeline sans conserver les PDFs (mode streaming)
        pyvolley pipeline -s 2024-2025 --no-keep-pdfs

        # Pipeline pour une entité, sans scraping
        pyvolley pipeline -e ABCCS --skip-scrape

        # Visualiser le plan sans exécuter
        pyvolley pipeline -s 2024-2025 --dry-run

        # Download + parse seulement (après un scraping déjà fait)
        pyvolley pipeline -s 2024-2025 --skip-scrape
    """
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import MatchDB, SaisonDB
    from sqlalchemy import select, func

    init_db()

    steps = []
    if not skip_scrape:
        steps.append("scrape")
    if not skip_download:
        steps.append("download")
    if not skip_parse:
        steps.append("parse")

    if not steps:
        console.print("[yellow]Toutes les étapes sont désactivées. Rien à faire.[/yellow]")
        raise typer.Exit(0)

    # Afficher le plan
    saison_display = ", ".join(saison) if saison else "toutes"
    entity_display = ", ".join(entity) if entity else "toutes"

    console.print(Panel(
        f"[bold blue]🔄 PyVolley - Pipeline de données[/bold blue]\n\n"
        f"Étapes:     [cyan]{' → '.join(steps)}[/cyan]\n"
        f"Saison(s):  [cyan]{saison_display}[/cyan]\n"
        f"Entité(s):  [cyan]{entity_display}[/cyan]\n"
        f"Limite:     [cyan]{limit or 'aucune'}[/cyan]\n"
        f"Mode:       [cyan]{'Aperçu (dry-run)' if dry_run else 'Exécution'}[/cyan]",
        title="Configuration du pipeline"
    ))

    if dry_run:
        with DatabaseSession() as session:
            for status in ["discovered", "downloaded", "parsed", "error"]:
                count = session.scalar(
                    select(func.count(MatchDB.id)).where(
                        MatchDB.parsing_status == status
                    )
                ) or 0
                console.print(f"  {status}: {count}")

        console.print("\n[yellow]Mode dry-run: aucune action effectuée[/yellow]")

        if "scrape" in steps:
            console.print("\n[bold]Étape 1 - Scrape :[/bold]")
            console.print("  → Exécuterait: pyvolley scrape" +
                (f" -e {' -e '.join(entity)}" if entity else "") +
                (f" -s {' -s '.join(saison)}" if saison else "")
            )

        if "download" in steps:
            console.print("\n[bold]Étape 2 - Download :[/bold]")
            console.print("  → Exécuterait: pyvolley download --from-db" +
                (f" -s {' -s '.join(saison)}" if saison else "")
            )

        if "parse" in steps:
            console.print("\n[bold]Étape 3 - Parse :[/bold]")
            console.print("  → Exécuterait: pyvolley parse --from-db" +
                (f" -s {' -s '.join(saison)}" if saison else "") +
                (f" -e {' -e '.join(entity)}" if entity else "") +
                (f" -n {limit}" if limit else "")
            )
        raise typer.Exit(0)

    # ── Étape 1 : Scrape ───────────────────────────────────────────────
    if "scrape" in steps:
        console.print("\n[bold blue]═══ Étape 1/3 : Scrape (Phase 1) ═══[/bold blue]")
        try:
            from pyvolley.scrapers.ffvb import FFVBScraper
            from pyvolley.database.connection import DatabaseSession
            from pyvolley.database.export_import_service import ExportImportService

            scraper_p = FFVBScraper()
            entities_to_scrape = entity if entity else []

            if not entities_to_scrape:
                console.print("  [yellow]Aucune entité spécifiée pour le scraping. "
                              "Utilisez -e CODE.[/yellow]")
            else:
                saisons_p = saison if saison else [scraper_p._get_current_saison()]
                for target_entity in entities_to_scrape:
                    for target_saison in saisons_p:
                        try:
                            with console.status(
                                f"[bold blue]Récupération export CSV {target_entity} "
                                f"saison {target_saison}..."
                            ):
                                export_data = scraper_p.scrape_entity(
                                    target_entity, target_saison,
                                )
                            if export_data:
                                with DatabaseSession() as session:
                                    import_service = ExportImportService(session)
                                    result = import_service.import_matches(
                                        export_data, target_entity, target_saison,
                                    )

                                    # Enrichissement clubs (adressier) — comme dans `scrape`
                                    if enrich_clubs:
                                        try:
                                            from pyvolley.scrapers.ffvb.adressier_scraper import fetch_adressier
                                            from pyvolley.scrapers.ffvb.export_scraper import get_unique_poules
                                            poules = get_unique_poules(export_data)
                                            poule_codes = sorted(poules.keys())
                                            with console.status(
                                                f"[bold magenta]Enrichissement clubs {target_entity} "
                                                f"({len(poule_codes)} poules)..."
                                            ):
                                                clubs_info = fetch_adressier(
                                                    scraper_p.client, scraper_p.base_url,
                                                    target_entity, target_saison, poule_codes,
                                                )
                                            if clubs_info:
                                                club_stats = import_service.enrich_clubs(
                                                    clubs_info, target_entity,
                                                    target_saison, scraper_p.base_url,
                                                )
                                                enriched = club_stats.get("enriched", 0) + club_stats.get("created", 0)
                                                console.print(
                                                    f"  [magenta]Clubs: {enriched} enrichis/créés[/magenta]"
                                                )
                                        except Exception as e:
                                            console.print(
                                                f"  [red]Erreur enrichissement clubs: {e}[/red]"
                                            )

                                    session.commit()
                                    console.print(
                                        f"  [green]✓[/green] Scrape {target_entity} "
                                        f"saison {target_saison}: "
                                        f"{result.get('imported', 0)} importés, "
                                        f"{result.get('updated', 0)} mis à jour"
                                    )
                        except Exception as e:
                            console.print(
                                f"  [red]✗[/red] Erreur scrape {target_entity}: {e}"
                            )
        except Exception as e:
            console.print(f"[red]Erreur Phase 1: {e}[/red]")

    # ── Étape 2 : Download ─────────────────────────────────────────────
    if "download" in steps:
        console.print("\n[bold blue]═══ Étape 2/3 : Download des PDFs ═══[/bold blue]")

        if not keep_pdfs and "parse" in steps:
            # Mode streaming : download + parse en une passe, puis suppression
            console.print("[dim]  Mode streaming : les PDFs seront parsés puis supprimés[/dim]")
            try:
                _stream_download_parse(
                    limit=limit,
                    saison=saison,
                    entity=entity,
                    verbose=verbose,
                )
            except SystemExit:
                pass
            except Exception as e:
                console.print(f"[red]Erreur streaming: {e}[/red]")
            # Le parse a déjà été fait, on le saute
            steps = [s for s in steps if s != "parse"]
        else:
            try:
                _download_from_db(
                    limit=limit,
                    saison=saison,
                    verbose=verbose,
                )
            except SystemExit:
                pass
            except Exception as e:
                console.print(f"[red]Erreur Download: {e}[/red]")

    # ── Étape 3 : Parse ────────────────────────────────────────────────
    if "parse" in steps:
        console.print("\n[bold blue]═══ Étape 3/3 : Parsing (Phase 2) ═══[/bold blue]")
        try:
            _parse_from_db(
                status_filter=None,
                played_only=True,
                parser_version="auto",
                limit=limit,
                skip_parsed=True,
                dry_run=False,
                saison=saison,
                entity=entity,
                verbose=verbose,
                verify=False,
                report=True,
                output=None,
                collect_problems=None,
            )
        except SystemExit:
            pass  # typer.Exit est attendu
        except Exception as e:
            console.print(f"[red]Erreur Parse: {e}[/red]")

        # Nettoyage post-parse si --no-keep-pdfs
        if not keep_pdfs:
            _cleanup_parsed_pdfs(saison=saison, verbose=verbose)

    # Résumé final
    console.print("\n" + "═" * 60)
    console.print(Panel(
        f"[bold green]Pipeline terminé[/bold green]\n"
        f"Étapes exécutées: {', '.join(steps)}"
        + ("\n[dim]PDFs supprimés après parsing[/dim]" if not keep_pdfs else ""),
        title="✅ Terminé"
    ))


def _download_from_db(
    *,
    limit: Optional[int] = None,
    saison: Optional[List[str]] = None,
    verbose: bool = False,
) -> None:
    """Télécharge les PDFs des matchs trouvés en DB avec statut 'discovered'.

    Cherche les matchs joués qui ont une source_url mais pas de PDF local,
    les télécharge, et met à jour le parsing_status → 'downloaded'.

    Le fichier est stocké sous ``data/pdfs/{saison}/{code_match}.pdf``
    (structure plate par saison, cohérente avec la recherche de
    ``_parse_from_db``).
    """
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import MatchDB, SaisonDB
    from sqlalchemy import select

    init_db()

    with DatabaseSession() as session:
        stmt = (
            select(MatchDB)
            .where(
                MatchDB.parsing_status == "discovered",
                MatchDB.match_joue == True,  # noqa: E712
                MatchDB.source_url.isnot(None),
            )
        )

        if saison:
            normalized = [s.replace("/", "-") for s in saison]
            saison_ids = [
                s.id for s in session.scalars(
                    select(SaisonDB).where(SaisonDB.code.in_(normalized))
                ).all()
            ]
            if saison_ids:
                stmt = stmt.where(MatchDB.saison_id.in_(saison_ids))

        stmt = stmt.order_by(MatchDB.code_match)
        if limit:
            stmt = stmt.limit(limit)

        matches = list(session.scalars(stmt).all())

    if not matches:
        console.print("[yellow]Aucun match à télécharger (pas de matchs avec statut 'discovered')[/yellow]")
        return

    console.print(f"[blue]📥 {len(matches)} matchs à télécharger[/blue]")

    import httpx
    pdf_base = Path("data/pdfs")
    downloaded = 0
    dl_failed = 0

    # Construire un index des PDFs existants pour une recherche rapide
    # au lieu de faire un glob par match (O(n²) → O(n))
    _pdf_index: dict[str, Path] = {}
    if pdf_base.exists():
        for pdf_file in pdf_base.glob("**/*.pdf"):
            stem = pdf_file.stem  # ex: "ABCCS_2FA001" ou "2FA001"
            _pdf_index[stem] = pdf_file
            # Si le nom contient un underscore (ancien format: {entity}_{code}),
            # indexer aussi par la partie après l'underscore  (le code match)
            if "_" in stem:
                code_part = stem.split("_", 1)[1]
                if code_part not in _pdf_index:
                    _pdf_index[code_part] = pdf_file

    with httpx.Client(timeout=30, follow_redirects=True) as http:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            dl_task = progress.add_task("Téléchargement...", total=len(matches))

            with DatabaseSession() as session:
                for match_db in matches:
                    match_fresh = session.get(MatchDB, match_db.id)
                    if not match_fresh or not match_fresh.source_url:
                        progress.update(dl_task, advance=1)
                        continue

                    # Déterminer le dossier de destination
                    saison_db = session.get(SaisonDB, match_fresh.saison_id) if match_fresh.saison_id else None
                    saison_code = saison_db.code if saison_db else "unknown"

                    dest_dir = pdf_base / saison_code
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest_file = dest_dir / f"{match_fresh.code_match}.pdf"

                    # Vérifier si le PDF existe déjà (nouveau ou ancien format)
                    already_exists = False
                    if dest_file.exists():
                        already_exists = True
                        if not match_fresh.source_pdf:
                            match_fresh.source_pdf = str(dest_file)
                    elif match_fresh.code_match in _pdf_index:
                        # Trouvé dans l'index (ancien format {entity}_{code}.pdf
                        # ou fichier dans un autre répertoire de saison)
                        already_exists = True
                        match_fresh.source_pdf = str(_pdf_index[match_fresh.code_match])

                    if already_exists:
                        match_fresh.parsing_status = "downloaded"
                        downloaded += 1
                        progress.update(dl_task, advance=1)
                        continue

                    try:
                        response = http.get(match_fresh.source_url)
                        response.raise_for_status()

                        # Vérifier que c'est bien un PDF
                        if not response.content[:5].startswith(b"%PDF"):
                            raise ValueError("Réponse non-PDF reçue")

                        dest_file.write_bytes(response.content)
                        match_fresh.parsing_status = "downloaded"
                        match_fresh.source_pdf = str(dest_file)
                        downloaded += 1

                        if verbose:
                            progress.console.print(
                                f"  [green]✓[/green] {match_fresh.code_match} → {dest_file}"
                            )

                    except Exception as e:
                        dl_failed += 1
                        match_fresh.parsing_status = "error"
                        match_fresh.remarques = f"Download error: {str(e)[:100]}"
                        if verbose:
                            progress.console.print(
                                f"  [red]✗[/red] {match_fresh.code_match}: {e}"
                            )

                    progress.update(dl_task, advance=1)

                    # Commit par batch
                    if (downloaded + dl_failed) % 50 == 0 and (downloaded + dl_failed) > 0:
                        try:
                            session.commit()
                        except Exception:
                            session.rollback()

                try:
                    session.commit()
                except Exception:
                    session.rollback()

    console.print(
        f"\n[green]✓ {downloaded} PDFs téléchargés[/green]"
        + (f" | [red]{dl_failed} échecs[/red]" if dl_failed else "")
    )


def _stream_download_parse(
    *,
    limit: Optional[int] = None,
    saison: Optional[List[str]] = None,
    entity: Optional[List[str]] = None,
    verbose: bool = False,
) -> None:
    """Télécharge et parse les matchs en streaming, sans conserver les PDFs.

    Pour chaque match « discovered » en DB :
    1. Télécharge le PDF dans un fichier temporaire
    2. Parse immédiatement
    3. Enrichit la base de données
    4. Supprime le fichier temporaire

    Ce mode est idéal quand on ne souhaite pas stocker les fichiers
    intermédiaires (économise plusieurs Go d'espace disque).
    """
    import tempfile
    import httpx
    from pyvolley.parsers.factory import ParserFactory
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import MatchDB, SaisonDB, ImportLogDB
    from sqlalchemy import select

    init_db()
    parser = ParserFactory.get_default()

    with DatabaseSession() as session:
        stmt = (
            select(MatchDB)
            .where(
                MatchDB.parsing_status == "discovered",
                MatchDB.match_joue == True,  # noqa: E712
                MatchDB.source_url.isnot(None),
            )
        )

        if saison:
            normalized = [s.replace("/", "-") for s in saison]
            saison_ids = [
                s.id for s in session.scalars(
                    select(SaisonDB).where(SaisonDB.code.in_(normalized))
                ).all()
            ]
            if saison_ids:
                stmt = stmt.where(MatchDB.saison_id.in_(saison_ids))

        if entity:
            from pyvolley.database.models import EntiteFFVBDB, CompetitionDB
            entite_ids = [
                e.id for e in session.scalars(
                    select(EntiteFFVBDB).where(EntiteFFVBDB.code.in_(entity))
                ).all()
            ]
            if entite_ids:
                comp_ids = [
                    c.id for c in session.scalars(
                        select(CompetitionDB).where(
                            CompetitionDB.entite_id.in_(entite_ids)
                        )
                    ).all()
                ]
                if comp_ids:
                    stmt = stmt.where(MatchDB.competition_id.in_(comp_ids))

        stmt = stmt.order_by(MatchDB.code_match)
        if limit:
            stmt = stmt.limit(limit)

        matches = list(session.scalars(stmt).all())

    if not matches:
        console.print("[yellow]Aucun match à traiter en streaming[/yellow]")
        return

    console.print(Panel(
        f"[bold blue]⚡ Streaming : download → parse → DB[/bold blue]\n\n"
        f"Matchs à traiter : [cyan]{len(matches)}[/cyan]\n"
        f"Parser :           [cyan]{parser.name} v{parser.version}[/cyan]\n"
        f"Mode :             [cyan]Streaming (PDFs non conservés)[/cyan]",
        title="Configuration"
    ))

    downloaded = 0
    enriched = 0
    failed = 0

    with httpx.Client(timeout=30, follow_redirects=True) as http:
        with DatabaseSession() as session:
            service = MatchImportService(session)

            import_log = ImportLogDB(
                operation="stream-pipeline",
                source="streaming",
                total_attempted=len(matches),
                status="running",
            )
            session.add(import_log)
            session.flush()

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                "[", TextColumn("{task.completed}/{task.total}"), "]",
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    "Streaming...", total=len(matches)
                )

                for match_db in matches:
                    match_fresh = session.get(MatchDB, match_db.id)
                    if not match_fresh or not match_fresh.source_url:
                        progress.update(task, advance=1)
                        continue

                    try:
                        # 1. Télécharger dans un fichier temporaire
                        response = http.get(match_fresh.source_url)
                        response.raise_for_status()

                        if not response.content[:5].startswith(b"%PDF"):
                            raise ValueError("Réponse non-PDF")

                        with tempfile.NamedTemporaryFile(
                            suffix=".pdf", delete=True
                        ) as tmp:
                            tmp.write(response.content)
                            tmp.flush()

                            # 2. Parser immédiatement
                            result = parser.parse(Path(tmp.name))

                        downloaded += 1

                        if result.success and result.match:
                            # 3. Enrichir en base
                            was_enriched = service.enrich_from_pdf(
                                match_fresh, result.match, force=True,
                            )
                            if was_enriched:
                                enriched += 1

                            if verbose:
                                m = result.match
                                progress.console.print(
                                    f"  [green]✓[/green] {match_fresh.code_match}: "
                                    f"{m.equipe_a.nom[:20] if m.equipe_a else '?'} vs "
                                    f"{m.equipe_b.nom[:20] if m.equipe_b else '?'}"
                                )
                        else:
                            failed += 1
                            match_fresh.parsing_status = "error"
                            match_fresh.remarques = (
                                result.errors[0][:200] if result.errors else "Parsing error"
                            )

                        progress.update(
                            task, advance=1,
                            description=f"[green]✓ {match_fresh.code_match}[/green]",
                        )

                    except Exception as e:
                        failed += 1
                        match_fresh.parsing_status = "error"
                        match_fresh.remarques = str(e)[:200]
                        progress.update(
                            task, advance=1,
                            description=f"[red]✗ {match_fresh.code_match}[/red]",
                        )

                    # Commit par batch
                    if (enriched + failed) % 50 == 0 and (enriched + failed) > 0:
                        try:
                            session.commit()
                        except Exception:
                            session.rollback()
                            service.clear_caches()

            # Commit final
            import_log.finished_at = datetime.now()
            import_log.imported = enriched
            import_log.errors = failed
            import_log.status = (
                "success" if failed == 0
                else "partial" if enriched > 0
                else "failed"
            )
            try:
                session.commit()
            except Exception:
                session.rollback()

    console.print(Panel(
        f"[green]✓ Téléchargés : {downloaded}[/green]\n"
        f"[green]✓ Enrichis :    {enriched}[/green]\n"
        f"[red]✗ Échecs :      {failed}[/red]\n"
        f"[dim]Aucun PDF conservé sur disque[/dim]",
        title="Résumé du streaming"
    ))


def _cleanup_parsed_pdfs(
    *,
    saison: Optional[List[str]] = None,
    verbose: bool = False,
) -> None:
    """Supprime les PDFs locaux des matchs déjà parsés en base.

    Ne supprime que les fichiers dont le match a ``parsing_status='parsed'``
    en base de données.
    """
    from pyvolley.database.connection import DatabaseSession
    from pyvolley.database.models import MatchDB, SaisonDB
    from sqlalchemy import select

    pdf_base_dir = Path("data/pdfs")
    if not pdf_base_dir.exists():
        return

    with DatabaseSession() as session:
        stmt = select(MatchDB.code_match).where(MatchDB.parsing_status == "parsed")

        if saison:
            normalized = [s.replace("/", "-") for s in saison]
            saison_ids = [
                s.id for s in session.scalars(
                    select(SaisonDB).where(SaisonDB.code.in_(normalized))
                ).all()
            ]
            if saison_ids:
                stmt = stmt.where(MatchDB.saison_id.in_(saison_ids))

        parsed_codes = set(session.scalars(stmt).all())

    if not parsed_codes:
        return

    deleted = 0
    freed_bytes = 0

    for pdf_file in pdf_base_dir.glob("**/*.pdf"):
        stem = pdf_file.stem
        # Extraire le code_match du nom de fichier
        code = stem.split("_", 1)[1] if "_" in stem else stem
        if code in parsed_codes or stem in parsed_codes:
            size = pdf_file.stat().st_size
            pdf_file.unlink()
            deleted += 1
            freed_bytes += size
            if verbose:
                console.print(f"  [dim]🗑 {pdf_file}[/dim]")

    if deleted:
        freed_mb = freed_bytes / (1024 * 1024)
        console.print(
            f"[green]🗑 {deleted} PDFs supprimés ({freed_mb:.1f} Mo libérés)[/green]"
        )


# ============== Commande Cleanup ==============

@app.command()
def cleanup(
    target: str = typer.Argument(
        "pdfs",
        help="Cible du nettoyage : 'pdfs' (supprime les PDFs parsés), "
             "'orphans' (supprime les PDFs sans match en DB), "
             "'all' (les deux)"
    ),
    saison: Optional[List[str]] = typer.Option(
        None,
        "--saison", "-s",
        help="Filtrer par saison. Répétable."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Afficher ce qui serait supprimé sans supprimer"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Afficher chaque fichier supprimé"
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Ne pas demander confirmation"
    ),
):
    """
    🧹 Nettoie les fichiers PDF téléchargés pour libérer de l'espace disque.

    Trois modes de nettoyage :

    - **pdfs** : supprime les PDFs dont le match a déjà été parsé et stocké
      en base de données (parsing_status='parsed'). Les données sont en
      sécurité dans la DB, le PDF n'est plus nécessaire.

    - **orphans** : supprime les PDFs qui ne correspondent à aucun match en
      base de données (fichiers téléchargés par l'ancien système ou par
      erreur).

    - **all** : combine les deux nettoyages.

    Exemples:

        # Voir ce qui serait supprimé
        pyvolley cleanup pdfs --dry-run

        # Supprimer les PDFs orphelins
        pyvolley cleanup orphans

        # Tout nettoyer pour une saison
        pyvolley cleanup all -s 2021-2022

        # Nettoyage complet sans confirmation
        pyvolley cleanup all --force
    """
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import MatchDB, SaisonDB
    from sqlalchemy import select

    init_db()

    pdf_base_dir = Path("data/pdfs")
    if not pdf_base_dir.exists():
        console.print("[yellow]Aucun dossier PDF trouvé[/yellow]")
        raise typer.Exit(0)

    # Collecter tous les PDFs locaux
    all_pdfs = list(pdf_base_dir.glob("**/*.pdf"))
    if not all_pdfs:
        console.print("[yellow]Aucun fichier PDF trouvé[/yellow]")
        raise typer.Exit(0)

    # Filtrer par saison si demandé
    if saison:
        normalized = [s.replace("/", "-") for s in saison]
        all_pdfs = [
            f for f in all_pdfs
            if any(ns in str(f) for ns in normalized)
        ]

    total_size = sum(f.stat().st_size for f in all_pdfs)
    console.print(
        f"[blue]📁 {len(all_pdfs)} PDFs trouvés "
        f"({total_size / (1024**3):.2f} Go)[/blue]"
    )

    # Récupérer les codes de matchs en base
    with DatabaseSession() as session:
        all_codes = set(session.scalars(select(MatchDB.code_match)).all())
        parsed_codes = set(session.scalars(
            select(MatchDB.code_match).where(MatchDB.parsing_status == "parsed")
        ).all())

    # Classifier chaque PDF
    to_delete_parsed: list[Path] = []
    to_delete_orphan: list[Path] = []

    for pdf_file in all_pdfs:
        stem = pdf_file.stem
        code = stem.split("_", 1)[1] if "_" in stem else stem

        is_in_db = code in all_codes or stem in all_codes
        is_parsed = code in parsed_codes or stem in parsed_codes

        if target in ("pdfs", "all") and is_parsed:
            to_delete_parsed.append(pdf_file)
        elif target in ("orphans", "all") and not is_in_db:
            to_delete_orphan.append(pdf_file)

    to_delete = to_delete_parsed + to_delete_orphan
    delete_size = sum(f.stat().st_size for f in to_delete)

    if not to_delete:
        console.print("[green]Rien à nettoyer ![/green]")
        raise typer.Exit(0)

    # Résumé
    table = Table(title="🧹 Nettoyage prévu")
    table.add_column("Catégorie", style="white")
    table.add_column("Fichiers", justify="right", style="cyan")
    table.add_column("Taille", justify="right", style="yellow")

    if to_delete_parsed:
        sz = sum(f.stat().st_size for f in to_delete_parsed)
        table.add_row(
            "PDFs parsés (données en DB)",
            str(len(to_delete_parsed)),
            f"{sz / (1024**2):.1f} Mo",
        )
    if to_delete_orphan:
        sz = sum(f.stat().st_size for f in to_delete_orphan)
        table.add_row(
            "PDFs orphelins (pas de match en DB)",
            str(len(to_delete_orphan)),
            f"{sz / (1024**2):.1f} Mo",
        )

    table.add_section()
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{len(to_delete)}[/bold]",
        f"[bold]{delete_size / (1024**2):.1f} Mo[/bold]",
    )
    console.print(table)

    if dry_run:
        if verbose:
            for f in to_delete[:100]:
                console.print(f"  [dim]{f}[/dim]")
            if len(to_delete) > 100:
                console.print(f"  [dim]... et {len(to_delete) - 100} autres[/dim]")
        console.print(f"\n[yellow]Mode dry-run : aucun fichier supprimé[/yellow]")
        raise typer.Exit(0)

    if not force:
        confirm = typer.confirm(
            f"⚠️  Supprimer {len(to_delete)} fichiers "
            f"({delete_size / (1024**2):.1f} Mo) ?"
        )
        if not confirm:
            console.print("[yellow]Annulé[/yellow]")
            raise typer.Exit(0)

    # Supprimer
    deleted = 0
    freed = 0
    for f in to_delete:
        try:
            size = f.stat().st_size
            f.unlink()
            deleted += 1
            freed += size
            if verbose:
                console.print(f"  [dim]🗑 {f}[/dim]")
        except Exception as e:
            console.print(f"  [red]Erreur: {f}: {e}[/red]")

    # Nettoyer les dossiers vides
    empty_cleaned = 0
    for dirpath in sorted(pdf_base_dir.glob("**"), reverse=True):
        if dirpath.is_dir() and dirpath != pdf_base_dir:
            try:
                if not any(dirpath.iterdir()):
                    dirpath.rmdir()
                    empty_cleaned += 1
            except Exception:
                pass

    console.print(Panel(
        f"[green]🗑 {deleted} fichiers supprimés[/green]\n"
        f"[green]💾 {freed / (1024**2):.1f} Mo libérés[/green]"
        + (f"\n[dim]{empty_cleaned} dossiers vides nettoyés[/dim]" if empty_cleaned else ""),
        title="Nettoyage terminé"
    ))


# ============== Helpers : rapport de parsing organisé ==============


def _generate_parse_report(
    *,
    input_path: Path,
    parser,
    pdf_files: list,
    results: list[dict],
    successful: int,
    skipped: int,
    failed: int,
    warnings_count: int,
    error_details: list[dict],
    saison: Optional[List[str]],
    entity: Optional[List[str]],
    import_stats: Optional[dict],
    force: bool,
) -> None:
    """Génère un rapport de parsing organisé dans data/reports/parse/.

    Les rapports sont toujours générés quand ``--save-db`` est utilisé,
    ou quand ``--report`` est spécifié.
    """
    if not force:
        return

    detailed_results = []
    for r in results:
        detailed_results.append({
            "file": r["file"],
            "match_code": r["match"].code_match if r.get("match") else None,
            "parse_time_ms": r["parse_time_ms"],
            "diagnostics": [str(d) for d in r.get("diagnostics", [])],
        })

    report_data: dict = {
        "timestamp": datetime.now().isoformat(),
        "input_path": str(input_path),
        "parser": parser.name,
        "parser_version": parser.version,
        "total_files": len(pdf_files),
        "successful": successful,
        "skipped": skipped,
        "failed": failed,
        "warnings_total": warnings_count,
        "filters": {
            "saisons": saison or [],
            "entities": entity or [],
        },
        "summary": {
            "success_rate_percent": (
                successful / len(pdf_files) * 100 if pdf_files else 0
            ),
            "avg_parse_time_ms": (
                sum(r["parse_time_ms"] for r in results) / len(results)
                if results
                else 0
            ),
        },
        "errors": error_details[:50],
        "successful_files_with_diagnostics": [
            r for r in detailed_results if r["diagnostics"]
        ],
    }

    # Include import stats if available
    if import_stats:
        report_data["import"] = {
            "committed": import_stats["committed"],
            "duplicates": import_stats["duplicates"],
            "errors": import_stats["errors"],
            "error_details": import_stats.get("error_details", [])[:20],
        }

    # Organised folder: data/reports/parse/
    report_dir = Path("data/reports/parse")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = (
        report_dir / f"parse_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)

    console.print(f"\n[blue]📊 Rapport: {report_path}[/blue]")
    diag_count = len(report_data["successful_files_with_diagnostics"])
    if diag_count:
        console.print(
            f"[yellow]⚠ {diag_count} fichiers avec avertissements[/yellow]"
        )


# ============== Helpers : récapitulatif warnings & collecte ==============

from pyvolley.parsers.diagnostics import (
    Diagnostic, DiagnosticCategory, DiagnosticOrigin, DiagnosticLevel, CATEGORY_FOLDERS,
)


def _categorize_warning(warning: Diagnostic) -> tuple[str, str]:
    """Retourne (nom_dossier, label_affichage) pour un diagnostic."""
    folder, label = CATEGORY_FOLDERS.get(
        warning.category, ("autre", "Autre"),
    )
    return folder, label


def _iter_diagnostics(record: dict):
    """Itère sur les diagnostics d'un enregistrement."""
    yield from record.get('diagnostics', [])


def _display_warning_summary(
    results: list[dict],
    error_details: list[dict],
    total_parsed: int,
    console: Console,
) -> None:
    """Affiche un récapitulatif des diagnostics, séparé par origine."""
    from collections import Counter

    # Collecter les diagnostics par origine
    parsing_files: dict[str, set] = {}
    parsing_count: Counter = Counter()
    data_files: dict[str, set] = {}
    data_count: Counter = Counter()

    for r in results:
        for w in _iter_diagnostics(r):
            _, label = _categorize_warning(w)
            if w.origin == DiagnosticOrigin.PARSING:
                parsing_count[label] += 1
                parsing_files.setdefault(label, set()).add(r['file'])
            else:
                data_count[label] += 1
                data_files.setdefault(label, set()).add(r['file'])

    for r in error_details:
        for w in _iter_diagnostics(r):
            _, label = _categorize_warning(w)
            if w.origin == DiagnosticOrigin.PARSING:
                parsing_count[label] += 1
                parsing_files.setdefault(label, set()).add(r['file'])
            else:
                data_count[label] += 1
                data_files.setdefault(label, set()).add(r['file'])
        if r.get('errors'):
            label = "Erreur de parsing"
            parsing_count[label] += len(r['errors'])
            parsing_files.setdefault(label, set()).add(r['file'])

    if not parsing_count and not data_count:
        console.print("\n[green]✨ Aucun warning détecté — parsing parfait ![/green]")
        return

    # Table des problèmes de parsing
    if parsing_count:
        table = Table(title="⚠️  Problèmes de parsing")
        table.add_column("Catégorie", style="white")
        table.add_column("Occurrences", justify="right", style="red")
        table.add_column("Fichiers", justify="right", style="cyan")
        table.add_column("%", justify="right", style="dim")

        for label, count in parsing_count.most_common():
            n_files = len(parsing_files.get(label, set()))
            pct = f"{n_files / total_parsed * 100:.1f}" if total_parsed > 0 else "—"
            table.add_row(label, str(count), str(n_files), pct)

        console.print()
        console.print(table)

    # Table des données manquantes / incomplètes
    if data_count:
        table = Table(title="📋 Données absentes ou incomplètes (source PDF)")
        table.add_column("Catégorie", style="white")
        table.add_column("Occurrences", justify="right", style="yellow")
        table.add_column("Fichiers", justify="right", style="cyan")
        table.add_column("%", justify="right", style="dim")

        for label, count in data_count.most_common():
            n_files = len(data_files.get(label, set()))
            pct = f"{n_files / total_parsed * 100:.1f}" if total_parsed > 0 else "—"
            table.add_row(label, str(count), str(n_files), pct)

        console.print()
        console.print(table)

    # Résumé global
    total_files_with_issues = len(
        {f for files in {**parsing_files, **data_files}.values() for f in files}
    )
    console.print(
        f"\n[dim]Total: {total_files_with_issues} fichier(s) avec "
        f"diagnostics sur {total_parsed} parsé(s) "
        f"({total_files_with_issues / total_parsed * 100:.1f}%)[/dim]"
        if total_parsed > 0 else ""
    )


def _collect_problem_files(
    results: list[dict],
    error_details: list[dict],
    dest_dir: Path,
    console: Console,
) -> None:
    """Copie les PDFs problématiques dans dest_dir, classés par catégorie."""
    import shutil

    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0

    # Fichiers avec warnings
    for r in results:
        for w in _iter_diagnostics(r):
            folder, _ = _categorize_warning(w)
            _copy_to_category(r['file'], dest_dir / folder)
            copied += 1

    # Fichiers en erreur
    for r in error_details:
        if r.get('errors'):
            _copy_to_category(r['file'], dest_dir / "erreur_parsing")
            copied += 1
        for w in _iter_diagnostics(r):
            folder, _ = _categorize_warning(w)
            _copy_to_category(r['file'], dest_dir / folder)

    # Dédupliquer le comptage (un fichier copié = 1 même s'il a 3 catégories)
    all_copied = set()
    if dest_dir.exists():
        for sub in dest_dir.iterdir():
            if sub.is_dir():
                for f in sub.iterdir():
                    all_copied.add(f.name)

    # Afficher résumé
    table = Table(title=f"📂 Fichiers problématiques → {dest_dir}")
    table.add_column("Catégorie", style="white")
    table.add_column("Fichiers", justify="right", style="cyan")

    for sub in sorted(dest_dir.iterdir()):
        if sub.is_dir():
            count = len(list(sub.glob("*.pdf")))
            if count > 0:
                table.add_row(sub.name, str(count))

    console.print()
    console.print(table)
    console.print(f"[dim]Total: {len(all_copied)} fichiers uniques copiés dans {dest_dir}[/dim]")


def _copy_to_category(src_file: str, dest_folder: Path) -> None:
    """Copie un PDF dans un dossier de catégorie (sans écraser)."""
    import shutil

    src = Path(src_file)
    if not src.exists() or not src.suffix.lower() == '.pdf':
        return
    dest_folder.mkdir(parents=True, exist_ok=True)
    dest = dest_folder / src.name
    if not dest.exists():
        shutil.copy2(str(src), str(dest))


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
        help="Parser à utiliser (auto = défaut)"
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

# Sous-commandes de rapports (accessible via `pyvolley report` directement)
from pyvolley.cli.reports import report_app
app.add_typer(report_app, name="report")


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
    
    ⚠️ ATTENTION: Supprime toutes les données et les caches de parsing!
    
    Options:
        --full: Réinitialise aussi l'historique des migrations (après des changements de schéma)
    """
    from pyvolley.database.connection import reset_db, reset_db_with_migrations
    
    if full:
        action_desc = "COMPLÈTEMENT Y COMPRIS LES MIGRATIONS"
    else:
        action_desc = "complètement"
    
    if not force:
        confirm = typer.confirm(f"⚠️ Cette action va SUPPRIMER toutes les données {action_desc} et vider les caches. Continuer?")
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
        console.print("[dim]↳ Caches de parsing vidés[/dim]")
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


@db_app.command("import-history")
def db_import_history(
    limit: int = typer.Option(20, "--limit", "-n", help="Nombre d'entrées à afficher"),
    operation: Optional[str] = typer.Option(None, "--operation", "-o", help="Filtrer par opération (parse, import, complete-scores)"),
):
    """
    📋 Affiche l'historique des imports en base de données.

    Montre les dernières opérations d'import avec le nombre de matchs
    importés, doublons ignorés, erreurs rencontrées, etc.
    """
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
            console.print("[yellow]Aucun historique d'import trouvé[/yellow]")
            return

        table = Table(title="📋 Historique des imports")
        table.add_column("Date", style="cyan", no_wrap=True)
        table.add_column("Opération", style="white")
        table.add_column("Source", style="dim", max_width=30)
        table.add_column("Importés", justify="right", style="green")
        table.add_column("Doublons", justify="right", style="yellow")
        table.add_column("Erreurs", justify="right", style="red")
        table.add_column("Statut", justify="center")

        for log in logs:
            started = log.started_at.strftime("%Y-%m-%d %H:%M") if log.started_at else "?"
            source_short = (log.source or "")[-30:] if log.source else "-"
            status_map = {
                "running": "[yellow]⏳ En cours[/yellow]",
                "success": "[green]✓ OK[/green]",
                "partial": "[yellow]⚠ Partiel[/yellow]",
                "failed": "[red]✗ Échoué[/red]",
            }
            status = status_map.get(log.status, log.status)

            table.add_row(
                started,
                log.operation,
                source_short,
                str(log.imported),
                str(log.duplicates),
                str(log.errors),
                status,
            )

        console.print(table)

        # Show total stats
        total_imported = sum(log.imported for log in logs)
        total_errors = sum(log.errors for log in logs)
        console.print(
            f"\n[dim]Total sur les {len(logs)} dernières opérations : "
            f"{total_imported} importés, {total_errors} erreurs[/dim]"
        )

    except Exception as e:
        console.print(f"[red]✗ Erreur: {e}[/red]")
        raise typer.Exit(1)


def main():
    """Point d'entrée principal."""
    app()


if __name__ == "__main__":
    main()
