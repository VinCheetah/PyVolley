"""
Interface CLI principale pour PyVolley.

Commandes principales :
- ``import``        : importer des données FFVB (scrape → download → parse)
- ``status``        : tableau de bord du pipeline
- ``list``          : consulter entités, poules, matchs disponibles
- ``parse``         : analyser un PDF de feuille de match (sans base de données)
- ``cleanup``       : nettoyer les PDFs locaux
- ``serve``         : lancer le serveur web
- ``simulate``      : visualiser un match en HTML interactif
- ``stats``         : statistiques globales de la base de données
- ``compute-stats`` : pré-calculer les statistiques palmarès et les stocker en base
- ``init``          : initialiser la base de données
- ``db``            : gestion de la base (migrations, exploration)
- ``report``        : rapports détaillés sur les entités en base
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pyvolley.core.config import settings
from pyvolley.cli.helpers import (
    resolve_entities,
    resolve_saisons,
    display_entities,
    build_pdf_index,
    find_pdf_for_match,
    add_saison_filter,
    add_entity_filter,
    make_progress,
    sanitize_filename,
    format_entities_display,
)

app = typer.Typer(
    name="pyvolley",
    help="🏐 PyVolley — Outils pour les données volleyball FFVB",
    add_completion=False,
)
console = Console()


# ════════════════════════════════════════════════════════════════════
# import — pipeline unifié : scrape → download → parse
# ════════════════════════════════════════════════════════════════════


@app.command("import")
def import_data(
    entity: Optional[List[str]] = typer.Option(
        None, "--entity", "-e",
        help="Code de l'entité (ex: ABCCS, LIRA). Répétable.",
    ),
    saison: Optional[List[str]] = typer.Option(
        None, "--saison", "-s",
        help="Saison au format YYYY/YYYY. Répétable. Défaut : saison courante.",
    ),
    entity_type: Optional[str] = typer.Option(
        None, "--type", "-t",
        help="Filtrer par type d'entité : nationale, ligue, comite.",
    ),
    all_entities: bool = typer.Option(
        False, "--all",
        help="Traiter toutes les entités.",
    ),
    pro: bool = typer.Option(
        False, "--pro",
        help="Importer uniquement les matchs pro (LNV).",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n",
        help="Nombre maximum de matchs à traiter.",
    ),
    only: Optional[str] = typer.Option(
        None, "--only",
        help="Exécuter une seule étape : scrape, download ou parse.",
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Re-traiter les matchs déjà parsés.",
    ),
    keep_pdfs: bool = typer.Option(
        True, "--keep-pdfs/--no-keep-pdfs",
        help="Conserver les PDFs après parsing. --no-keep-pdfs libère l'espace.",
    ),
    concurrent: int = typer.Option(
        5, "--concurrent", "-c",
        help="Nombre de téléchargements simultanés (1–20).",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Afficher le plan sans effectuer de modification.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Affichage détaillé.",
    ),
):
    """
    🔄 Importer des données FFVB dans la base de données.

    Exécute le pipeline complet en trois étapes :

      1. **Scrape** — récupère les exports CSV FFVB et enregistre les
         matchs en base. Enrichit automatiquement les clubs (adressier).
      2. **Download** — télécharge les PDFs des feuilles de match
         (concurrent par défaut).
      3. **Parse** — analyse les PDFs et enrichit les matchs avec les
         données détaillées (compositions, scores, arbitres…).

    Utilisez ``--only`` pour n'exécuter qu'une seule étape.

    Exemples :

        pyvolley import -e ABCCS
        pyvolley import -e ABCCS -s 2024/2025
        pyvolley import --type ligue
        pyvolley import --pro -n 100
        pyvolley import --only scrape -e ABCCS
        pyvolley import --only parse --force
        pyvolley import --no-keep-pdfs -e ABCCS
        pyvolley import --dry-run --all
    """
    concurrent = max(1, min(concurrent, 20))

    # Déterminer les étapes à exécuter
    steps = ["scrape", "download", "parse"]
    if only:
        if only not in steps:
            console.print(f"[red]Étape invalide : {only}. Choix : scrape, download, parse.[/red]")
            raise typer.Exit(1)
        steps = [only]

    from pyvolley.scrapers.ffvb import FFVBScraper

    scraper = FFVBScraper()
    entities_to_process = resolve_entities(
        scraper, entity=entity, entity_type=entity_type,
        all_entities=all_entities, pro=pro,
    )
    saisons = resolve_saisons(scraper, saison)

    # Vérifier qu'on a des entités pour l'étape scrape
    if "scrape" in steps and not entities_to_process:
        console.print("[yellow]Aucune entité spécifiée.[/yellow]")
        display_entities(scraper, console)
        console.print("\n[blue]Utilisez -e CODE, --type TYPE, ou --all[/blue]")
        raise typer.Exit(0)

    # Afficher la configuration
    entities_display = format_entities_display(entities_to_process)
    saisons_display = ", ".join(saisons)

    console.print(Panel(
        f"[bold blue]🔄 Import FFVB[/bold blue]\n\n"
        f"Étapes :     [cyan]{' → '.join(steps)}[/cyan]\n"
        f"Saison(s) :  [cyan]{saisons_display}[/cyan]\n"
        f"Entité(s) :  [cyan]{entities_display or 'depuis la base'}[/cyan]"
        f" ({len(entities_to_process)} au total)\n"
        f"Limite :     [cyan]{limit or 'aucune'}[/cyan]\n"
        f"Mode :       [cyan]{'aperçu' if dry_run else 'exécution'}[/cyan]",
        title="Configuration",
    ))

    if dry_run:
        _import_dry_run(steps, entities_to_process, saisons, limit)
        raise typer.Exit(0)

    from pyvolley.database.connection import init_db
    init_db()

    # ── Étape 1 : Scrape ───────────────────────────────────────────
    if "scrape" in steps:
        _import_scrape(
            scraper, entities_to_process, saisons, verbose=verbose,
        )

    # ── Étape 2 : Download ─────────────────────────────────────────
    if "download" in steps:
        if not keep_pdfs and "parse" in steps:
            # Mode streaming : download + parse en une passe
            console.print(
                "\n[bold blue]═══ Download + Parse (streaming) ═══[/bold blue]"
            )
            _import_stream(
                limit=limit, saison=saison, entity=entity, verbose=verbose,
            )
            steps = [s for s in steps if s != "parse"]
        else:
            console.print("\n[bold blue]═══ Download ═══[/bold blue]")
            _import_download(
                limit=limit, saison=saison, concurrent=concurrent,
                verbose=verbose,
            )

    # ── Étape 3 : Parse ───────────────────────────────────────────
    if "parse" in steps:
        console.print("\n[bold blue]═══ Parse ═══[/bold blue]")
        _import_parse(
            limit=limit, saison=saison, entity=entity,
            force=force, verbose=verbose,
        )

        # Nettoyage post-parse si --no-keep-pdfs
        if not keep_pdfs:
            _cleanup_parsed_pdfs(saison=saison, verbose=verbose)

    console.print(Panel(
        "[bold green]Pipeline terminé[/bold green]",
        title="✅ Terminé",
    ))


# ── Sous-fonctions du pipeline import ───────────────────────────────


def _import_dry_run(
    steps: list[str],
    entities: list[str],
    saisons: list[str],
    limit: Optional[int],
) -> None:
    """Affiche le plan d'exécution sans effectuer d'action."""
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import MatchDB
    from sqlalchemy import select, func

    try:
        init_db()
        with DatabaseSession() as session:
            for status in ["discovered", "downloaded", "parsed", "error"]:
                count = session.scalar(
                    select(func.count(MatchDB.id)).where(
                        MatchDB.parsing_status == status,
                    )
                ) or 0
                console.print(f"  {status}: [cyan]{count}[/cyan]")
    except Exception:
        console.print("  [dim]Base de données non initialisée[/dim]")

    if "scrape" in steps:
        console.print("\n[bold]Étape 1 — Scrape :[/bold]")
        console.print(f"  → Entités : {', '.join(entities)}")
        console.print(f"  → Saisons : {', '.join(saisons)}")

    if "download" in steps:
        console.print("\n[bold]Étape 2 — Download :[/bold]")
        console.print("  → Matchs en base avec statut 'discovered'")

    if "parse" in steps:
        console.print("\n[bold]Étape 3 — Parse :[/bold]")
        console.print("  → Matchs en base avec PDFs téléchargés")

    console.print("\n[yellow]Mode dry-run : aucune action effectuée[/yellow]")


def _import_scrape(
    scraper,
    entities: list[str],
    saisons: list[str],
    *,
    verbose: bool = False,
) -> None:
    """Étape 1 : scrape des exports CSV et import en base."""
    from pyvolley.database.connection import DatabaseSession
    from pyvolley.database.export_import_service import ExportImportService
    from pyvolley.scrapers.ffvb.adressier_scraper import fetch_adressier
    from pyvolley.scrapers.ffvb.export_scraper import get_unique_poules

    console.print("\n[bold blue]═══ Scrape ═══[/bold blue]")

    total_imported = 0
    total_updated = 0
    total_clubs = 0

    for target_saison in saisons:
        for target_entity in entities:
            console.print(f"\n[blue]{target_entity} — {target_saison}[/blue]")

            try:
                with console.status(
                    f"[bold blue]Récupération export CSV pour {target_entity}..."
                ):
                    export_data = scraper.scrape_entity(target_entity, target_saison)
            except Exception as e:
                console.print(f"  [red]Erreur : {e}[/red]")
                continue

            if not export_data:
                console.print("  [yellow]Aucun match trouvé[/yellow]")
                continue

            played = sum(1 for m in export_data if m.match_joue)
            poules = get_unique_poules(export_data)
            console.print(
                f"  [green]✓ {len(export_data)} matchs[/green] "
                f"({played} joués, {len(poules)} poules)"
            )

            with DatabaseSession() as session:
                service = ExportImportService(session)
                stats = service.import_matches(
                    export_data, target_entity, target_saison,
                )
                imported = stats.get("imported", 0)
                updated = stats.get("updated", 0)
                total_imported += imported
                total_updated += updated

                parts = []
                if imported:
                    parts.append(f"[green]+{imported} créés[/green]")
                if updated:
                    parts.append(f"[cyan]~{updated} mis à jour[/cyan]")
                dup = stats.get("duplicates", 0)
                if dup:
                    parts.append(f"[dim]{dup} inchangés[/dim]")
                console.print(
                    f"  DB : {' | '.join(parts) or '[dim]aucun changement[/dim]'}"
                )

                # Enrichissement clubs (systématique)
                try:
                    poule_codes = sorted(poules.keys())
                    with console.status(
                        f"[bold magenta]Enrichissement clubs ({len(poule_codes)} poules)..."
                    ):
                        clubs_info = fetch_adressier(
                            scraper.client, scraper.base_url,
                            target_entity, target_saison, poule_codes,
                        )
                    if clubs_info:
                        club_stats = service.enrich_clubs(
                            clubs_info, target_entity, target_saison,
                            scraper.base_url,
                        )
                        enriched = club_stats.get("enriched", 0)
                        created = club_stats.get("created", 0)
                        total_clubs += enriched + created
                        if enriched or created:
                            console.print(
                                f"  Clubs : [magenta]{created} créés, "
                                f"{enriched} enrichis[/magenta]"
                            )
                except Exception as e:
                    console.print(f"  [red]Erreur enrichissement clubs : {e}[/red]")

                session.commit()

    console.print(
        f"\n[green]Scrape terminé : {total_imported} importés, "
        f"{total_updated} mis à jour, {total_clubs} clubs enrichis[/green]"
    )


def _import_download(
    *,
    limit: Optional[int] = None,
    saison: Optional[List[str]] = None,
    concurrent: int = 5,
    verbose: bool = False,
) -> None:
    """Étape 2 : téléchargement concurrent des PDFs.

    Procède en trois phases :
    1. Prépare la liste des téléchargements (marque les existants)
    2. Télécharge les fichiers manquants (async concurrent)
    3. Met à jour la base de données en batch
    """
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import MatchDB, SaisonDB
    from sqlalchemy import select

    init_db()

    # Phase 1 : préparer les téléchargements
    download_tasks: list[tuple[int, str, Path]] = []
    already_present: list[tuple[int, str]] = []  # (match_id, pdf_path)

    with DatabaseSession() as session:
        stmt = (
            select(MatchDB)
            .where(
                MatchDB.parsing_status == "discovered",
                MatchDB.match_joue == True,  # noqa: E712
                MatchDB.source_url.isnot(None),
            )
        )
        stmt, _ = add_saison_filter(session, stmt, saison)
        stmt = stmt.order_by(MatchDB.code_match)
        if limit:
            stmt = stmt.limit(limit)
        matches = list(session.scalars(stmt).all())

        if not matches:
            console.print("[yellow]Aucun match à télécharger[/yellow]")
            return

        console.print(f"[blue]📥 {len(matches)} matchs à traiter[/blue]")

        pdf_base = Path("data/pdfs")
        pdf_index = build_pdf_index(pdf_base)

        for match_db in matches:
            if not match_db.source_url:
                continue

            saison_db = (
                session.get(SaisonDB, match_db.saison_id)
                if match_db.saison_id else None
            )
            saison_code = saison_db.code if saison_db else "unknown"
            dest_dir = pdf_base / saison_code
            dest_file = dest_dir / f"{match_db.code_match}.pdf"

            # Vérifier si déjà présent
            if dest_file.exists():
                already_present.append((match_db.id, str(dest_file)))
                continue

            existing = pdf_index.get(match_db.code_match)
            if existing:
                already_present.append((match_db.id, str(existing)))
                continue

            download_tasks.append((match_db.id, match_db.source_url, dest_file))

        # Mettre à jour les matchs dont le PDF existe déjà
        if already_present:
            for match_id, pdf_path in already_present:
                m = session.get(MatchDB, match_id)
                if m:
                    m.parsing_status = "downloaded"
                    m.source_pdf = pdf_path
            session.commit()
            console.print(f"[dim]⏭ {len(already_present)} PDFs déjà présents[/dim]")

    if not download_tasks:
        return

    console.print(f"[blue]⬇ {len(download_tasks)} à télécharger[/blue]")

    # Phase 2 : téléchargement concurrent (pas d'accès DB ici)
    # Résultats : (match_id, dest_path, success, error_msg)
    dl_results: list[tuple[int, Path, bool, str]] = []

    async def _run():
        from pyvolley.scrapers.async_http_client import AsyncHttpClient

        async with AsyncHttpClient(
            request_delay=0.15, max_concurrent=concurrent,
        ) as client:
            semaphore = asyncio.Semaphore(concurrent)

            with make_progress(console) as progress:
                task_id = progress.add_task(
                    "Téléchargement...", total=len(download_tasks),
                )

                async def _dl_one(match_id: int, url: str, dest: Path):
                    async with semaphore:
                        try:
                            response = await client.get(url)
                            content = response.content
                            if not content[:5].startswith(b"%PDF"):
                                raise ValueError("Réponse non-PDF")
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            with open(dest, "wb") as f:
                                f.write(content)
                            dl_results.append((match_id, dest, True, ""))
                            progress.update(
                                task_id, advance=1,
                                description=f"[green]✓ {dest.stem}[/green]",
                            )
                        except Exception as e:
                            dl_results.append((match_id, dest, False, str(e)[:100]))
                            progress.update(
                                task_id, advance=1,
                                description=f"[red]✗ {dest.stem}[/red]",
                            )

                await asyncio.gather(
                    *[_dl_one(mid, url, d) for mid, url, d in download_tasks]
                )

    asyncio.run(_run())

    # Phase 3 : mise à jour DB en batch
    downloaded = 0
    failed = 0

    with DatabaseSession() as session:
        for match_id, dest, success, error_msg in dl_results:
            m = session.get(MatchDB, match_id)
            if not m:
                continue
            if success:
                m.parsing_status = "downloaded"
                m.source_pdf = str(dest)
                downloaded += 1
            else:
                m.parsing_status = "error"
                m.remarques = f"Download: {error_msg}"
                failed += 1

            if (downloaded + failed) % 50 == 0:
                try:
                    session.commit()
                except Exception:
                    session.rollback()

        try:
            session.commit()
        except Exception:
            session.rollback()

    console.print(
        f"\n[green]✓ {downloaded} téléchargés[/green]"
        + (f" | [dim]{len(already_present)} déjà présents[/dim]" if already_present else "")
        + (f" | [red]{failed} erreurs[/red]" if failed else "")
    )


def _import_parse(
    *,
    limit: Optional[int] = None,
    saison: Optional[List[str]] = None,
    entity: Optional[List[str]] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Étape 3 : parsing des PDFs et enrichissement de la base."""
    from pyvolley.parsers.factory import ParserFactory
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import MatchDB, ImportLogDB
    from sqlalchemy import select

    init_db()

    statuses = (
        ["discovered", "downloaded", "parsed", "error"]
        if force
        else ["discovered", "downloaded"]
    )

    parser = ParserFactory.get_default()

    with DatabaseSession() as session:
        stmt = (
            select(MatchDB)
            .where(
                MatchDB.parsing_status.in_(statuses),
                MatchDB.match_joue == True,  # noqa: E712
            )
        )
        stmt, saison_ids = add_saison_filter(session, stmt, saison)
        if saison_ids is not None and not saison_ids:
            console.print("[yellow]Aucune saison trouvée[/yellow]")
            return
        stmt = add_entity_filter(session, stmt, entity)
        stmt = stmt.order_by(MatchDB.code_match)
        if limit:
            stmt = stmt.limit(limit)
        matches_db = list(session.scalars(stmt).all())

    if not matches_db:
        console.print(
            f"[yellow]Aucun match à parser (statuts : {', '.join(statuses)})[/yellow]"
        )
        return

    # Localiser les PDFs
    pdf_base = Path("data/pdfs")
    pdf_index = build_pdf_index(pdf_base)

    match_pdf_pairs = []
    for m in matches_db:
        pdf_path = find_pdf_for_match(m, pdf_base, pdf_index)
        if pdf_path:
            match_pdf_pairs.append((m, pdf_path))

    if not match_pdf_pairs:
        console.print(
            f"[yellow]Aucun PDF trouvé pour les {len(matches_db)} matchs. "
            f"Lancez d'abord : pyvolley import --only download[/yellow]"
        )
        return

    console.print(
        f"[blue]{len(match_pdf_pairs)} matchs à parser "
        f"({parser.name} v{parser.version})[/blue]"
    )

    enriched = 0
    skipped_count = 0
    failed = 0
    warnings_count = 0
    results = []
    error_details = []

    with DatabaseSession() as session:
        service = MatchImportService(session)

        import_log = ImportLogDB(
            operation="parse-enrich",
            source="import-pipeline",
            total_attempted=len(match_pdf_pairs),
            status="running",
        )
        session.add(import_log)
        session.flush()

        with make_progress(console) as progress:
            task = progress.add_task(
                "Parsing...", total=len(match_pdf_pairs),
            )

            for match_db, pdf_path in match_pdf_pairs:
                match_fresh = session.get(MatchDB, match_db.id)
                if not match_fresh:
                    skipped_count += 1
                    progress.update(task, advance=1)
                    continue

                try:
                    result = parser.parse(pdf_path)

                    if result.success and result.match:
                        was_enriched = service.enrich_from_pdf(
                            match_fresh, result.match, force=force,
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
                            'enriched': was_enriched,
                        })

                        if result.diagnostics:
                            warnings_count += result.warnings_count

                        if verbose and was_enriched:
                            m = result.match
                            progress.console.print(
                                f"  [green]✓[/green] {match_fresh.code_match}: "
                                f"{m.equipe_a.nom[:20] if m.equipe_a else '?'} vs "
                                f"{m.equipe_b.nom[:20] if m.equipe_b else '?'}"
                            )

                        progress.update(
                            task, advance=1,
                            description=f"[green]✓ {match_fresh.code_match}[/green]",
                        )
                    else:
                        failed += 1
                        match_fresh.parsing_status = "error"
                        match_fresh.remarques = (
                            result.errors[0][:200] if result.errors else "Erreur de parsing"
                        )
                        error_details.append({
                            'file': str(pdf_path),
                            'errors': result.errors,
                            'diagnostics': result.diagnostics,
                        })
                        progress.update(
                            task, advance=1,
                            description=f"[red]✗ {match_fresh.code_match}[/red]",
                        )

                except Exception as e:
                    failed += 1
                    match_fresh.parsing_status = "error"
                    match_fresh.remarques = str(e)[:200]
                    error_details.append({
                        'file': str(pdf_path), 'errors': [str(e)],
                    })
                    progress.update(
                        task, advance=1,
                        description=f"[red]✗ {match_fresh.code_match}[/red]",
                    )

                # Commit par batch
                if (enriched + failed) % 100 == 0 and (enriched + failed) > 0:
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                        service.clear_caches()

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

    console.print(Panel(
        f"[green]✓ Enrichis :  {enriched}[/green]\n"
        f"[yellow]⏭ Ignorés :   {skipped_count}[/yellow]\n"
        f"[red]✗ Échecs :    {failed}[/red]\n"
        f"[dim]⚠ Warnings :  {warnings_count}[/dim]",
        title="Résumé du parsing",
    ))

    if results or error_details:
        _display_warning_summary(results, error_details, enriched + failed)


def _import_stream(
    *,
    limit: Optional[int] = None,
    saison: Optional[List[str]] = None,
    entity: Optional[List[str]] = None,
    verbose: bool = False,
) -> None:
    """Mode streaming : download → parse → DB, sans conserver les PDFs."""
    import tempfile
    import httpx
    from pyvolley.parsers.factory import ParserFactory
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import MatchDB, ImportLogDB
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
        stmt, _ = add_saison_filter(session, stmt, saison)
        stmt = add_entity_filter(session, stmt, entity)
        stmt = stmt.order_by(MatchDB.code_match)
        if limit:
            stmt = stmt.limit(limit)
        matches = list(session.scalars(stmt).all())

    if not matches:
        console.print("[yellow]Aucun match à traiter[/yellow]")
        return

    console.print(
        f"[blue]⚡ {len(matches)} matchs en streaming "
        f"({parser.name} v{parser.version})[/blue]"
    )

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

            with make_progress(console) as progress:
                task = progress.add_task("Streaming...", total=len(matches))

                for match_db in matches:
                    match_fresh = session.get(MatchDB, match_db.id)
                    if not match_fresh or not match_fresh.source_url:
                        progress.update(task, advance=1)
                        continue

                    try:
                        response = http.get(match_fresh.source_url)
                        response.raise_for_status()

                        if not response.content[:5].startswith(b"%PDF"):
                            raise ValueError("Réponse non-PDF")

                        with tempfile.NamedTemporaryFile(
                            suffix=".pdf", delete=True,
                        ) as tmp:
                            tmp.write(response.content)
                            tmp.flush()
                            result = parser.parse(Path(tmp.name))

                        downloaded += 1

                        if result.success and result.match:
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
                                result.errors[0][:200] if result.errors
                                else "Erreur de parsing"
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

    console.print(
        f"\n[green]✓ {enriched} enrichis[/green]"
        + (f" | [red]{failed} erreurs[/red]" if failed else "")
    )


# ════════════════════════════════════════════════════════════════════
# status — tableau de bord du pipeline
# ════════════════════════════════════════════════════════════════════


@app.command()
def status(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s",
        help="Filtrer par saison (ex: 2024-2025).",
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
        pyvolley status -s 2024-2025
        pyvolley status -v
    """
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import (
        MatchDB, SaisonDB, CompetitionDB, EntiteFFVBDB,
    )
    from sqlalchemy import select, func

    init_db()

    with DatabaseSession() as session:
        # Filtres optionnels
        base_filter = select(MatchDB)
        filter_label = ""

        if saison:
            normalized = saison.replace("/", "-")
            saison_db = session.scalars(
                select(SaisonDB).where(SaisonDB.code == normalized)
            ).first()
            if saison_db:
                base_filter = base_filter.where(
                    MatchDB.saison_id == saison_db.id,
                )
                filter_label += f" | Saison: {saison_db.code}"
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
                f"pyvolley import --only parse --force[/yellow]"
            )


# ════════════════════════════════════════════════════════════════════
# list — consulter les données FFVB
# ════════════════════════════════════════════════════════════════════


list_app = typer.Typer(help="📋 Consulter les données FFVB disponibles")
app.add_typer(list_app, name="list")


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
        None, "--saison", "-s", help="Saison YYYY/YYYY.",
    ),
):
    """📋 Liste les poules disponibles pour une entité."""
    from pyvolley.scrapers.ffvb import FFVBScraper

    scraper = FFVBScraper()

    if saison is None:
        saison = scraper._get_current_saison()

    with console.status(f"[bold blue]Récupération des poules pour {entity}..."):
        poules = scraper.discover_poules(entity, saison)

    if not poules:
        console.print(f"[yellow]Aucune poule trouvée pour {entity}[/yellow]")
        return

    table = Table(title=f"📋 Poules — {entity} — {saison}")
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
        None, "--saison", "-s", help="Saison YYYY/YYYY.",
    ),
    limit: int = typer.Option(
        50, "--limit", "-n", help="Nombre max à afficher.",
    ),
):
    """📋 Liste les matchs disponibles pour une entité."""
    from pyvolley.scrapers.ffvb import FFVBScraper

    scraper = FFVBScraper()
    if saison is None:
        saison = scraper._get_current_saison()

    with console.status(f"[bold blue]Récupération des matchs pour {entity}..."):
        export_matches = scraper.scrape_entity(entity, saison, poule=poule)

    if not export_matches:
        console.print("[yellow]Aucun match trouvé[/yellow]")
        return

    table = Table(title=f"📋 Matchs — {entity} — {saison}")
    table.add_column("Code", style="cyan", no_wrap=True)
    table.add_column("Poule", style="white")
    table.add_column("Date", style="dim")
    table.add_column("Équipe A", style="white")
    table.add_column("Équipe B", style="white")
    table.add_column("Score", style="green")
    table.add_column("PDF", style="green")

    for m in export_matches[:limit]:
        date_str = m.date.strftime("%d/%m/%Y") if m.date else "—"
        score = f"{m.score_a}-{m.score_b}" if m.score_a is not None else "—"
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


# ════════════════════════════════════════════════════════════════════
# parse — analyse de PDF standalone
# ════════════════════════════════════════════════════════════════════


@app.command()
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
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Afficher les détails.",
    ),
):
    """
    📄 Analyser des feuilles de match PDF.

    Parse un ou plusieurs fichiers PDF et affiche les résultats.
    Cette commande est indépendante de la base de données — pour importer
    des données en base, utilisez ``pyvolley import``.

    Exemples :

        pyvolley parse match.pdf
        pyvolley parse data/pdfs/ -n 10
        pyvolley parse match.pdf -o resultat.json -v
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

    parser = ParserFactory.get_default()
    console.print(
        f"[blue]Parser : {parser.name} v{parser.version} — "
        f"{len(pdf_files)} fichier(s)[/blue]\n"
    )

    results = []
    successful = 0
    failed = 0

    with make_progress(console) as progress:
        task = progress.add_task("Parsing...", total=len(pdf_files))

        for pdf_file in pdf_files:
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

                    if verbose:
                        m = result.match
                        progress.console.print(
                            f"  [green]✓[/green] {pdf_file.name}: "
                            f"{m.code_match} — "
                            f"{m.equipe_a.nom[:20] if m.equipe_a else '?'} vs "
                            f"{m.equipe_b.nom[:20] if m.equipe_b else '?'}"
                        )
                        if result.diagnostics:
                            for d in result.diagnostics:
                                progress.console.print(
                                    f"      [yellow]⚠ {d}[/yellow]"
                                )

                    progress.update(
                        task, advance=1,
                        description=f"[green]✓ {pdf_file.name[:30]}[/green]",
                    )
                else:
                    failed += 1
                    msg = result.errors[0][:60] if result.errors else "Erreur"
                    if verbose:
                        progress.console.print(
                            f"  [red]✗[/red] {pdf_file.name}: {msg}"
                        )
                    progress.update(
                        task, advance=1,
                        description=f"[red]✗ {pdf_file.name[:30]}[/red]",
                    )

            except Exception as e:
                failed += 1
                progress.update(
                    task, advance=1,
                    description=f"[red]✗ {pdf_file.name[:30]}[/red]",
                )

    console.print(Panel(
        f"[green]✓ Parsés : {successful}[/green]\n"
        f"[red]✗ Échecs : {failed}[/red]",
        title="Résultat",
    ))

    # Export JSON
    if output and results:
        export_data = [
            {
                'file': r['file'],
                'parse_time_ms': r['parse_time_ms'],
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


# ════════════════════════════════════════════════════════════════════
# cleanup — nettoyage des PDFs
# ════════════════════════════════════════════════════════════════════


@app.command()
def cleanup(
    target: str = typer.Argument(
        "pdfs",
        help="Cible : 'pdfs' (parsés), 'orphans' (sans match en DB), 'all'.",
    ),
    saison: Optional[List[str]] = typer.Option(
        None, "--saison", "-s", help="Filtrer par saison.",
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
        pyvolley cleanup all -s 2024-2025
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
        normalized = [s.replace("/", "-") for s in saison]
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
        code = stem.split("_", 1)[1] if "_" in stem else stem
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


# ════════════════════════════════════════════════════════════════════
# serve, simulate, stats, init
# ════════════════════════════════════════════════════════════════════


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Adresse d'écoute."),
    port: int = typer.Option(8000, "--port", "-p", help="Port d'écoute."),
    reload: bool = typer.Option(False, "--reload", "-r", help="Rechargement auto."),
):
    """🌐 Lance le serveur web."""
    import uvicorn

    console.print(f"[blue]🏐 PyVolley sur http://{host}:{port}[/blue]")
    uvicorn.run("pyvolley.web.app:web_app", host=host, port=port, reload=reload)


@app.command()
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


@app.command()
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


@app.command("compute-stats")
def compute_stats(
    saison_id: Optional[int] = typer.Option(
        None, "--saison-id", help="Restreindre au calcul pour une saison (ID).",
    ),
    force: bool = typer.Option(
        False, "--force", help="Recalculer même si le cache est à jour.",
    ),
    clear: bool = typer.Option(
        False, "--clear", help="Vider le cache avant de recalculer.",
    ),
):
    """🔢 Pré-calcule les statistiques palmarès et les stocke en base.

    Par défaut, calcule les statistiques pour les combinaisons les plus
    courantes de filtres (toutes saisons confondues + chaque saison).
    Utilisez ``--force`` pour forcer le recalcul même si le cache est déjà
    à jour.
    """
    from pyvolley.database.connection import get_db, init_db
    from pyvolley.database.repositories import (
        StatsCacheRepository, MatchRepository, SaisonRepository,
    )
    from pyvolley.database.stats_service import StatsAmusantesService, StatsFilters

    init_db()

    with get_db() as session:
        if clear:
            repo = StatsCacheRepository(session)
            deleted = repo.delete_all()
            session.commit()
            console.print(f"[yellow]🗑 Cache vidé ({deleted} entrée(s) supprimée(s))[/yellow]")

        match_count = MatchRepository(session).count()
        if match_count == 0:
            console.print("[yellow]⚠ Aucun match en base — rien à calculer.[/yellow]")
            return

        # Construire la liste des combinaisons de filtres à précalculer
        filters_to_compute: list[StatsFilters] = [StatsFilters()]  # global (aucun filtre)

        if saison_id is not None:
            filters_to_compute.append(StatsFilters(saison_id=saison_id))
        else:
            saisons = SaisonRepository(session).get_all(limit=50)
            for s in saisons:
                filters_to_compute.append(StatsFilters(saison_id=s.id))

        service = StatsAmusantesService(session)
        cache_repo = StatsCacheRepository(session)

        computed = 0
        skipped = 0

        table = Table(title="🔢 Calcul des statistiques palmarès")
        table.add_column("Filtre", style="cyan")
        table.add_column("Statut", style="green")
        table.add_column("Matchs", justify="right")

        for f in filters_to_compute:
            key = service.build_filter_key(f)
            label = key

            if not force and not cache_repo.is_stale(key, match_count):
                table.add_row(label, "[dim]à jour[/dim]", str(match_count))
                skipped += 1
                continue

            try:
                stats_data = service.get_all_stats(f)
                cache_repo.upsert(key, stats_data, match_count)
                session.commit()
                table.add_row(label, "[green]✓ calculé[/green]", str(match_count))
                computed += 1
            except Exception as exc:
                session.rollback()
                table.add_row(label, f"[red]✗ {exc}[/red]", str(match_count))

        console.print(table)
        console.print(
            f"[green]✓ {computed} combinaison(s) calculée(s)[/green], "
            f"[dim]{skipped} déjà à jour[/dim]"
        )


# ════════════════════════════════════════════════════════════════════
# init — initialiser la base de données
# ════════════════════════════════════════════════════════════════════


@app.command("init")
def init_database():
    """🔧 Initialise la base de données."""
    from pyvolley.database.connection import init_db

    console.print("[blue]Initialisation de la base de données...[/blue]")
    init_db()
    console.print(f"[green]✓ Base créée : {settings.database_url}[/green]")


# ════════════════════════════════════════════════════════════════════
# db — gestion de la base de données
# ════════════════════════════════════════════════════════════════════


db_app = typer.Typer(help="🗄️ Gestion de la base de données")
app.add_typer(db_app, name="db")

# Sous-commandes d'exploration
from pyvolley.cli.db_explorer import explore_app
db_app.add_typer(explore_app, name="explore")

# Sous-commandes de rapports
from pyvolley.cli.reports import report_app
app.add_typer(report_app, name="report")


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


# ════════════════════════════════════════════════════════════════════
# Helpers internes
# ════════════════════════════════════════════════════════════════════


def _cleanup_parsed_pdfs(
    *,
    saison: Optional[List[str]] = None,
    verbose: bool = False,
) -> None:
    """Supprime les PDFs des matchs parsés avec succès."""
    from pyvolley.database.connection import DatabaseSession
    from pyvolley.database.models import MatchDB
    from sqlalchemy import select

    with DatabaseSession() as session:
        parsed_codes = set(session.scalars(
            select(MatchDB.code_match).where(MatchDB.parsing_status == "parsed")
        ).all())

    if not parsed_codes:
        return

    pdf_base = Path("data/pdfs")
    if not pdf_base.exists():
        return

    deleted = 0
    for pdf_file in pdf_base.glob("**/*.pdf"):
        stem = pdf_file.stem
        code = stem.split("_", 1)[1] if "_" in stem else stem
        if code in parsed_codes or stem in parsed_codes:
            # Filtrer par saison si demandé
            if saison:
                normalized = [s.replace("/", "-") for s in saison]
                if not any(ns in str(pdf_file) for ns in normalized):
                    continue
            try:
                pdf_file.unlink()
                deleted += 1
            except Exception:
                pass

    if deleted:
        console.print(f"[dim]🗑 {deleted} PDFs supprimés (déjà parsés)[/dim]")


def _display_warning_summary(
    results: list[dict],
    error_details: list[dict],
    total_parsed: int,
) -> None:
    """Affiche un récapitulatif des diagnostics de parsing."""
    from collections import Counter
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


# ════════════════════════════════════════════════════════════════════
# Point d'entrée
# ════════════════════════════════════════════════════════════════════


def main():
    """Point d'entrée principal."""
    app()


if __name__ == "__main__":
    main()
