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
        
        # Télécharger uniquement les matchs pro (LNV)
        pyvolley download --pro
        
        # Limiter à 10 téléchargements avec aperçu
        pyvolley download -e ABCCS -p EFA -n 10 --dry-run
    """
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
    total_poules = 0
    
    for current_saison in saisons:
        for current_entity in entities_to_process:
            console.print(f"\n[blue]📂 {current_entity} - Saison {current_saison}[/blue]")
            
            # Récupérer les poules
            try:
                with console.status(f"[bold blue]Récupération des poules pour {current_entity}..."):
                    poules_list = scraper.get_poules_for_entity(current_entity, current_saison)
            except Exception as e:
                console.print(f"  [red]Erreur lors de la récupération des poules: {e}[/red]")
                continue
            
            if not poules_list:
                console.print(f"  [yellow]Aucune poule trouvée[/yellow]")
                continue
            
            # Filtrer par poule si spécifiée
            if poule:
                poules_list = [p for p in poules_list if p.code == poule]
                if not poules_list:
                    console.print(f"  [yellow]Poule {poule} non trouvée[/yellow]")
                    continue
            
            # Filtrer pour le mode --pro (seulement les compétitions LNV)
            if pro:
                poules_list = [p for p in poules_list if p.code in pro_poule_codes]
                if not poules_list:
                    console.print(f"  [yellow]Aucune poule pro trouvée[/yellow]")
                    continue
            
            total_poules += len(poules_list)
            console.print(f"  [green]✓ {len(poules_list)} poule(s) trouvée(s)[/green]")
            
            # Collecter les matchs
            poule_errors = 0
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
                    try:
                        matches = list(scraper.get_matches_for_poule(
                            current_entity, p.code, current_saison,
                            is_division=p.is_division,
                        ))
                        for m in matches:
                            m.poule_nom = p.nom
                            m.entity_code = current_entity  # Ajouter le code entité
                            m.saison = current_saison       # Ajouter la saison
                        all_matches.extend(matches)
                        progress.update(task, advance=1, description=f"  {p.code}: {len(matches)} match(s)")
                    except Exception as e:
                        poule_errors += 1
                        progress.update(task, advance=1, description=f"  [red]{p.code}: erreur ({e})[/red]")

            if poule_errors:
                console.print(f"  [yellow]⚠ {poule_errors} poule(s) avec erreurs (ignorées)[/yellow]")
            
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

    # Phase 1 : collecte des matchs (séquentiel, rapide)
    all_matches = []
    for current_saison in saisons:
        for current_entity in entities_to_process:
            console.print(f"\n[blue]📂 {current_entity} - Saison {current_saison}[/blue]")
            try:
                with console.status(f"[bold blue]Récupération des poules pour {current_entity}..."):
                    poules_list = scraper.get_poules_for_entity(current_entity, current_saison)
            except Exception as e:
                console.print(f"  [red]Erreur: {e}[/red]")
                continue

            if not poules_list:
                console.print(f"  [yellow]Aucune poule trouvée[/yellow]")
                continue

            if poule:
                poules_list = [p for p in poules_list if p.code == poule]
            if pro:
                poules_list = [p for p in poules_list if p.code in pro_poule_codes]

            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                          BarColumn(), TaskProgressColumn(), console=console, transient=True) as progress:
                task_id = progress.add_task("Récupération des matchs...", total=len(poules_list))
                for p in poules_list:
                    try:
                        matches = list(scraper.get_matches_for_poule(
                            current_entity, p.code, current_saison,
                            is_division=p.is_division,
                        ))
                        for m in matches:
                            m.poule_nom = p.nom
                            m.entity_code = current_entity
                            m.saison = current_saison
                        all_matches.extend(matches)
                        progress.update(task_id, advance=1, description=f"  {p.code}: {len(matches)} match(s)")
                    except Exception:
                        progress.update(task_id, advance=1, description=f"  [red]{p.code}: erreur[/red]")

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
                        getattr(match, 'poule_nom', match.competition_code or 'autres'))
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
                                scraper.base_url, match.ligue_code,
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
                                        scraper.base_url, match.ligue_code,
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
        # Chercher si la poule est une division pour utiliser le bon paramètre URL
        poules_info = scraper.get_poules_for_entity(entity, saison)
        is_division = any(p.code == poule and p.is_division for p in poules_info)
        matches = list(scraper.get_matches_for_poule(entity, poule, saison, is_division=is_division))
    
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


# ============== Commande Parse ==============

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
        help="Ignorer les fichiers déjà parsés (basé sur le cache de hashes)"
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
    saison: Optional[List[str]] = typer.Option(
        None,
        "--saison", "-s",
        help="Filtrer par saison (ex: 2024-2025). Répétable: -s 2024-2025 -s 2025-2026"
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
):
    """
    📄 Parse intelligemment les feuilles de match PDF.
    
    Le cache de parsing (basé sur le hash des fichiers) permet de ne pas
    re-parser les PDFs déjà traités. Lors de l'import en base (--save-db),
    les doublons sont détectés directement en base, indépendamment du cache.
    
    Exemples:
    
        # Parser tous les PDFs récursivement
        pyvolley parse data/pdfs
        
        # Parser avec limite et sauvegarde en base
        pyvolley parse data/pdfs -n 100 --save-db
        
        # Parser plusieurs saisons
        pyvolley parse data/pdfs -s 2024-2025 -s 2025-2026
        
        # Parser avec forçage (ignore le cache)
        pyvolley parse data/pdfs --force
        
        # Vider le cache puis parser
        pyvolley parse data/pdfs --clear-cache
        
        # Parser seulement certaines entités
        pyvolley parse data/pdfs -e ABCCS -e LIRA
        
        # Exporter en JSON
        pyvolley parse data/pdfs -o results.json
        
        # Mode dry-run pour voir ce qui serait parsé
        pyvolley parse data/pdfs --dry-run -n 50
    """
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
    # Le cache est centralisé dans data/.pyvolley_parse_cache.json
    # Il associe un hash de fichier → code_match parsé pour éviter de
    # re-parser les mêmes PDFs.  Le cache est indépendant de la base de
    # données : lors de --save-db, les doublons sont détectés en DB.
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
        f"[bold blue]🏐 PyVolley - Parsing des feuilles de match[/bold blue]\n\n"
        f"Source: [cyan]{input_path}[/cyan]\n"
        f"Fichiers: [cyan]{len(pdf_files)}[/cyan]\n"
        f"Saison(s): [cyan]{saison_display}[/cyan]\n"
        f"Entité(s): [cyan]{entity_display}[/cyan]\n"
        f"Parser: [cyan]auto[/cyan]\n"
        f"Mode: [cyan]{'Aperçu (dry-run)' if dry_run else 'Parsing'}[/cyan]\n"
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
    total_parsed = successful + failed  # fichiers effectivement traités (hors cache)
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
    # L'import vérifie les doublons directement en base via code_match +
    # saison_id, donc il est fiable même si le cache de parsing contient
    # des entrées pour des matchs supprimés lors d'un reset DB.
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

                # Create audit log entry
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
                            # Rollback annule les matchs non commités de ce batch
                            imported -= batch_imported
                            batch_imported = 0
                            # Re-add the import_log (lost after rollback)
                            session.add(import_log)
                            session.flush()
                            if verbose:
                                console.print(f"  [red]✗[/red] Import {r['match'].code_match}: {e}")
                        
                        # Commit par batch pour éviter de tout perdre
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

                # Update audit log
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
    
    # ── Rapport (toujours généré quand --save-db, optionnel sinon) ─────
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


# ============== Commande complétion de scores ==============

@app.command("complete-scores")
def complete_scores(
    saison: str = typer.Argument(
        ...,
        help="Saison à compléter (ex: 2025-2026)"
    ),
    entity: Optional[List[str]] = typer.Option(
        None,
        "--entity", "-e",
        help="Restreindre à certaines entités. Répétable: -e LIRA -e ABCCS"
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Affiche ce qui serait créé/modifié sans modifier la base"
    ),
    summary_only: bool = typer.Option(
        False,
        "--summary",
        help="Affiche uniquement l'état de complétion sans rien modifier"
    ),
):
    """
    🔄 Synchronise et complète les matchs depuis le site FFVB.

    Récupère les calendriers FFVB en ligne pour chaque poule de la saison.
    Crée les matchs manquants (feuille absente, matchs à venir) et complète
    les scores des matchs existants.

    Exemples:

        # Voir l'état de complétion pour une saison
        pyvolley complete-scores 2025-2026 --summary

        # Voir ce qui serait créé/modifié (dry-run)
        pyvolley complete-scores 2025-2026 --dry-run

        # Synchroniser effectivement
        pyvolley complete-scores 2025-2026

        # Restreindre à une entité
        pyvolley complete-scores 2025-2026 -e LIRA
    """
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.score_completion import ScoreCompletionService

    init_db()

    with DatabaseSession() as session:
        service = ScoreCompletionService(session)

        # ── Mode summary : juste afficher l'état ──
        if summary_only:
            summary = service.get_completion_summary(saison)
            if "error" in summary:
                console.print(f"[red]Erreur: {summary['error']}[/red]")
                raise typer.Exit(1)

            console.print(Panel(
                f"[bold blue]Saison: {summary['saison']}[/bold blue]\n\n"
                f"Total matchs:        [cyan]{summary['total_matches']}[/cyan]\n"
                f"Matchs joués:        [cyan]{summary['match_joue']}[/cyan]\n"
                f"Matchs à venir:      [yellow]{summary['upcoming']}[/yellow]\n"
                f"Avec détails:        [green]{summary['with_details']}[/green]\n"
                f"Sans détails:        [yellow]{summary['without_details']}[/yellow]\n"
                f"Complétion:          [{'green' if summary['completion_pct'] > 80 else 'yellow'}]"
                f"{summary['completion_pct']:.1f}%[/{'green' if summary['completion_pct'] > 80 else 'yellow'}]",
                title="📊 État de complétion des scores"
            ))

            if summary['by_source']:
                table = Table(title="Sources des scores")
                table.add_column("Source", style="cyan")
                table.add_column("Matchs", justify="right", style="white")
                for src, count in sorted(summary['by_source'].items()):
                    label = {
                        "pdf": "📄 PDF (feuille de match)",
                        "online": "🌐 En ligne (FFVB)",
                        "manual": "✏️ Manuel",
                        "none": "❌ Pas de score",
                    }.get(src, src)
                    table.add_row(label, str(count))
                console.print(table)

            raise typer.Exit(0)

        # ── Mode complétion / synchronisation ──
        mode = "[yellow]DRY-RUN[/yellow]" if dry_run else "[green]MISE À JOUR[/green]"
        entity_display = ", ".join(entity) if entity else "toutes"

        console.print(Panel(
            f"[bold blue]🔄 Synchronisation & complétion des scores[/bold blue]\n\n"
            f"Saison:   [cyan]{saison}[/cyan]\n"
            f"Entités:  [cyan]{entity_display}[/cyan]\n"
            f"Mode:     {mode}",
            title="Configuration"
        ))

        def on_progress(poule_code, n_online, n_created, n_updated):
            status = ""
            if n_created:
                status += f"[green]+{n_created} créés[/green] "
            if n_updated:
                status += f"[cyan]~{n_updated} mis à jour[/cyan] "
            if not status:
                status = "[dim]aucun changement[/dim]"
            console.print(
                f"  [bold]{poule_code}[/bold]: "
                f"{n_online} matchs en ligne → {status}"
            )

        console.print()
        console.print("[bold]Traitement des poules :[/bold]")

        stats = service.complete_scores_for_saison(
            saison,
            entity_codes=entity,
            dry_run=dry_run,
            progress_callback=on_progress,
        )

        # ── Afficher les résultats ──
        console.print()

        result_lines = [
            f"Poules traitées:        [cyan]{stats['poules_processed']}[/cyan]",
            f"Matchs en ligne:        [cyan]{stats['total_online']}[/cyan]",
        ]

        if stats['matches_created']:
            result_lines.append(
                f"Matchs créés:           [green]{stats['matches_created']}[/green]"
                f"  (dont [yellow]{stats['upcoming_created']}[/yellow] à venir)"
            )
        if stats['matches_updated']:
            result_lines.append(
                f"Scores mis à jour:      [green]{stats['matches_updated']}[/green]"
            )
        if stats['metadata_updated']:
            result_lines.append(
                f"Métadonnées mises à jour: [cyan]{stats['metadata_updated']}[/cyan]"
            )
        if stats['arbitres_added']:
            result_lines.append(
                f"Arbitres ajoutés:       [cyan]{stats['arbitres_added']}[/cyan]"
            )
        if stats['already_complete']:
            result_lines.append(
                f"Déjà complets:          [dim]{stats['already_complete']}[/dim]"
            )
        if stats['skipped_exempt']:
            result_lines.append(
                f"Exemptions ignorées:    [dim]{stats['skipped_exempt']}[/dim]"
            )

        title = "🔍 Résultats (dry-run)" if dry_run else "✅ Résultats"
        console.print(Panel("\n".join(result_lines), title=title))

        if stats['errors']:
            console.print(f"\n[red]Erreurs ({len(stats['errors'])}):[/red]")
            for err in stats['errors'][:10]:
                console.print(f"  [red]• {err}[/red]")
            if len(stats['errors']) > 10:
                console.print(f"  [dim]... et {len(stats['errors']) - 10} autres[/dim]")

        if dry_run and (stats['matches_created'] + stats['matches_updated'] > 0):
            total_changes = stats['matches_created'] + stats['matches_updated']
            console.print(
                f"\n[blue]💡 {total_changes} changements possibles. "
                f"Relancez sans --dry-run pour appliquer.[/blue]"
            )


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
