"""Commande CLI `pyvolley import` (pipeline unifié : scrape -> download -> parse)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, date as dt_date
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
    format_saison_short,
    saisons_to_db_codes,
    display_entities,
    build_pdf_index,
    find_pdf_for_match,
    add_saison_filter,
    add_entity_filter,
    make_progress,
    format_entities_display,
    configure_parser_plausibility,
    PipelineTimer,
    format_duration,
    format_rate,
)
from pyvolley.cli.plausibility_cli import (
    apply_plausibility_core_to_match_db,
    build_plausibility_reviewer,
    display_plausibility_summary,
    display_warning_summary,
)
from pyvolley.shared.pdf_storage import (
    build_pdf_storage_path,
    extract_match_code_from_pdf_path,
)

console = Console()
_configure_parser_plausibility = configure_parser_plausibility


def _is_local_pdf_usable(pdf_path: Path, *, min_size_bytes: int = 1024) -> bool:
    """Retourne True si un PDF local semble exploitable pour le parsing."""
    try:
        if not pdf_path.exists() or not pdf_path.is_file():
            return False

        size = pdf_path.stat().st_size
        if size < min_size_bytes:
            return False

        with open(pdf_path, "rb") as f:
            if not f.read(5).startswith(b"%PDF"):
                return False

            # Vérifie la fin du flux PDF sur un petit tail pour éviter
            # de relire tout le fichier.
            tail_size = min(size, 1024)
            f.seek(-tail_size, 2)
            tail = f.read(tail_size)
            if b"%%EOF" not in tail:
                return False

        return True
    except OSError:
        return False


def _get_pdf_redownload_reason(
    match_db,
    pdf_path: Path,
    *,
    today: Optional[dt_date] = None,
) -> Optional[str]:
    """Retourne la raison d'un retéléchargement nécessaire, sinon None.

    Raisons:
      - ``invalid-local-pdf``: fichier local corrompu/incomplet.
      - ``downloaded-before-match-date``: PDF obtenu avant la date du match,
        potentiellement une feuille vide de pré-match.
    """
    if not _is_local_pdf_usable(pdf_path):
        return "invalid-local-pdf"

    if today is None:
        today = dt_date.today()

    match_date = getattr(match_db, "date_match", None)
    if not isinstance(match_date, dt_date):
        return None
    if match_date > today:
        return None

    try:
        downloaded_on = datetime.fromtimestamp(pdf_path.stat().st_mtime).date()
    except OSError:
        return "invalid-local-pdf"

    if downloaded_on < match_date:
        return "downloaded-before-match-date"

    return None


# ════════════════════════════════════════════════════════════════════
# import — pipeline unifié : scrape → download → parse
# ════════════════════════════════════════════════════════════════════


def import_data(
    entity: Optional[List[str]] = typer.Option(
        None, "--entity", "-e",
        help="Code de l'entité (ex: ABCCS, LIRA). Répétable.",
    ),
    saison: Optional[List[str]] = typer.Option(
        None, "--saison", "-s",
        help="Saison au format YY/YY (ex: 23/24). Accepte les plages (ex: 22/25). Répétable.",
    ),
    entity_type: Optional[str] = typer.Option(
        None, "--type", "-t",
        help="Filtrer par type d'entité : nationale, ligue, comite.",
    ),
    all_entities: bool = typer.Option(
        False, "--all",
        help="Traiter toutes les entités.",
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
    force_club_enrichment: bool = typer.Option(
        False, "--force-club-enrichment",
        help="Ré-enrichir les clubs même s'ils ont déjà des données adressier.",
    ),
    enrich_clubs: bool = typer.Option(
        True, "--enrich-clubs/--no-enrich-clubs",
        help="Actualiser les informations des clubs (adressier FFVB) en fin de scrape.",
    ),
    geocode: bool = typer.Option(
        True, "--geocode/--no-geocode",
        help="Géocoder les adresses des salles et des clubs lors de l'enrichissement.",
    ),
    keep_pdfs: bool = typer.Option(
        True, "--keep-pdfs/--no-keep-pdfs",
        help="Conserver les PDFs après parsing. --no-keep-pdfs libère l'espace.",
    ),
    concurrent: int = typer.Option(
        10, "--concurrent", "-c",
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
    plausibility: bool = typer.Option(
        True, "--plausibility/--no-plausibility",
        help="Activer les contrôles de vraisemblance et auto-corrections.",
    ),
    plausibility_policy: str = typer.Option(
        "auto", "--plausibility-policy",
        help="Politique: auto, report-only, strict.",
    ),
    review_fixes: bool = typer.Option(
        False, "--review-fixes",
        help="Demander validation manuelle pour les corrections proposées.",
    ),
    parser_name: str = typer.Option(
        "fast", "--parser", "-p",
        help="Parser à utiliser : 'fast' (FastMatchSheetParser) ou 'legacy' (MatchSheetParser).",
    ),
    verify_existing: bool = typer.Option(
        False, "--verify-existing",
        help="Re-vérifier l'intégrité de tous les PDFs déjà téléchargés en base.",
    ),
    rollup: bool = typer.Option(
        True, "--rollup/--no-rollup",
        help="Actualiser les statistiques agglomérées (rollups) à la fin de l'import.",
    ),
    defer_player_stats: bool = typer.Option(
        True, "--defer-player-stats/--no-defer-player-stats",
        help="Calculer les statistiques joueurs en lot à la fin plutôt qu'en ligne (plus rapide).",
    ),
    refresh_cache: bool = typer.Option(
        False, "--refresh-cache", "-R",
        help="Forcer le re-téléchargement des exports CSV sans utiliser le cache disque.",
    ),
    delay: Optional[float] = typer.Option(
        None, "--delay", "-d",
        help="Délai entre requêtes en secondes (défaut: 0s pour downloads concurrents, sinon settings.ffvb_request_delay).",
    ),
    timing_detail: str = typer.Option(
        "summary", "--timing-detail", "--timing-summary", "-T",
        help="Niveau de détail du récapitulatif des temps : 'none' (désactivé), 'summary' (étapes principales) ou 'detailed' (sous-étapes et débits).",
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
        pyvolley import -e ABCCS -s 23/24
        pyvolley import -e ABCCS -s 22/25
        pyvolley import --type ligue
        pyvolley import --only scrape -e ABCCS
        pyvolley import --only parse --force
        pyvolley import --no-keep-pdfs -e ABCCS
        pyvolley import --dry-run --all
        pyvolley import -e ABCCS --timing-detail detailed
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
    dispatcher = sys.modules.get("pyvolley.cli.main") or sys.modules[__name__]
    entities_to_process = getattr(dispatcher, "resolve_entities", resolve_entities)(
        scraper, entity=entity, entity_type=entity_type,
        all_entities=all_entities,
    )
    try:
        saisons = getattr(dispatcher, "resolve_saisons", resolve_saisons)(scraper, saison)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    # Vérifier qu'on a des entités pour l'étape scrape
    if "scrape" in steps and not entities_to_process:
        console.print("[yellow]Aucune entité spécifiée.[/yellow]")
        display_entities(scraper, console)
        console.print("\n[blue]Utilisez -e CODE, --type TYPE, ou --all[/blue]")
        raise typer.Exit(0)

    # Afficher la configuration
    entities_display = format_entities_display(entities_to_process)
    saisons_display = ", ".join(format_saison_short(s) for s in saisons)

    console.print(Panel(
        f"[bold blue]🔄 Import FFVB[/bold blue]\n\n"
        f"Étapes :     [cyan]{' → '.join(steps)}[/cyan]\n"
        f"Parser :     [cyan]{parser_name}[/cyan]\n"
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

    dispatcher = sys.modules.get("pyvolley.cli.main") or sys.modules[__name__]
    timer = PipelineTimer(label="Pipeline Import FFVB")

    # ── Étape 1 : Scrape ───────────────────────────────────────────
    if "scrape" in steps:
        with timer.step("scrape", "1. Scrape (Exports CSV & Clubs)", items_unit="matchs"):
            getattr(dispatcher, "_import_scrape", _import_scrape)(
                scraper,
                entities_to_process,
                saisons,
                verbose=verbose,
                force_club_enrichment=force_club_enrichment,
                enrich_clubs=enrich_clubs,
                geocode=geocode,
                refresh_cache=refresh_cache,
                timer=timer,
            )

    # ── Étape 2 : Download ─────────────────────────────────────────
    if "download" in steps:
        if not keep_pdfs and "parse" in steps:
            # Mode streaming : download + parse en une passe
            console.print(
                "\n[bold blue]═══ Download + Parse (streaming) ═══[/bold blue]"
            )
            with timer.step("stream", "2. Streaming (Download + Parse)", items_unit="matchs"):
                getattr(dispatcher, "_import_stream", _import_stream)(
                    limit=limit, saison=saisons, entity=entity, verbose=verbose,
                    concurrent=concurrent,
                    plausibility=plausibility,
                    plausibility_policy=plausibility_policy,
                    review_fixes=review_fixes,
                    parser_name=parser_name,
                    rollup=rollup,
                    defer_player_stats=defer_player_stats,
                    timer=timer,
                )
            steps = [s for s in steps if s != "parse"]
        else:
            console.print("\n[bold blue]═══ Download ═══[/bold blue]")
            with timer.step("download", "2. Download (Feuilles PDF)", items_unit="PDFs"):
                getattr(dispatcher, "_import_download", _import_download)(
                    limit=limit, saison=saisons, concurrent=concurrent,
                    entity=entity,
                    verbose=verbose,
                    verify_existing=verify_existing,
                    delay=delay,
                    timer=timer,
                )

    # ── Étape 3 : Parse ───────────────────────────────────────────
    if "parse" in steps:
        console.print("\n[bold blue]═══ Parse ═══[/bold blue]")
        with timer.step("parse", "3. Parse & Enrichissement", items_unit="matchs"):
            getattr(dispatcher, "_import_parse", _import_parse)(
                limit=limit, saison=saisons, entity=entity,
                force=force, verbose=verbose,
                plausibility=plausibility,
                plausibility_policy=plausibility_policy,
                review_fixes=review_fixes,
                parser_name=parser_name,
                rollup=rollup,
                defer_player_stats=defer_player_stats,
                timer=timer,
            )

        # Nettoyage post-parse si --no-keep-pdfs
        if not keep_pdfs:
            getattr(dispatcher, "_cleanup_parsed_pdfs", _cleanup_parsed_pdfs)(
                saison=saisons, verbose=verbose, timer=timer,
            )

    timer.stop_pipeline()
    console.print(Panel(
        f"[bold green]Pipeline terminé avec succès en {format_duration(timer.total_duration)}[/bold green]",
        title="✅ Terminé",
    ))
    timer.display_summary(
        console,
        detail_level=timing_detail,
        title="⏱️ Récapitulatif du Pipeline d'Import",
    )


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
    force_club_enrichment: bool = False,
    enrich_clubs: bool = True,
    geocode: bool = True,
    refresh_cache: bool = False,
    timer: Optional[PipelineTimer] = None,
) -> None:
    """Étape 1 : scrape des exports CSV et import en base."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pyvolley.database.connection import DatabaseSession
    from pyvolley.database.export_import_service import ExportImportService
    from pyvolley.scrapers.ffvb.adressier_scraper import fetch_adressier
    from pyvolley.scrapers.ffvb.export_scraper import get_unique_poules
    from pyvolley.cli.helpers import expand_saison_inputs

    console.print("\n[bold blue]═══ Scrape ═══[/bold blue]")

    t_scrape_start = time.perf_counter()
    total_imported = 0
    total_updated = 0
    total_clubs = 0

    poules_by_entity: dict[str, set[str]] = {}
    saisons_by_entity: dict[str, set[str]] = {}

    def _process_export(target_entity: str, target_saison: str, export_data: list) -> None:
        nonlocal total_imported, total_updated
        if not export_data:
            console.print(f"\n[blue]{target_entity} — {target_saison}[/blue]")
            console.print("  [yellow]Aucun match trouvé[/yellow]")
            return

        played = sum(1 for m in export_data if m.match_joue)
        poules = get_unique_poules(export_data)
        console.print(f"\n[blue]{target_entity} — {target_saison}[/blue]")
        console.print(
            f"  [green]✓ {len(export_data)} matchs[/green] "
            f"({played} joués, {len(poules)} poules)"
        )

        poule_codes = {
            (m.poule_code_ffvb or m.poule_code)
            for m in export_data
            if (m.poule_code_ffvb or m.poule_code)
        }
        if poule_codes:
            poules_by_entity.setdefault(target_entity, set()).update(poule_codes)
        saisons_by_entity.setdefault(target_entity, set()).add(target_saison)

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
            session.commit()

    tasks = [(target_entity, target_saison) for target_saison in saisons for target_entity in entities]
    scrape_kwargs = {"force_refresh": refresh_cache} if refresh_cache else {}

    t_csv_start = time.perf_counter()
    if len(tasks) > 1:
        max_workers = min(8, len(tasks))
        console.print(
            f"[cyan]Téléchargement parallèle des exports ({len(tasks)} cibles, {max_workers} workers)...[/cyan]"
        )
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(scraper.scrape_entity, ent, sais, **scrape_kwargs): (ent, sais)
                for ent, sais in tasks
            }
            for future in as_completed(future_to_task):
                ent, sais = future_to_task[future]
                try:
                    export_data = future.result()
                except Exception as e:
                    console.print(f"\n[blue]{ent} — {sais}[/blue]")
                    console.print(f"  [red]Erreur : {e}[/red]")
                    continue
                _process_export(ent, sais, export_data)
    else:
        for target_entity, target_saison in tasks:
            try:
                with console.status(
                    f"[bold blue]Récupération export CSV pour {target_entity} ({target_saison})..."
                ):
                    export_data = scraper.scrape_entity(target_entity, target_saison, **scrape_kwargs)
            except Exception as e:
                console.print(f"\n[blue]{target_entity} — {target_saison}[/blue]")
                console.print(f"  [red]Erreur : {e}[/red]")
                continue
            _process_export(target_entity, target_saison, export_data)
    csv_duration = time.perf_counter() - t_csv_start

    # ── Enrichissement consolidé des clubs à la fin du scrape ──────────
    clubs_duration = 0.0
    if enrich_clubs and poules_by_entity:
        t_clubs_start = time.perf_counter()
        console.print("\n[bold magenta]═══ Actualisation des clubs (adressier FFVB) ═══[/bold magenta]")
        for target_entity, poule_set in poules_by_entity.items():
            if not poule_set:
                continue

            entity_saisons = list(saisons_by_entity.get(target_entity, []))
            # Normaliser et trier pour retenir la saison la plus récente (ex: 2024/2025 > 2023/2024)
            expanded_saisons = expand_saison_inputs(entity_saisons) if entity_saisons else []
            expanded_saisons.sort(reverse=True)
            latest_saison = expanded_saisons[0] if expanded_saisons else (saisons[-1] if saisons else "2024/2025")

            sorted_poules = sorted(poule_set)
            with console.status(
                f"[bold magenta]Enrichissement clubs pour {target_entity} "
                f"({len(sorted_poules)} poules, saison récente: {latest_saison})..."
            ):
                try:
                    fetch_kwargs = {"force_refresh": True} if refresh_cache else {}
                    clubs_info = fetch_adressier(
                        scraper.client,
                        scraper.base_url,
                        target_entity,
                        latest_saison,
                        sorted_poules,
                        **fetch_kwargs,
                    )
                except Exception as e:
                    console.print(f"  [red]Erreur adressier pour {target_entity} : {e}[/red]")
                    continue

            if clubs_info:
                with DatabaseSession() as session:
                    service = ExportImportService(session)
                    club_stats = service.enrich_clubs(
                        clubs_info,
                        target_entity,
                        latest_saison,
                        scraper.base_url,
                        force_reenrich=force_club_enrichment,
                        geocode=geocode,
                    )
                    session.commit()
                    enriched = club_stats.get("enriched", 0)
                    created = club_stats.get("created", 0)
                    skipped = club_stats.get("skipped", 0)
                    total_clubs += enriched + created
                    console.print(
                        f"  [magenta]{target_entity}[/magenta] : "
                        f"[magenta]{created} créés, {enriched} enrichis, {skipped} ignorés[/magenta]"
                    )
            else:
                console.print(
                    f"  [yellow]Aucun club récupéré pour {target_entity} via l'adressier[/yellow]"
                )
        clubs_duration = time.perf_counter() - t_clubs_start

    total_scrape_duration = time.perf_counter() - t_scrape_start
    total_processed = total_imported + total_updated
    rate_str = format_rate(total_processed, total_scrape_duration, "matchs")

    console.print(
        f"\n[green]✓ Scrape terminé en {format_duration(total_scrape_duration)} : "
        f"{total_imported} importés, {total_updated} mis à jour, "
        f"{total_clubs} clubs enrichis ({rate_str})[/green]"
    )

    if timer:
        timer.record_sub_step(
            "scrape", "csv_import", "Téléchargement & Import CSV",
            csv_duration, items_count=total_processed, items_unit="matchs",
        )
        if enrich_clubs and poules_by_entity:
            timer.record_sub_step(
                "scrape", "clubs_enrich", "Actualisation Clubs & Salles",
                clubs_duration, items_count=total_clubs, items_unit="clubs",
            )



def _import_download(
    *,
    limit: Optional[int] = None,
    saison: Optional[List[str]] = None,
    entity: Optional[List[str]] = None,
    concurrent: int = 5,
    verbose: bool = False,
    verify_existing: bool = False,
    delay: Optional[float] = None,
    timer: Optional[PipelineTimer] = None,
) -> None:
    """Étape 2 : téléchargement concurrent des PDFs.

    Procède en trois phases :
    1. Prépare la liste des téléchargements (marque les existants)
    2. Télécharge les fichiers manquants (async concurrent)
    3. Met à jour la base de données en batch
    """
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import MatchDB, SaisonDB, CompetitionDB
    from sqlalchemy import or_, select
    from sqlalchemy.orm import joinedload

    init_db()
    today = dt_date.today()
    t_dl_start = time.perf_counter()

    # Phase 1 : préparer les téléchargements
    download_tasks: list[tuple[int, str, Path]] = []
    already_present: list[tuple[int, str]] = []  # (match_id, pdf_path)
    forced_redownload = {
        "invalid-local-pdf": 0,
        "downloaded-before-match-date": 0,
    }

    status_filter = (
        ["discovered", "downloaded", "error"]
        if verify_existing
        else ["discovered", "error"]
    )

    with DatabaseSession() as session:
        stmt = (
            select(MatchDB)
            .options(joinedload(MatchDB.saison))
            .options(joinedload(MatchDB.competition).joinedload(CompetitionDB.entite))
            .options(joinedload(MatchDB.poule))
            .where(
                MatchDB.match_joue == True,  # noqa: E712
                MatchDB.source_url.isnot(None),
                MatchDB.parsing_status.in_(status_filter),
                or_(
                    MatchDB.date_match.is_(None),
                    MatchDB.date_match <= today,
                ),
            )
        )
        stmt, _ = add_saison_filter(session, stmt, saison)
        stmt = add_entity_filter(session, stmt, entity)
        stmt = stmt.order_by(MatchDB.code_match)
        if limit:
            stmt = stmt.limit(limit)
        matches = list(session.scalars(stmt).all())

        if not matches:
            console.print("[yellow]Aucun match à télécharger[/yellow]")
            return

        console.print(f"[blue]📥 {len(matches)} matchs à traiter[/blue]")
        if verbose:
            console.print("[dim]Mode verbeux: affichage des URLs, des skips et des erreurs de téléchargement.[/dim]")

        pdf_base = Path("data/pdfs")

        for match_db in matches:
            if not match_db.source_url:
                continue

            saison_code = match_db.saison.code if match_db.saison else "unknown"

            entite_code = getattr(
                getattr(match_db.competition, "entite", None),
                "code",
                None,
            )
            poule_code = getattr(match_db.poule, "code", None)
            dest_file = build_pdf_storage_path(
                pdf_base,
                saison_code=saison_code,
                entite_code=entite_code,
                poule_code=poule_code,
                match_code=match_db.code_match,
                journee=match_db.journee,
                unique_hint=match_db.id,
            )

            # Vérifier si déjà présent en O(1)
            existing = None
            if dest_file.exists():
                existing = dest_file
            else:
                existing = find_pdf_for_match(
                    match_db,
                    pdf_base,
                    saison_code=saison_code,
                )

            if existing:
                redownload_reason = (
                    _get_pdf_redownload_reason(match_db, existing, today=today)
                    if verify_existing
                    else None
                )
                if redownload_reason is None:
                    already_present.append((match_db.id, str(existing)))
                    if verbose:
                        console.print(
                            f"[dim]↷ {match_db.code_match} déjà présent: {existing}[/dim]"
                        )
                    continue

                forced_redownload[redownload_reason] += 1
                if verbose:
                    console.print(
                        f"[yellow]↻ {match_db.code_match} retéléchargement forcé: {redownload_reason}[/yellow]"
                    )
                try:
                    existing.unlink()
                except OSError:
                    # Non bloquant: le téléchargement écrira la nouvelle cible.
                    pass

            download_tasks.append((match_db.id, match_db.source_url, dest_file))
            if verbose:
                console.print(
                    f"[dim]→ {match_db.code_match} | {match_db.source_url} -> {dest_file}[/dim]"
                )

        # Mettre à jour les matchs dont le PDF existe déjà
        if already_present:
            matches_by_id = {m.id: m for m in matches}
            for match_id, pdf_path in already_present:
                m = matches_by_id.get(match_id)
                if m:
                    m.parsing_status = "downloaded"
                    m.source_pdf = pdf_path
            session.commit()
            console.print(f"[dim]⏭ {len(already_present)} PDFs déjà présents[/dim]")

        forced_total = sum(forced_redownload.values())
        if forced_total:
            details = []
            if forced_redownload["invalid-local-pdf"]:
                details.append(f"{forced_redownload['invalid-local-pdf']} invalides")
            if forced_redownload["downloaded-before-match-date"]:
                details.append(
                    f"{forced_redownload['downloaded-before-match-date']} antérieurs à la date du match"
                )
            console.print(
                "[dim]↻ Retéléchargement forcé : " + ", ".join(details) + "[/dim]"
            )

    phase1_duration = time.perf_counter() - t_dl_start

    if not download_tasks:
        if timer:
            timer.record_sub_step(
                "download", "local_check", "Vérification locale des PDFs",
                phase1_duration, items_count=len(matches), items_unit="fichiers",
            )
        return

    console.print(f"[blue]⬇ {len(download_tasks)} à télécharger[/blue]")

    # Phase 2 : téléchargement concurrent (pas d'accès DB ici)
    # Résultats : (match_id, dest_path, success, error_msg)
    dl_results: list[tuple[int, Path, bool, str]] = []

    t_p2_start = time.perf_counter()

    async def _run():
        from pyvolley.scrapers.async_http_client import AsyncHttpClient

        # Concurrency semaphore is already managed inside AsyncHttpClient.
        # Default request_delay is 0.0s for concurrent downloads unless specified.
        effective_delay = delay if delay is not None else 0.0
        async with AsyncHttpClient(
            request_delay=effective_delay,
            max_concurrent=concurrent,
            burst=concurrent,
        ) as client:
            with make_progress(console) as progress:
                task_id = progress.add_task(
                    "Téléchargement...", total=len(download_tasks),
                )

                async def _dl_one(match_id: int, url: str, dest: Path):
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
                        error_msg = str(e)[:200]
                        dl_results.append((match_id, dest, False, error_msg))
                        if verbose:
                            console.print(
                                f"[red]✗ {dest.stem}: {error_msg}[/red]"
                            )
                        progress.update(
                            task_id, advance=1,
                            description=f"[red]✗ {dest.stem}[/red]",
                        )

                await asyncio.gather(
                    *[_dl_one(mid, url, d) for mid, url, d in download_tasks]
                )

    asyncio.run(_run())
    phase2_duration = time.perf_counter() - t_p2_start

    # Phase 3 : mise à jour DB en batch
    t_p3_start = time.perf_counter()
    downloaded = 0
    failed = 0

    batch_size = 200
    with DatabaseSession() as session:
        for i in range(0, len(dl_results), batch_size):
            chunk = dl_results[i : i + batch_size]
            chunk_ids = [mid for mid, _, _, _ in chunk]
            matches_chunk = {
                m.id: m
                for m in session.scalars(
                    select(MatchDB).where(MatchDB.id.in_(chunk_ids))
                ).all()
            }
            for match_id, dest, success, error_msg in chunk:
                m = matches_chunk.get(match_id)
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

            try:
                session.commit()
            except Exception:
                session.rollback()

    phase3_duration = time.perf_counter() - t_p3_start
    total_dl_duration = time.perf_counter() - t_dl_start
    dl_rate = format_rate(downloaded, phase2_duration, "PDFs")

    console.print(
        f"\n[green]✓ {downloaded} téléchargés en {format_duration(total_dl_duration)} ({dl_rate})[/green]"
        + (f" | [dim]{len(already_present)} déjà présents[/dim]" if already_present else "")
        + (f" | [red]{failed} erreurs[/red]" if failed else "")
    )
    if verbose and failed:
        console.print("[bold red]Détails des erreurs de téléchargement :[/bold red]")
        for match_id, dest, success, error_msg in dl_results:
            if not success:
                console.print(f"[red]- {dest.stem}: {error_msg}[/red]")

    if timer:
        timer.record_sub_step(
            "download", "local_check", "Vérification locale des PDFs",
            phase1_duration, items_count=len(matches), items_unit="fichiers",
        )
        timer.record_sub_step(
            "download", "async_fetch", "Téléchargement réseau concurrent",
            phase2_duration, items_count=downloaded, items_unit="PDFs",
        )
        timer.record_sub_step(
            "download", "db_update", "Mise à jour des statuts en base",
            phase3_duration, items_count=downloaded + failed, items_unit="matchs",
        )


def _import_parse(
    *,
    limit: Optional[int] = None,
    saison: Optional[List[str]] = None,
    entity: Optional[List[str]] = None,
    force: bool = False,
    verbose: bool = False,
    plausibility: bool = True,
    plausibility_policy: str = "auto",
    review_fixes: bool = False,
    parser_name: str = "fast",
    rollup: bool = True,
    defer_player_stats: bool = True,
    timer: Optional[PipelineTimer] = None,
) -> None:
    """Étape 3 : parsing des PDFs et enrichissement de la base."""
    from pyvolley.parsers.factory import ParserFactory
    from pyvolley.database.connection import DatabaseSession, init_db, sqlite_bulk_mode
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import (
        MatchDB, ImportLogDB, CompetitionDB, SaisonDB, PouleDB, EntiteFFVBDB
    )
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    init_db()
    t_parse_start = time.perf_counter()
    statuses = ["downloaded"]
    if force:
        statuses.extend(["parsed", "error"])

    parser = ParserFactory.get(parser_name)
    approval_cb = None
    if review_fixes:
        approval_cb = build_plausibility_reviewer(console)
    _configure_parser_plausibility(
        parser,
        enabled=plausibility,
        policy=plausibility_policy,
        approval=approval_cb,
    )

    with DatabaseSession() as session:
        stmt = (
            select(
                MatchDB.id,
                MatchDB.code_match,
                MatchDB.source_pdf,
                MatchDB.journee,
                SaisonDB.code.label("saison_code"),
                EntiteFFVBDB.code.label("entite_code"),
                PouleDB.code.label("poule_code"),
            )
            .join(MatchDB.saison, isouter=True)
            .join(MatchDB.competition, isouter=True)
            .join(CompetitionDB.entite, isouter=True)
            .join(MatchDB.poule, isouter=True)
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
        matches_db = list(session.execute(stmt).all())

    if not matches_db:
        console.print(
            f"[yellow]Aucun match à parser (statuts : {', '.join(statuses)})[/yellow]"
        )
        return

    # Localiser les PDFs (résolution directe O(1) d'abord, sans glob disque global)
    pdf_base = Path("data/pdfs")
    pdf_index = None

    match_pdf_pairs = []
    missing_matches = []
    for m in matches_db:
        pdf_path = find_pdf_for_match(m, pdf_base, pdf_index)
        if pdf_path:
            match_pdf_pairs.append((m.id, pdf_path))
        else:
            missing_matches.append(m)

    # Si certains fichiers ne sont pas trouvés aux chemins standard,
    # on indexe de manière ciblée uniquement la/les saison(s) concernée(s).
    if missing_matches:
        needed_saisons = set()
        if saison:
            from pyvolley.cli.helpers import normaliser_saison
            needed_saisons.update({normaliser_saison(s) for s in saison if s})
        else:
            needed_saisons.update({
                getattr(m, "saison_code", None)
                for m in missing_matches
                if getattr(m, "saison_code", None)
            })

        for s_code in needed_saisons:
            if s_code:
                seasonal_idx = build_pdf_index(pdf_base, saison_filter=s_code)
                if seasonal_idx:
                    if pdf_index is None:
                        pdf_index = {}
                    pdf_index.update(seasonal_idx)

        for m in missing_matches:
            pdf_path = find_pdf_for_match(m, pdf_base, pdf_index)
            if pdf_path:
                match_pdf_pairs.append((m.id, pdf_path))

    missing_pdf_count = len(matches_db) - len(match_pdf_pairs)

    if missing_pdf_count:
        console.print(
            f"[dim]⏭ {missing_pdf_count} match(s) ignoré(s) : PDF introuvable[/dim]"
        )

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
    plausibility_touched = 0
    plausibility_flagged = 0
    results = []
    error_details = []
    enriched_match_ids: list[int] = []

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
        import_log_id = import_log.id

        with sqlite_bulk_mode(session):
            with make_progress(console) as progress:
                task = progress.add_task(
                    "Parsing...", total=len(match_pdf_pairs),
                )

                import os
                from queue import Queue
                from threading import Thread
                from concurrent.futures import ThreadPoolExecutor

                max_workers = min(8, os.cpu_count() or 4)
                parse_queue: Queue = Queue(maxsize=150)
                _sentinel = object()

                def _parse_worker(pair):
                    m_id, p_path = pair
                    try:
                        res = parser.parse(p_path)
                        return m_id, p_path, res, None
                    except Exception as exc:
                        return m_id, p_path, None, exc

                def _producer():
                    try:
                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                            for item in executor.map(_parse_worker, match_pdf_pairs, chunksize=8):
                                parse_queue.put(item)
                    finally:
                        parse_queue.put(_sentinel)

                producer_thread = Thread(target=_producer, daemon=True)
                producer_thread.start()

                batch_size = 200
                is_done = False

                while not is_done:
                    batch_items = []
                    while len(batch_items) < batch_size:
                        item = parse_queue.get()
                        if item is _sentinel:
                            is_done = True
                            break
                        batch_items.append(item)

                    if not batch_items:
                        break

                    chunk_ids = [it[0] for it in batch_items]
                    chunk_matches = session.scalars(
                        select(MatchDB)
                        .options(
                            joinedload(MatchDB.saison),
                            joinedload(MatchDB.competition).joinedload(CompetitionDB.entite),
                            joinedload(MatchDB.poule),
                        )
                        .where(MatchDB.id.in_(chunk_ids))
                    ).unique().all()
                    match_map = {m.id: m for m in chunk_matches}

                    for match_id, pdf_path, result, parse_error in batch_items:
                        match_fresh = match_map.get(match_id)
                        if not match_fresh:
                            skipped_count += 1
                            progress.update(task, advance=1)
                            continue

                        if parse_error:
                            failed += 1
                            match_fresh.parsing_status = "error"
                            match_fresh.remarques = str(parse_error)[:200]
                            error_details.append({
                                'file': str(pdf_path), 'errors': [str(parse_error)],
                            })
                            progress.update(task, advance=1)
                            continue

                        try:
                            if result.success and result.match:
                                was_enriched = service.enrich_from_pdf(
                                    match_fresh,
                                    result.match,
                                    force=force,
                                    defer_rollups=True,
                                    defer_player_stats=defer_player_stats,
                                )
                                if was_enriched:
                                    enriched += 1
                                    enriched_match_ids.append(match_fresh.id)
                                else:
                                    skipped_count += 1

                                results.append({
                                    'file': str(pdf_path),
                                    'parse_time_ms': result.parse_time_ms,
                                    'diagnostics': result.diagnostics,
                                    'plausibility_report': (
                                        result.plausibility_report.to_dict()
                                        if result.plausibility_report else None
                                    ),
                                    'enriched': was_enriched,
                                })

                                if result.diagnostics:
                                    warnings_count += result.warnings_count
                                plausibility_touched += result.plausibility_changes_count
                                plausibility_flagged += result.plausibility_flagged_count

                                if verbose and was_enriched:
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
                                    result.errors[0][:200] if result.errors else "Erreur de parsing"
                                )
                                error_details.append({
                                    'file': str(pdf_path),
                                    'errors': result.errors,
                                    'diagnostics': result.diagnostics,
                                })

                        except Exception as e:
                            failed += 1
                            match_fresh.parsing_status = "error"
                            match_fresh.remarques = str(e)[:200]
                            error_details.append({
                                'file': str(pdf_path), 'errors': [str(e)],
                            })

                        progress.update(task, advance=1)
                        if (enriched + failed + skipped_count) % 25 == 0:
                            progress.update(
                                task,
                                description=f"Parsing... ({enriched} enrichis, {failed} err)",
                            )

                    # Commit par batch et purge de session en préservant les caches d'entités résolues
                    try:
                        session.commit()
                        session.expunge_all()
                        service.clear_caches(clear_all=False)
                    except Exception:
                        session.rollback()
                        service.clear_caches(clear_all=True)

                producer_thread.join()

        # Commit final
        import_log = session.get(ImportLogDB, import_log_id)
        if import_log:
            import_log.finished_at = datetime.now()
            import_log.imported = enriched
            import_log.duplicates = skipped_count
            import_log.errors = failed
            import_log.summary = json.dumps(
                {
                    "warnings": warnings_count,
                    "plausibility_touched": plausibility_touched,
                    "plausibility_flagged": plausibility_flagged,
                    "total_results": len(results),
                },
                ensure_ascii=False,
            )
            import_log.status = (
                "success" if failed == 0
                else "partial" if enriched > 0
                else "failed"
            )
        try:
            session.commit()
            session.expunge_all()
            service.clear_caches(clear_all=False)
        except Exception:
            session.rollback()
            service.clear_caches(clear_all=True)

        parse_work_duration = time.perf_counter() - t_parse_start

        # Calcul en lot des statistiques joueurs si différé
        if defer_player_stats and enriched_match_ids:
            t_stats_start = time.perf_counter()
            with make_progress(console) as stats_progress:
                stats_task = stats_progress.add_task(
                    "[cyan]Calcul des statistiques joueurs...",
                    total=len(enriched_match_ids),
                )
                total_player_rows = service.compute_player_stats_for_matches(
                    enriched_match_ids,
                    chunk_size=50,
                    progress_callback=lambda n: stats_progress.update(stats_task, advance=n),
                )
                try:
                    session.commit()
                    session.expunge_all()
                    service.clear_caches(clear_all=False)
                except Exception:
                    session.rollback()
                    service.clear_caches(clear_all=True)

            stats_duration = time.perf_counter() - t_stats_start
            stats_rate = format_rate(len(enriched_match_ids), stats_duration, "matchs")
            console.print(
                f"[cyan]✓ Statistiques joueurs calculées en {format_duration(stats_duration)} : "
                f"{len(enriched_match_ids)} matchs, {total_player_rows} lignes ({stats_rate})[/cyan]"
            )
            if timer:
                timer.record_sub_step(
                    "parse", "player_stats", "Calcul Stats Joueurs (différé)",
                    stats_duration, items_count=len(enriched_match_ids), items_unit="matchs",
                )

        # Actualisation consolidée des rollups si demandé
        if rollup and enriched_match_ids:
            from pyvolley.database.rollup_service import RollupStatsService
            t_rollups_start = time.perf_counter()
            with console.status(
                f"[bold magenta]Actualisation consolidée des rollups pour {len(enriched_match_ids)} match(s)..."
            ):
                try:
                    rollup_service = RollupStatsService(session)
                    rollup_summary = rollup_service.apply_batch_deltas(enriched_match_ids)
                    session.commit()
                    rollups_duration = time.perf_counter() - t_rollups_start
                    total_rollups_items = (
                        rollup_summary.get("player_seasons_updated", 0)
                        + rollup_summary.get("teams_updated", 0)
                        + rollup_summary.get("clubs_updated", 0)
                        + rollup_summary.get("poules_updated", 0)
                    )
                    console.print(
                        f"[magenta]✓ Rollups actualisés en {format_duration(rollups_duration)} : "
                        f"{rollup_summary.get('player_seasons_updated', 0)} stats saisons joueurs, "
                        f"{rollup_summary.get('teams_updated', 0)} équipes, "
                        f"{rollup_summary.get('poules_updated', 0)} poules, "
                        f"{rollup_summary.get('clubs_updated', 0)} clubs ({format_rate(len(enriched_match_ids), rollups_duration, 'matchs')})[/magenta]"
                    )
                    if timer:
                        timer.record_sub_step(
                            "parse", "rollups", "Actualisation Rollups Consolidés",
                            rollups_duration, items_count=total_rollups_items, items_unit="agrégats",
                        )
                except Exception as exc:
                    console.print(f"[yellow]⚠ Erreur lors de l'actualisation consolidée des rollups : {exc}[/yellow]")

    total_parse_duration = time.perf_counter() - t_parse_start
    if timer:
        timer.record_sub_step(
            "parse", "pdf_parse", "Parsing PDF & Injection Matchs",
            parse_work_duration, items_count=enriched, items_unit="matchs",
        )

    console.print(Panel(
        f"[green]✓ Enrichis :  {enriched}[/green]\n"
        f"[yellow]⏭ Ignorés :   {skipped_count}[/yellow]\n"
        f"[red]✗ Échecs :    {failed}[/red]\n"
        f"[dim]⚠ Warnings :  {warnings_count}[/dim]\n"
        f"[magenta]🧪 Plausibilité (modifs) : {plausibility_touched}[/magenta]\n"
        f"[magenta]🧪 Plausibilité (signalées) : {plausibility_flagged}[/magenta]\n"
        f"[yellow]⏱ Durée parse & compute : {format_duration(total_parse_duration)} "
        f"({format_rate(enriched, total_parse_duration, 'matchs')})[/yellow]",
        title=f"Résumé du parsing (achevé en {format_duration(total_parse_duration)})",
    ))

    if results or error_details:
        display_warning_summary(console, results, error_details, enriched + failed)
        display_plausibility_summary(console, results)


def _import_stream(
    *,
    limit: Optional[int] = None,
    saison: Optional[List[str]] = None,
    entity: Optional[List[str]] = None,
    verbose: bool = False,
    concurrent: int = 10,
    plausibility: bool = True,
    plausibility_policy: str = "auto",
    review_fixes: bool = False,
    parser_name: str = "fast",
    rollup: bool = True,
    defer_player_stats: bool = True,
    timer: Optional[PipelineTimer] = None,
) -> None:
    """Mode streaming : download → parse → DB, sans conserver les PDFs."""
    from concurrent.futures import ThreadPoolExecutor
    import httpx
    from pyvolley.parsers.factory import ParserFactory
    from pyvolley.database.connection import DatabaseSession, init_db, sqlite_bulk_mode
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import MatchDB, ImportLogDB
    from sqlalchemy import or_, select

    init_db()
    today = dt_date.today()
    t_stream_start = time.perf_counter()
    parser = ParserFactory.get(parser_name)
    approval_cb = None
    if review_fixes:
        approval_cb = build_plausibility_reviewer(console)
    _configure_parser_plausibility(
        parser,
        enabled=plausibility,
        policy=plausibility_policy,
        approval=approval_cb,
    )

    with DatabaseSession() as session:
        stmt = (
            select(MatchDB)
            .where(
                MatchDB.parsing_status == "discovered",
                MatchDB.match_joue == True,  # noqa: E712
                MatchDB.source_url.isnot(None),
                or_(
                    MatchDB.date_match.is_(None),
                    MatchDB.date_match <= today,
                ),
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

    max_workers = max(1, min(concurrent, 20))
    console.print(
        f"[blue]⚡ {len(matches)} matchs en streaming "
        f"({parser.name} v{parser.version}, {max_workers} workers)[/blue]"
    )

    downloaded = 0
    enriched = 0
    failed = 0
    enriched_match_ids: list[int] = []

    limits = httpx.Limits(max_connections=max_workers + 5, max_keepalive_connections=max_workers)
    with httpx.Client(timeout=30, follow_redirects=True, limits=limits) as http:
        with DatabaseSession() as session:
            with sqlite_bulk_mode(session):
                service = MatchImportService(session)

                import_log = ImportLogDB(
                    operation="stream-pipeline",
                    source="streaming",
                    total_attempted=len(matches),
                    status="running",
                )
                session.add(import_log)
                session.flush()
                import_log_id = import_log.id

                targets = [(m.id, m.code_match, m.source_url) for m in matches if m.source_url]
                skipped_no_url = len(matches) - len(targets)

                def _fetch_and_parse(item):
                    m_id, code_match, url = item
                    try:
                        resp = http.get(url)
                        resp.raise_for_status()
                        if not resp.content[:5].startswith(b"%PDF"):
                            return m_id, code_match, None, "Réponse non-PDF"
                        parsed = parser.parse(resp.content)
                        return m_id, code_match, parsed, None
                    except Exception as exc:
                        return m_id, code_match, None, str(exc)

                with make_progress(console) as progress:
                    task = progress.add_task("Streaming...", total=len(matches))
                    if skipped_no_url:
                        progress.update(task, advance=skipped_no_url)

                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        for m_id, code_match, result, err_msg in executor.map(_fetch_and_parse, targets):
                            match_fresh = session.get(MatchDB, m_id)
                            if not match_fresh:
                                progress.update(task, advance=1)
                                continue

                            if err_msg:
                                failed += 1
                                match_fresh.parsing_status = "error"
                                match_fresh.remarques = err_msg[:200]
                                progress.update(
                                    task, advance=1,
                                    description=f"[red]✗ {code_match}[/red]",
                                )
                            elif result and result.success and result.match:
                                downloaded += 1
                                was_enriched = service.enrich_from_pdf(
                                    match_fresh,
                                    result.match,
                                    force=True,
                                    defer_rollups=True,
                                    defer_player_stats=defer_player_stats,
                                )
                                if was_enriched:
                                    enriched += 1
                                    enriched_match_ids.append(match_fresh.id)

                                if verbose:
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
                                downloaded += 1
                                failed += 1
                                match_fresh.parsing_status = "error"
                                match_fresh.remarques = (
                                    result.errors[0][:200] if result and result.errors
                                    else "Erreur de parsing"
                                )
                                progress.update(
                                    task, advance=1,
                                    description=f"[red]✗ {code_match}[/red]",
                                )

                            # Commit par batch et purge de session
                            if (enriched + failed) % 50 == 0 and (enriched + failed) > 0:
                                try:
                                    session.commit()
                                    session.expunge_all()
                                    service.clear_caches(clear_all=False)
                                except Exception:
                                    session.rollback()
                                    service.clear_caches(clear_all=True)

                stream_work_duration = time.perf_counter() - t_stream_start

                import_log = session.get(ImportLogDB, import_log_id)
                if import_log:
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
                    session.expunge_all()
                    service.clear_caches(clear_all=False)
                except Exception:
                    session.rollback()
                    service.clear_caches(clear_all=True)

                # Calcul en lot des statistiques joueurs si différé
                if defer_player_stats and enriched_match_ids:
                    t_stats_start = time.perf_counter()
                    with make_progress(console) as stats_progress:
                        stats_task = stats_progress.add_task(
                            "[cyan]Calcul des statistiques joueurs (streaming)...",
                            total=len(enriched_match_ids),
                        )
                        service.compute_player_stats_for_matches(
                            enriched_match_ids,
                            chunk_size=50,
                            progress_callback=lambda n: stats_progress.update(stats_task, advance=n),
                        )
                        try:
                            session.commit()
                            session.expunge_all()
                            service.clear_caches(clear_all=False)
                        except Exception:
                            session.rollback()
                            service.clear_caches(clear_all=True)

                stats_duration = time.perf_counter() - t_stats_start
                console.print(
                    f"[cyan]✓ Statistiques joueurs calculées en {format_duration(stats_duration)} "
                    f"({format_rate(len(enriched_match_ids), stats_duration, 'matchs')})[/cyan]"
                )
                if timer:
                    timer.record_sub_step(
                        "stream", "player_stats", "Calcul Stats Joueurs (différé)",
                        stats_duration, items_count=len(enriched_match_ids), items_unit="matchs",
                    )

            # Actualisation consolidée des rollups si demandé
            if rollup and enriched_match_ids:
                from pyvolley.database.rollup_service import RollupStatsService
                t_rollups_start = time.perf_counter()
                with console.status(
                    f"[bold magenta]Actualisation consolidée des rollups pour {len(enriched_match_ids)} match(s)..."
                ):
                    try:
                        rollup_service = RollupStatsService(session)
                        rollup_summary = rollup_service.apply_batch_deltas(enriched_match_ids)
                        session.commit()
                        rollups_duration = time.perf_counter() - t_rollups_start
                        console.print(
                            f"[magenta]✓ Rollups actualisés en {format_duration(rollups_duration)} "
                            f"({format_rate(len(enriched_match_ids), rollups_duration, 'matchs')})[/magenta]"
                        )
                        if timer:
                            timer.record_sub_step(
                                "stream", "rollups", "Actualisation Rollups Consolidés",
                                rollups_duration, items_count=len(enriched_match_ids), items_unit="matchs",
                            )
                    except Exception as exc:
                        console.print(f"[yellow]⚠ Erreur rollups streaming : {exc}[/yellow]")

    total_stream_duration = time.perf_counter() - t_stream_start
    stream_rate = format_rate(enriched, total_stream_duration, "matchs")
    if timer:
        timer.record_sub_step(
            "stream", "stream_dl_parse", "Streaming Download & Parse",
            stream_work_duration, items_count=enriched, items_unit="matchs",
        )

    console.print(
        f"\n[green]✓ {enriched} enrichis en {format_duration(total_stream_duration)} ({stream_rate})[/green]"
        + (f" | [red]{failed} erreurs[/red]" if failed else "")
    )



def _cleanup_parsed_pdfs(
    *,
    saison: Optional[List[str]] = None,
    verbose: bool = False,
    timer: Optional[PipelineTimer] = None,
) -> None:
    """Supprime les PDFs des matchs parsés avec succès."""
    from pyvolley.database.connection import DatabaseSession
    from pyvolley.database.models import MatchDB
    from sqlalchemy import select

    t_clean_start = time.perf_counter()
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
        code = extract_match_code_from_pdf_path(pdf_file)
        if code in parsed_codes or stem in parsed_codes:
            # Filtrer par saison si demandé
            if saison:
                normalized = saisons_to_db_codes(saison)
                if not any(ns in str(pdf_file) for ns in normalized):
                    continue
            try:
                pdf_file.unlink()
                deleted += 1
            except Exception:
                pass

    clean_duration = time.perf_counter() - t_clean_start
    if deleted:
        console.print(f"[dim]🗑 {deleted} PDFs supprimés en {format_duration(clean_duration)} (déjà parsés)[/dim]")
    if timer:
        timer.record_sub_step(
            "parse", "cleanup", "Nettoyage PDFs locaux",
            clean_duration, items_count=deleted, items_unit="PDFs",
        )


