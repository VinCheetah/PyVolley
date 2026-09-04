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
- ``compute-player-stats`` : pré-calculer les statistiques détaillées joueurs par match
- ``roles``                : gestion, diffusion réseau et audit des rôles joueurs
- ``plausibility-audit`` : relancer les contrôles de vraisemblance a posteriori
- ``init``          : initialiser la base de données
- ``db``            : gestion de la base (migrations, exploration)
- ``report``        : rapports détaillés sur les entités en base
"""

import asyncio
import json
import time
from datetime import datetime, date as dt_date
from pathlib import Path
from typing import Optional, List

import sys
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
)
from pyvolley.cli.list_commands import list_app
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

app = typer.Typer(
    name="pyvolley",
    help="PyVolley — Outils pour les données volleyball FFVB",
    add_completion=False,
)
console = Console()


def _configure_parser_plausibility(
    parser,
    *,
    enabled: bool,
    policy: str,
    approval,
) -> None:
    """Configure la plausibilité d'un parser si l'API est disponible."""
    configure = getattr(parser, "configure_plausibility", None)
    if callable(configure):
        configure(
            enabled=enabled,
            policy=policy,
            approval=approval,
        )


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


@app.command("import")
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
        all_entities=all_entities,
    )
    try:
        saisons = resolve_saisons(scraper, saison)
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

    # ── Étape 1 : Scrape ───────────────────────────────────────────
    if "scrape" in steps:
        _import_scrape(
            scraper,
            entities_to_process,
            saisons,
            verbose=verbose,
            force_club_enrichment=force_club_enrichment,
        )

    # ── Étape 2 : Download ─────────────────────────────────────────
    if "download" in steps:
        if not keep_pdfs and "parse" in steps:
            # Mode streaming : download + parse en une passe
            console.print(
                "\n[bold blue]═══ Download + Parse (streaming) ═══[/bold blue]"
            )
            _import_stream(
                limit=limit, saison=saisons, entity=entity, verbose=verbose,
                plausibility=plausibility,
                plausibility_policy=plausibility_policy,
                review_fixes=review_fixes,
                parser_name=parser_name,
                rollup=rollup,
            )
            steps = [s for s in steps if s != "parse"]
        else:
            console.print("\n[bold blue]═══ Download ═══[/bold blue]")
            _import_download(
                limit=limit, saison=saisons, concurrent=concurrent,
                entity=entity,
                verbose=verbose,
                verify_existing=verify_existing,
            )

    # ── Étape 3 : Parse ───────────────────────────────────────────
    if "parse" in steps:
        console.print("\n[bold blue]═══ Parse ═══[/bold blue]")
        _import_parse(
            limit=limit, saison=saisons, entity=entity,
            force=force, verbose=verbose,
            plausibility=plausibility,
            plausibility_policy=plausibility_policy,
            review_fixes=review_fixes,
            parser_name=parser_name,
            rollup=rollup,
        )

        # Nettoyage post-parse si --no-keep-pdfs
        if not keep_pdfs:
            _cleanup_parsed_pdfs(saison=saisons, verbose=verbose)

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
    force_club_enrichment: bool = False,
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

                # Enrichissement clubs (idempotent par défaut)
                try:
                    poule_codes = sorted({
                        (m.poule_code_ffvb or m.poule_code)
                        for m in export_data
                        if (m.poule_code_ffvb or m.poule_code)
                    })
                    with console.status(
                        f"[bold magenta]Enrichissement clubs ({len(poule_codes)} poules)..."
                    ):
                        clubs_info = fetch_adressier(
                            scraper.client, scraper.base_url,
                            target_entity, target_saison, poule_codes,
                        )
                    if clubs_info:
                        club_stats = service.enrich_clubs(
                            clubs_info,
                            target_entity,
                            target_saison,
                            scraper.base_url,
                            force_reenrich=force_club_enrichment,
                        )
                        enriched = club_stats.get("enriched", 0)
                        created = club_stats.get("created", 0)
                        skipped = club_stats.get("skipped", 0)
                        total_clubs += enriched + created
                        if enriched or created or skipped:
                            console.print(
                                f"  Clubs : [magenta]{created} créés, "
                                f"{enriched} enrichis, "
                                f"{skipped} ignorés[/magenta]"
                            )
                    else:
                        console.print(
                            "  [yellow]Aucun club récupéré via l'adressier "
                            f"(entité={target_entity}, saison={target_saison})[/yellow]"
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
    entity: Optional[List[str]] = None,
    concurrent: int = 5,
    verbose: bool = False,
    verify_existing: bool = False,
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

            saison_db = (
                session.get(SaisonDB, match_db.saison_id)
                if match_db.saison_id else None
            )
            saison_code = saison_db.code if saison_db else "unknown"

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
            for match_id, pdf_path in already_present:
                m = session.get(MatchDB, match_id)
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
    if verbose and failed:
        console.print("[bold red]Détails des erreurs de téléchargement :[/bold red]")
        for match_id, dest, success, error_msg in dl_results:
            if not success:
                console.print(f"[red]- {dest.stem}: {error_msg}[/red]")


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
) -> None:
    """Étape 3 : parsing des PDFs et enrichissement de la base."""
    from pyvolley.parsers.factory import ParserFactory
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import MatchDB, ImportLogDB, CompetitionDB
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    init_db()
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
            select(MatchDB)
            .options(
                joinedload(MatchDB.saison),
                joinedload(MatchDB.competition).joinedload(CompetitionDB.entite),
                joinedload(MatchDB.poule),
            )
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

    # Localiser les PDFs (résolution directe O(1) d'abord, sans glob disque global)
    pdf_base = Path("data/pdfs")
    pdf_index = None

    match_pdf_pairs = []
    missing_matches = []
    for m in matches_db:
        pdf_path = find_pdf_for_match(m, pdf_base, pdf_index)
        if pdf_path:
            match_pdf_pairs.append((m, pdf_path))
        else:
            missing_matches.append(m)

    # Si certains fichiers ne sont pas trouvés aux chemins standard,
    # on indexe de manière ciblée uniquement la saison concernée.
    if missing_matches:
        saison_filter = None
        if saison and len(saison) == 1:
            from pyvolley.cli.helpers import normaliser_saison
            saison_filter = normaliser_saison(saison[0])
        pdf_index = build_pdf_index(pdf_base, saison_filter=saison_filter)
        for m in missing_matches:
            pdf_path = find_pdf_for_match(m, pdf_base, pdf_index)
            if pdf_path:
                match_pdf_pairs.append((m, pdf_path))

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

        with make_progress(console) as progress:
            task = progress.add_task(
                "Parsing...", total=len(match_pdf_pairs),
            )

            def _parse_worker(pair):
                m_obj, p_path = pair
                try:
                    res = parser.parse(p_path)
                    return m_obj.id, p_path, res, None
                except Exception as exc:
                    return m_obj.id, p_path, None, exc

            import os
            from concurrent.futures import ThreadPoolExecutor

            max_workers = min(8, os.cpu_count() or 4)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for match_id, pdf_path, result, parse_error in executor.map(
                    _parse_worker, match_pdf_pairs, chunksize=8
                ):
                    match_fresh = session.scalar(
                        select(MatchDB)
                        .options(
                            joinedload(MatchDB.saison),
                            joinedload(MatchDB.competition).joinedload(CompetitionDB.entite),
                            joinedload(MatchDB.poule),
                        )
                        .where(MatchDB.id == match_id)
                    )
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
                                match_fresh, result.match, force=force, defer_rollups=True,
                            )
                            if was_enriched:
                                enriched += 1
                                enriched_match_ids.append(match_fresh.id)
                            else:
                                skipped_count += 1

                            results.append({
                                'file': str(pdf_path),
                                'match': result.match,
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
        except Exception:
            session.rollback()

        # Actualisation consolidée des rollups si demandé
        if rollup and enriched_match_ids:
            from pyvolley.database.rollup_service import RollupStatsService
            with console.status(
                f"[bold magenta]Actualisation consolidée des rollups pour {len(enriched_match_ids)} match(s)..."
            ):
                try:
                    rollup_service = RollupStatsService(session)
                    rollup_summary = rollup_service.apply_batch_deltas(enriched_match_ids)
                    session.commit()
                    console.print(
                        f"[magenta]✓ Rollups : {rollup_summary.get('player_seasons_updated', 0)} stats saisons joueurs, "
                        f"{rollup_summary.get('teams_updated', 0)} équipes, "
                        f"{rollup_summary.get('poules_updated', 0)} poules actualisées[/magenta]"
                    )
                except Exception as exc:
                    console.print(f"[yellow]⚠ Erreur lors de l'actualisation consolidée des rollups : {exc}[/yellow]")

    console.print(Panel(
        f"[green]✓ Enrichis :  {enriched}[/green]\n"
        f"[yellow]⏭ Ignorés :   {skipped_count}[/yellow]\n"
        f"[red]✗ Échecs :    {failed}[/red]\n"
        f"[dim]⚠ Warnings :  {warnings_count}[/dim]\n"
        f"[magenta]🧪 Plausibilité (modifs) : {plausibility_touched}[/magenta]\n"
        f"[magenta]🧪 Plausibilité (signalées) : {plausibility_flagged}[/magenta]",
        title="Résumé du parsing",
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
    plausibility: bool = True,
    plausibility_policy: str = "auto",
    review_fixes: bool = False,
    parser_name: str = "fast",
    rollup: bool = True,
) -> None:
    """Mode streaming : download → parse → DB, sans conserver les PDFs."""
    import httpx
    from pyvolley.parsers.factory import ParserFactory
    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.import_service import MatchImportService
    from pyvolley.database.models import MatchDB, ImportLogDB
    from sqlalchemy import or_, select

    init_db()
    today = dt_date.today()
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

    console.print(
        f"[blue]⚡ {len(matches)} matchs en streaming "
        f"({parser.name} v{parser.version})[/blue]"
    )

    downloaded = 0
    enriched = 0
    failed = 0
    enriched_match_ids: list[int] = []

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

                        result = parser.parse(response.content)
                        downloaded += 1

                        if result.success and result.match:
                            was_enriched = service.enrich_from_pdf(
                                match_fresh, result.match, force=True, defer_rollups=True,
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

            # Actualisation consolidée des rollups si demandé
            if rollup and enriched_match_ids:
                from pyvolley.database.rollup_service import RollupStatsService
                with console.status(
                    f"[bold magenta]Actualisation consolidée des rollups pour {len(enriched_match_ids)} match(s)..."
                ):
                    try:
                        rollup_service = RollupStatsService(session)
                        rollup_service.apply_batch_deltas(enriched_match_ids)
                        session.commit()
                    except Exception as exc:
                        console.print(f"[yellow]⚠ Erreur rollups streaming : {exc}[/yellow]")

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
        # Filtres optionnels
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


# ════════════════════════════════════════════════════════════════════
# list — consulter les données FFVB
# ════════════════════════════════════════════════════════════════════


app.add_typer(list_app, name="list")


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
    parser_name: str = typer.Option(
        "fast", "--parser", "-p",
        help="Parser à utiliser : 'fast' (FastMatchSheetParser, ~20ms) ou 'legacy' (MatchSheetParser, ~1200ms).",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Afficher les détails.",
    ),
    plausibility: bool = typer.Option(
        True, "--plausibility/--no-plausibility",
        help="Activer les contrôles de vraisemblance.",
    ),
    plausibility_policy: str = typer.Option(
        "auto", "--plausibility-policy",
        help="Politique: auto, report-only, strict.",
    ),
    review_fixes: bool = typer.Option(
        False, "--review-fixes",
        help="Valider manuellement les corrections proposées.",
    ),
):
    """
    📄 Analyser des feuilles de match PDF.

    Parse un ou plusieurs fichiers PDF et affiche les résultats.
    Cette commande est indépendante de la base de données — pour importer
    des données en base, utilisez ``pyvolley import``.

    Exemples :

        pyvolley parse match.pdf
        pyvolley parse data/pdfs/ -n 10 --parser legacy
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
                        'plausibility_report': (
                            result.plausibility_report.to_dict()
                            if result.plausibility_report else None
                        ),
                    })

                    if verbose:
                        m = result.match
                        progress.console.print(
                            f"  [green]OK[/green] {pdf_file.name}: "
                            f"{m.equipe_a.nom if m.equipe_a else '?'} vs "
                            f"{m.equipe_b.nom if m.equipe_b else '?'}"
                        )
                        if result.diagnostics:
                            for d in result.diagnostics:
                                progress.console.print(
                                    f"      [yellow][!] {d}[/yellow]"
                                )

                    progress.update(
                        task, advance=1,
                        description=f"[green]OK {pdf_file.name[:30]}[/green]",
                    )
                else:
                    failed += 1
                    msg = result.errors[0][:60] if result.errors else "Erreur"
                    if verbose:
                        progress.console.print(
                            f"  [red]ERR[/red] {pdf_file.name}: {msg}"
                        )
                    progress.update(
                        task, advance=1,
                        description=f"[red]ERR {pdf_file.name[:30]}[/red]",
                    )

            except Exception as e:
                failed += 1
                progress.update(
                    task, advance=1,
                    description=f"[red]ERR {pdf_file.name[:30]}[/red]",
                )

    console.print(Panel(
        f"[green]Succes : {successful}[/green]\n"
        f"[red]Echecs : {failed}[/red]",
        title="Resultat",
    ))

    if results:
        display_plausibility_summary(console, results)

    # Export JSON
    if output and results:
        export_data = [
            {
                'file': r['file'],
                'parse_time_ms': r['parse_time_ms'],
                'plausibility_report': r.get('plausibility_report'),
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
# compare — comparaison de performance et de parité des parsers
# ════════════════════════════════════════════════════════════════════


@app.command("compare")
def compare_parsers(
    input_path: Optional[Path] = typer.Argument(
        None, help="Chemin vers un PDF ou un dossier de PDFs (par défaut: data/data_sample ou data/pdfs).",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n", help="Nombre max de fichiers PDF à comparer.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Afficher les détails des différences entre parsers.",
    ),
    parsers: Optional[List[str]] = typer.Option(
        None, "--parsers", "-p", help="Parsers à comparer (ex: -p legacy -p zone ou -p legacy,zone).",
    ),
):
    """
    Comparer la vitesse d'exécution et la parité des données entre parsers.

    Parse une série de fichiers PDF avec les parsers sélectionnés et affiche un bilan comparatif de vitesse et de parité.

    Exemples :

        pyvolley compare
        pyvolley compare -p legacy -p zone -v
        pyvolley compare data/data_sample -n 5 -p legacy,zone
        pyvolley compare data/pdfs/ -v
    """
    from pyvolley.parsers.factory import ParserFactory
    from pyvolley.parsers.utils import normalize_club_name

    pdf_files: list[Path] = []
    if input_path:
        if not input_path.exists():
            console.print(f"[red]Erreur : {input_path} n'existe pas[/red]")
            raise typer.Exit(1)
        if input_path.is_dir():
            pdf_files = sorted(input_path.glob("**/*.pdf"))
        else:
            pdf_files = [input_path]
    else:
        for cand_dir in [Path("data/data_sample"), Path("data/pdfs")]:
            if cand_dir.exists() and cand_dir.is_dir():
                found = sorted(cand_dir.glob("**/*.pdf"))
                if found:
                    pdf_files = found
                    break

    if not pdf_files:
        console.print("[yellow]Aucun fichier PDF trouvé pour la comparaison.[/yellow]")
        raise typer.Exit(0)

    if limit:
        pdf_files = pdf_files[:limit]

    raw_parser_names: list[str] = []
    if parsers:
        for p in parsers:
            for item in p.split(","):
                item_clean = item.strip()
                if item_clean:
                    raw_parser_names.append(item_clean)

    if not raw_parser_names:
        raw_parser_names = ["legacy", "fast"]

    parser_instances = []

    def _get_short_label(canonical_key: str, instance) -> str:
        k = canonical_key.lower()
        if "legacy" in k or k == "matchsheetparser":
            return "Legacy"
        if "fast" in k or k == "fastmatchsheetparser":
            return "Fast"
        return instance.name or canonical_key

    for p_name in raw_parser_names:
        try:
            canonical = ParserFactory.resolve_name(p_name)
            instance = ParserFactory.get(canonical)
            label = _get_short_label(canonical, instance)
            parser_instances.append((label, instance))
        except KeyError:
            available = ", ".join(["legacy", "fast"] + ParserFactory.list_parsers())
            console.print(f"[red]Erreur : Parser '{p_name}' non reconnu. Disponibles : {available}[/red]")
            raise typer.Exit(1)

    if len(parser_instances) < 2:
        console.print("[yellow]Attention : au moins 2 parsers sont nécessaires pour une comparaison utile.[/yellow]")

    parser_lines = [f"• Parser {i+1} : [cyan]{instance.name}[/cyan] ({label})" for i, (label, instance) in enumerate(parser_instances)]
    console.print(Panel(
        f"[bold blue]Comparaison des Parsers PyVolley[/bold blue]\n\n" +
        "\n".join(parser_lines) +
        f"\n• Fichiers : [cyan]{len(pdf_files)} PDF(s)[/cyan]",
        title="Benchmark & Parité",
    ))

    table = Table(title="Résultats de la Comparaison")
    table.add_column("Fichier PDF", style="dim")

    colors = ["magenta", "cyan", "blue", "green", "yellow", "purple"]
    for i, (label, _) in enumerate(parser_instances):
        color = colors[i % len(colors)]
        table.add_column(f"{label} (ms)", justify="right", style=color)

    if len(parser_instances) >= 2:
        table.add_column("Speedup", justify="right", style="bold green")
    table.add_column("Parité Données", justify="center")

    total_times = {label: 0.0 for label, _ in parser_instances}
    total_matches = 0
    parity_count = 0
    discrepancies_list = []

    def _compare_two_results(label1: str, res1, label2: str, res2) -> tuple[list[str], list[str]]:
        matches = []
        diffs = []

        if res1.success != res2.success:
            diffs.append(f"Statut Succès: {label1}={res1.success} vs {label2}={res2.success}")
        else:
            matches.append(f"Statut Succès: {'Succès' if res1.success else 'Échec'}")

        if res1.match and res2.match:
            lm, fm = res1.match, res2.match

            l_eq_a = normalize_club_name(lm.equipe_a.nom if lm.equipe_a else "")
            f_eq_a = normalize_club_name(fm.equipe_a.nom if fm.equipe_a else "")
            if l_eq_a != f_eq_a:
                diffs.append(f"Equipe A Nom: '{lm.equipe_a.nom if lm.equipe_a else '?'}' vs '{fm.equipe_a.nom if fm.equipe_a else '?'}'")
            else:
                matches.append(f"Equipe A Nom: '{lm.equipe_a.nom if lm.equipe_a else '?'}'")

            l_eq_b = normalize_club_name(lm.equipe_b.nom if lm.equipe_b else "")
            f_eq_b = normalize_club_name(fm.equipe_b.nom if fm.equipe_b else "")
            if l_eq_b != f_eq_b:
                diffs.append(f"Equipe B Nom: '{lm.equipe_b.nom if lm.equipe_b else '?'}' vs '{fm.equipe_b.nom if fm.equipe_b else '?'}'")
            else:
                matches.append(f"Equipe B Nom: '{lm.equipe_b.nom if lm.equipe_b else '?'}'")

            if (lm.sets_a, lm.sets_b) != (fm.sets_a, fm.sets_b):
                diffs.append(f"Score Sets: {label1}={lm.sets_a}-{lm.sets_b} vs {label2}={fm.sets_a}-{fm.sets_b}")
            else:
                matches.append(f"Score Sets: {lm.sets_a}-{lm.sets_b}")

            if lm.match_joue != fm.match_joue:
                diffs.append(f"Statut Match Joué: {label1}={lm.match_joue} vs {label2}={fm.match_joue}")
            else:
                matches.append(f"Statut Match Joué: {lm.match_joue}")

            # Match Header Fields
            for field_name in ("code_match", "date", "heure", "lieu", "salle", "competition", "journee", "organisateur", "niveau", "categorie", "genre", "score_final", "duree_totale", "vainqueur_nom"):
                val_l = getattr(lm, field_name, None)
                val_f = getattr(fm, field_name, None)

                if field_name == "heure":
                    s_l = str(val_l).replace("h", ":")[:5] if val_l else ""
                    s_f = str(val_f).replace("h", ":")[:5] if val_f else ""
                    if s_l == s_f:
                        matches.append(f"Header heure: {s_l}")
                        continue

                if field_name == "lieu" and val_l and any(w in str(val_l).upper() for w in ("SAMEDI", "DIMANCHE", "LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI")) and not val_f:
                    matches.append(f"Header lieu: {val_l}")
                    continue

                if val_l != val_f and not (val_l is None and val_f == "") and not (val_f is None and val_l == ""):
                    diffs.append(f"Header {field_name}: {label1}={val_l} vs {label2}={val_f}")
                elif val_l or val_f:
                    matches.append(f"Header {field_name}: {val_l if val_l is not None else val_f}")

            # Entraîneurs A & B
            ent_a1 = getattr(lm.equipe_a, "entraineur", None) if lm.equipe_a else None
            ent_a2 = getattr(fm.equipe_a, "entraineur", None) if fm.equipe_a else None
            if ent_a1 != ent_a2 and (ent_a1 or ent_a2):
                diffs.append(f"Entraîneur Equipe A: {label1}='{ent_a1}' vs {label2}='{ent_a2}'")
            elif ent_a1 or ent_a2:
                matches.append(f"Entraîneur Equipe A: {ent_a1 or ent_a2}")

            ent_b1 = getattr(lm.equipe_b, "entraineur", None) if lm.equipe_b else None
            ent_b2 = getattr(fm.equipe_b, "entraineur", None) if fm.equipe_b else None
            if ent_b1 != ent_b2 and (ent_b1 or ent_b2):
                diffs.append(f"Entraîneur Equipe B: {label1}='{ent_b1}' vs {label2}='{ent_b2}'")
            elif ent_b1 or ent_b2:
                matches.append(f"Entraîneur Equipe B: {ent_b1 or ent_b2}")

            # Capitaines
            cap_a1 = lm.equipe_a.capitaine if lm.equipe_a else None
            cap_a2 = fm.equipe_a.capitaine if fm.equipe_a else None
            if cap_a1 != cap_a2 and (cap_a1 or cap_a2):
                diffs.append(f"Capitaine Equipe A (maillot): {label1}='{cap_a1}' vs {label2}='{cap_a2}'")
            elif cap_a1 or cap_a2:
                matches.append(f"Capitaine Equipe A: N° {cap_a1}")

            cap_b1 = lm.equipe_b.capitaine if lm.equipe_b else None
            cap_b2 = fm.equipe_b.capitaine if fm.equipe_b else None
            if cap_b1 != cap_b2 and (cap_b1 or cap_b2):
                diffs.append(f"Capitaine Equipe B (maillot): {label1}='{cap_b1}' vs {label2}='{cap_b2}'")
            elif cap_b1 or cap_b2:
                matches.append(f"Capitaine Equipe B: N° {cap_b1}")

            # Joueurs A & B (numéros, licences & détails)
            l_j_a = [(j.numero, j.nom, j.prenom, j.licence, getattr(j, "est_capitaine", False)) for j in (lm.equipe_a.joueurs if lm.equipe_a else [])]
            f_j_a = [(j.numero, j.nom, j.prenom, j.licence, getattr(j, "est_capitaine", False)) for j in (fm.equipe_a.joueurs if fm.equipe_a else [])]
            if l_j_a != f_j_a:
                diffs.append(f"Joueurs Equipe A (N°/Nom/Licence): {label1}={l_j_a} vs {label2}={f_j_a}")
            else:
                matches.append(f"Joueurs Equipe A: {len(l_j_a)} joueur(s) identiques")

            l_j_b = [(j.numero, j.nom, j.prenom, j.licence, getattr(j, "est_capitaine", False)) for j in (lm.equipe_b.joueurs if lm.equipe_b else [])]
            f_j_b = [(j.numero, j.nom, j.prenom, j.licence, getattr(j, "est_capitaine", False)) for j in (fm.equipe_b.joueurs if fm.equipe_b else [])]
            if l_j_b != f_j_b:
                diffs.append(f"Joueurs Equipe B (N°/Nom/Licence): {label1}={l_j_b} vs {label2}={f_j_b}")
            else:
                matches.append(f"Joueurs Equipe B: {len(l_j_b)} joueur(s) identiques")

            # Libéros A & B
            l_lib_a = [(j.numero, j.nom, j.prenom, j.licence) for j in (lm.equipe_a.liberos if lm.equipe_a else [])]
            f_lib_a = [(j.numero, j.nom, j.prenom, j.licence) for j in (fm.equipe_a.liberos if fm.equipe_a else [])]
            if l_lib_a != f_lib_a:
                diffs.append(f"Libéros Equipe A (N°/Nom/Licence): {label1}={l_lib_a} vs {label2}={f_lib_a}")
            else:
                matches.append(f"Libéros Equipe A: {len(l_lib_a)} libéro(s) identiques")

            l_lib_b = [(j.numero, j.nom, j.prenom, j.licence) for j in (lm.equipe_b.liberos if lm.equipe_b else [])]
            f_lib_b = [(j.numero, j.nom, j.prenom, j.licence) for j in (fm.equipe_b.liberos if fm.equipe_b else [])]
            if l_lib_b != f_lib_b:
                diffs.append(f"Libéros Equipe B (N°/Nom/Licence): {label1}={l_lib_b} vs {label2}={f_lib_b}")
            else:
                matches.append(f"Libéros Equipe B: {len(l_lib_b)} libéro(s) identiques")

            # Officiels / Staff A & B
            l_off_a = [(o.role, o.nom, o.prenom, o.licence) for o in (lm.equipe_a.officiels if lm.equipe_a else [])]
            f_off_a = [(o.role, o.nom, o.prenom, o.licence) for o in (fm.equipe_a.officiels if fm.equipe_a else [])]
            if l_off_a != f_off_a:
                diffs.append(f"Officiels Equipe A: {label1}={l_off_a} vs {label2}={f_off_a}")
            else:
                matches.append(f"Officiels Equipe A: {len(l_off_a)} officiel(s) identiques")

            l_off_b = [(o.role, o.nom, o.prenom, o.licence) for o in (lm.equipe_b.officiels if lm.equipe_b else [])]
            f_off_b = [(o.role, o.nom, o.prenom, o.licence) for o in (fm.equipe_b.officiels if fm.equipe_b else [])]
            if l_off_b != f_off_b:
                diffs.append(f"Officiels Equipe B: {label1}={l_off_b} vs {label2}={f_off_b}")
            else:
                matches.append(f"Officiels Equipe B: {len(l_off_b)} officiel(s) identiques")

            # Corps Arbitral
            l_arb = [(a.role.value if hasattr(a.role, "value") else str(a.role), a.nom, getattr(a, "prenom", ""), getattr(a, "ligue", ""), a.licence) for a in (lm.arbitres or [])]
            f_arb = [(a.role.value if hasattr(a.role, "value") else str(a.role), a.nom, getattr(a, "prenom", ""), getattr(a, "ligue", ""), a.licence) for a in (fm.arbitres or [])]
            if l_arb != f_arb:
                diffs.append(f"Arbitres (Rôle/Nom/Prénom/Ligue/Licence): {label1}={l_arb} vs {label2}={f_arb}")
            else:
                matches.append(f"Corps Arbitral: {len(l_arb)} arbitre(s) identiques")

            # Sets Details (Sets 1 à 5)
            l_sets = {s.numero: s for s in (lm.sets or [])}
            f_sets = {s.numero: s for s in (fm.sets or [])}
            if set(l_sets.keys()) != set(f_sets.keys()):
                diffs.append(f"Numéros des Sets présents: {label1}={sorted(l_sets.keys())} vs {label2}={sorted(f_sets.keys())}")

            common_sets = set(l_sets.keys()).intersection(set(f_sets.keys()))
            for s_num in sorted(common_sets):
                ls, fs = l_sets[s_num], f_sets[s_num]
                if (ls.score_a, ls.score_b) != (fs.score_a, fs.score_b):
                    diffs.append(f"Set {s_num} Score: {label1}={ls.score_a}-{ls.score_b} vs {label2}={fs.score_a}-{fs.score_b}")
                else:
                    matches.append(f"Set {s_num} Score: {ls.score_a}-{ls.score_b}")

                # Heures Début / Fin
                deb_l = str(ls.debut) if ls.debut else None
                deb_f = str(fs.debut) if fs.debut else None
                if deb_l != deb_f and (deb_l is not None and deb_f is not None):
                    diffs.append(f"Set {s_num} Début: {label1}={deb_l} vs {label2}={deb_f}")
                elif deb_l or deb_f:
                    matches.append(f"Set {s_num} Début: {deb_l or deb_f}")

                fin_l = str(ls.fin) if ls.fin else None
                fin_f = str(fs.fin) if fs.fin else None
                if fin_l != fin_f and (fin_l is not None and fin_f is not None):
                    diffs.append(f"Set {s_num} Fin: {label1}={fin_l} vs {label2}={fin_f}")
                elif fin_l or fin_f:
                    matches.append(f"Set {s_num} Fin: {fin_l or fin_f}")

                if ls.duree_minutes != fs.duree_minutes and (ls.duree_minutes is not None and fs.duree_minutes is not None):
                    diffs.append(f"Set {s_num} Durée: {label1}={ls.duree_minutes}m vs {label2}={fs.duree_minutes}m")
                elif ls.duree_minutes is not None:
                    matches.append(f"Set {s_num} Durée: {ls.duree_minutes}m")

                if ls.service_initial != fs.service_initial and (ls.service_initial is not None and fs.service_initial is not None):
                    diffs.append(f"Set {s_num} Service Initial: {label1}={ls.service_initial} vs {label2}={fs.service_initial}")
                elif ls.service_initial is not None:
                    matches.append(f"Set {s_num} Service Initial: Équipe {ls.service_initial}")

                # Formations A & B
                if (ls.equipe_a and fs.equipe_a) and ls.equipe_a.formation != fs.equipe_a.formation:
                    if ls.equipe_a.formation is not None and fs.equipe_a.formation is not None:
                        diffs.append(f"Set {s_num} Formation A: {label1}={ls.equipe_a.formation} vs {label2}={fs.equipe_a.formation}")
                elif ls.equipe_a and ls.equipe_a.formation:
                    matches.append(f"Set {s_num} Formation A: {ls.equipe_a.formation}")

                if (ls.equipe_b and fs.equipe_b) and ls.equipe_b.formation != fs.equipe_b.formation:
                    if ls.equipe_b.formation is not None and fs.equipe_b.formation is not None:
                        diffs.append(f"Set {s_num} Formation B: {label1}={ls.equipe_b.formation} vs {label2}={fs.equipe_b.formation}")
                elif ls.equipe_b and ls.equipe_b.formation:
                    matches.append(f"Set {s_num} Formation B: {ls.equipe_b.formation}")

                # Changements / Substitutions A & B
                ch_a1 = [(c.joueur_entrant, c.joueur_sortant, c.position, c.score_a, c.score_b) for c in (ls.equipe_a.changements if ls.equipe_a else [])]
                ch_a2 = [(c.joueur_entrant, c.joueur_sortant, c.position, c.score_a, c.score_b) for c in (fs.equipe_a.changements if fs.equipe_a else [])]
                if ch_a1 != ch_a2 and (ch_a1 or ch_a2):
                    diffs.append(f"Set {s_num} Changements A: {label1}={ch_a1} vs {label2}={ch_a2}")
                elif ch_a1:
                    matches.append(f"Set {s_num} Changements A: {len(ch_a1)} changement(s)")

                ch_b1 = [(c.joueur_entrant, c.joueur_sortant, c.position, c.score_a, c.score_b) for c in (ls.equipe_b.changements if ls.equipe_b else [])]
                ch_b2 = [(c.joueur_entrant, c.joueur_sortant, c.position, c.score_a, c.score_b) for c in (fs.equipe_b.changements if fs.equipe_b else [])]
                if ch_b1 != ch_b2 and (ch_b1 or ch_b2):
                    diffs.append(f"Set {s_num} Changements B: {label1}={ch_b1} vs {label2}={ch_b2}")
                elif ch_b1:
                    matches.append(f"Set {s_num} Changements B: {len(ch_b1)} changement(s)")

                # Timeouts A & B
                t_a1 = [(t.score_a, t.score_b) for t in (ls.equipe_a.timeouts if ls.equipe_a else [])]
                t_a2 = [(t.score_a, t.score_b) for t in (fs.equipe_a.timeouts if fs.equipe_a else [])]
                if t_a1 != t_a2 and (t_a1 or t_a2):
                    diffs.append(f"Set {s_num} Timeouts A: {label1}={t_a1} vs {label2}={t_a2}")
                elif t_a1:
                    matches.append(f"Set {s_num} Timeouts A: {t_a1}")

                t_b1 = [(t.score_a, t.score_b) for t in (ls.equipe_b.timeouts if ls.equipe_b else [])]
                t_b2 = [(t.score_a, t.score_b) for t in (fs.equipe_b.timeouts if fs.equipe_b else [])]
                if t_b1 != t_b2 and (t_b1 or t_b2):
                    diffs.append(f"Set {s_num} Timeouts B: {label1}={t_b1} vs {label2}={t_b2}")
                elif t_b1:
                    matches.append(f"Set {s_num} Timeouts B: {t_b1}")

                # Services A & B
                if (ls.equipe_a and fs.equipe_a) and ls.equipe_a.services != fs.equipe_a.services:
                    diffs.append(f"Set {s_num} Services A: {label1}={dict(ls.equipe_a.services)} vs {label2}={dict(fs.equipe_a.services)}")
                elif ls.equipe_a and ls.equipe_a.services:
                    matches.append(f"Set {s_num} Services A: {dict(ls.equipe_a.services)}")

                if (ls.equipe_b and fs.equipe_b) and ls.equipe_b.services != fs.equipe_b.services:
                    diffs.append(f"Set {s_num} Services B: {label1}={dict(ls.equipe_b.services)} vs {label2}={dict(fs.equipe_b.services)}")
                elif ls.equipe_b and ls.equipe_b.services:
                    matches.append(f"Set {s_num} Services B: {dict(ls.equipe_b.services)}")

            # Remarques
            if (lm.remarques or "").strip() != (fm.remarques or "").strip() and (lm.remarques or fm.remarques):
                diffs.append(f"Remarques: {label1}='{(lm.remarques or '').strip()}' vs {label2}='{(fm.remarques or '').strip()}'")
            elif lm.remarques:
                matches.append(f"Remarques: {lm.remarques.strip()}")

        elif res1.success or res2.success:
            diffs.append(f"Parsing Match Objet: {label1}={'présent' if res1.match else 'absent'} vs {label2}={'présent' if res2.match else 'absent'}")
        return matches, diffs

    all_comparison_details = []

    with make_progress(console) as progress:
        task_id = progress.add_task("Comparaison...", total=len(pdf_files))

        for pdf_file in pdf_files:
            file_results = []
            for label, instance in parser_instances:
                t0 = time.perf_counter()
                res = instance.parse(pdf_file)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                total_times[label] += elapsed_ms
                file_results.append((label, res, elapsed_ms))

            total_matches += 1

            matches_all, diffs_all = [], []
            ref_label, ref_res, ref_ms = file_results[0]
            for other_label, other_res, other_ms in file_results[1:]:
                m_list, d_list = _compare_two_results(ref_label, ref_res, other_label, other_res)
                matches_all.extend(m_list)
                diffs_all.extend(d_list)

            all_comparison_details.append((pdf_file.name, matches_all, diffs_all))

            if not diffs_all:
                parity_count += 1
                parity_str = "[bold green]100% Identique[/bold green]"
            else:
                parity_str = f"[bold yellow]{len(diffs_all)} ecart(s)[/bold yellow]"

            row_vals = [pdf_file.name]
            for _, _, elapsed_ms in file_results:
                row_vals.append(f"{elapsed_ms:.1f}")

            if len(parser_instances) >= 2:
                first_ms = file_results[0][2]
                last_ms = file_results[-1][2]
                speedup = first_ms / max(last_ms, 0.001)
                row_vals.append(f"{speedup:.1f}x")

            row_vals.append(parity_str)
            table.add_row(*row_vals)
            progress.update(task_id, advance=1)

    console.print(table)

    parity_rate = (parity_count / max(total_matches, 1)) * 100.0

    summary_lines = [f"• Matchs analysés :       [cyan]{total_matches}[/cyan]"]
    for label, _ in parser_instances:
        t_ms = total_times[label]
        avg = t_ms / max(total_matches, 1)
        summary_lines.append(f"• Temps total {label} :      [cyan]{t_ms / 1000.0:.2f} s[/cyan] (moy. {avg:.1f} ms/pdf)")

    if len(parser_instances) >= 2:
        ref_label = parser_instances[0][0]
        last_label = parser_instances[-1][0]
        spd = total_times[ref_label] / max(total_times[last_label], 0.001)
        summary_lines.append(f"• Gain moyen de vitesse :  [bold green]{spd:.1f}x ({last_label} vs {ref_label})[/bold green]")

    summary_lines.append(f"• Taux de parité globale : [bold green]{parity_rate:.1f}% de données identiques[/bold green]")

    console.print(Panel(
        "\n".join(summary_lines),
        title="Synthèse",
    ))

    if verbose:
        console.print("\n[bold cyan]Detail exhaustif par fichier (-v active) :[/bold cyan]")
        for fname, matches_list, diffs_list in all_comparison_details:
            console.print(f"\n[bold cyan]Fichier: {fname}[/bold cyan]")
            if matches_list:
                console.print(f"  [bold green]Champs Concordants ({len(matches_list)} champs) :[/bold green]")
                for m in matches_list:
                    console.print(f"     [green]+ {m}[/green]")
            if diffs_list:
                console.print(f"  [bold yellow]Differences Surlignes ({len(diffs_list)} ecarts) :[/bold yellow]")
                for d in diffs_list:
                    console.print(f"     [bold yellow]- {d}[/bold yellow]")
            else:
                console.print("  [bold green]Aucune difference constatee (100% Identique)[/bold green]")


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

    try:
        console.print(f"[blue]🏐 PyVolley sur http://{host}:{port}[/blue]")
    except UnicodeEncodeError:
        console.print(f"[blue]PyVolley sur http://{host}:{port}[/blue]")
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


@app.command("sync-logos")
def sync_logos(
    limit: int = typer.Option(0, "--limit", "-n", help="Nombre max de clubs (0 = tous)."),
    min_score: float = typer.Option(
        0.35,
        "--min-score",
        help="Score minimal de matching pour accepter un logo Volleybox.",
    ),
    only_missing: bool = typer.Option(
        True,
        "--only-missing/--all",
        help="Ne traiter que les clubs sans logo_url.",
    ),
    top_candidates: int = typer.Option(
        3,
        "--top-candidates",
        help="Nombre de candidats Volleybox évalués par club.",
    ),
    review: bool = typer.Option(
        False,
        "--review/--no-review",
        help="Demander une confirmation manuelle pour chaque association.",
    ),
    max_fr_pages: int = typer.Option(
        40,
        "--max-fr-pages",
        help="Nombre max de pages clubs FR explorées.",
    ),
    request_timeout: float = typer.Option(
        25.0,
        "--request-timeout",
        help="Timeout HTTP (secondes) pour les requêtes logos.",
    ),
):
    """🖼 Synchronise les logos clubs depuis Volleybox."""
    from sqlalchemy import select

    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.models import ClubDB
    from pyvolley.scrapers.volleybox import VolleyboxLogoScraper

    init_db()
    scraper = VolleyboxLogoScraper(
        timeout=max(5.0, request_timeout),
        max_fr_pages=max(1, max_fr_pages),
    )

    with DatabaseSession() as session:
        stmt = select(ClubDB).where(ClubDB.code_ffvb.is_not(None)).order_by(ClubDB.nom.asc())
        if only_missing:
            stmt = stmt.where(ClubDB.logo_url.is_(None))

        clubs = session.execute(stmt).scalars().all()
        if limit > 0:
            clubs = clubs[:limit]

        updated = 0
        skipped = 0
        associations: list[tuple[str, str, str, str]] = []
        skip_reasons = {
            "aucun_candidat_logo": 0,
            "score_trop_faible": 0,
            "rejet_manuel": 0,
        }

        with make_progress(console) as progress:
            task_id = progress.add_task("[cyan]Sync logos clubs", total=max(1, len(clubs)))

            for club in clubs:
                progress.update(task_id, description=f"[cyan]Recherche logo: {club.nom[:45]}")

                names = [club.nom]
                if club.nom_court:
                    names.append(club.nom_court)
                names.extend(alias.alias for alias in (club.aliases or []) if alias.alias)

                ordered_names = [name.strip() for name in names if name and name.strip()]
                unique_names: list[str] = []
                seen_names: set[str] = set()
                for name in ordered_names:
                    key = name.lower()
                    if key in seen_names:
                        continue
                    seen_names.add(key)
                    unique_names.append(name)

                selected = scraper.find_logo_for_club(
                    unique_names,
                    target_city=club.ville,
                    prefer_google=True,
                )

                candidates = []
                if (not selected) or selected.source == "volleybox":
                    candidates = scraper.find_team_candidates(
                        unique_names,
                        target_city=club.ville,
                        limit=max(1, top_candidates),
                        min_score=max(0.15, min_score * 0.5),
                    )

                if not selected:
                    skipped += 1
                    skip_reasons["aucun_candidat_logo"] += 1
                    progress.advance(task_id)
                    continue

                if selected.source == "volleybox" and selected.score < min_score:
                    skipped += 1
                    skip_reasons["score_trop_faible"] += 1
                    progress.advance(task_id)
                    continue

                console.print(
                    f"[cyan][PROPOSE][/cyan] {club.nom} -> {selected.logo_url} "
                    f"(source={selected.source}, ref={selected.result_url or selected.team_url}, "
                    f"score={selected.score:.3f}, via={selected.matched_name}, city={selected.matched_city}, city_score={selected.city_score:.3f})"
                )
                if candidates:
                    alternatives = [
                        candidate for candidate in candidates if candidate.team_url != selected.team_url
                    ][:3]
                    for alt in alternatives:
                        console.print(
                            f"  [dim]- alt: {alt.team_url} "
                            f"(score={alt.score:.3f}, via={alt.matched_name}, city={alt.matched_city}, city_score={alt.city_score:.3f})[/dim]"
                        )

                if review and not typer.confirm("Confirmer cette association ?", default=True):
                    skipped += 1
                    skip_reasons["rejet_manuel"] += 1
                    progress.advance(task_id)
                    continue

                club.logo_url = selected.logo_url
                updated += 1
                associations.append(
                    (
                        club.nom,
                        selected.source,
                        selected.result_url or selected.team_url,
                        selected.logo_url or "",
                    )
                )
                progress.advance(task_id)

        session.commit()

    if associations:
        summary = Table(title="Récapitulatif associations logos")
        summary.add_column("Club", style="cyan")
        summary.add_column("Source", style="magenta")
        summary.add_column("Référence", style="blue")
        summary.add_column("Logo", style="green")
        for club_name, source, reference, logo_url in associations:
            summary.add_row(club_name, source, reference, logo_url)
        console.print(summary)

    reason_table = Table(title="Raisons des clubs ignorés")
    reason_table.add_column("Raison", style="yellow")
    reason_table.add_column("Nombre", style="red", justify="right")
    for reason, count in skip_reasons.items():
        reason_table.add_row(reason, str(count))
    console.print(reason_table)

    console.print(
        Panel(
            f"[green]{updated} logo(s) mis à jour[/green]\n"
            f"[yellow]{skipped} club(s) ignoré(s)[/yellow]",
            title="Sync Volleybox",
        )
    )

    if updated == 0:
        console.print(
            "[yellow]Aucun logo validé. Astuce: relancer avec "
            "--min-score 0.2 --review et éventuellement --request-timeout 8.[/yellow]"
        )


@app.command("compute-stats")
def compute_stats(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s",
        help="Restreindre à une saison (23/24) ou une plage (22/25).",
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
        StatsCacheRepository, SaisonRepository,
    )
    from pyvolley.database.stats_service import StatsAmusantesService, StatsFilters

    init_db()

    with get_db() as session:
        if clear:
            repo = StatsCacheRepository(session)
            deleted = repo.delete_all()
            session.commit()
            console.print(f"[yellow]🗑 Cache vidé ({deleted} entrée(s) supprimée(s))[/yellow]")

        service = StatsAmusantesService(session)
        total_played, _ = service.current_cache_signature(StatsFilters())
        if total_played == 0:
            console.print("[yellow]⚠ Aucun match en base — rien à calculer.[/yellow]")
            return

        # Construire la liste des combinaisons de filtres à précalculer
        filters_to_compute: list[StatsFilters] = [StatsFilters()]  # global (aucun filtre)

        if saison is not None:
            requested_codes = []
            try:
                requested_codes = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)

            saison_repo = SaisonRepository(session)
            for code in requested_codes:
                saison_db = saison_repo.get_by_code(code)
                if saison_db is not None:
                    filters_to_compute.append(StatsFilters(saison_id=saison_db.id))
        else:
            saisons = SaisonRepository(session).get_all(limit=50)
            for s in saisons:
                filters_to_compute.append(StatsFilters(saison_id=s.id))

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
            filter_match_count, filter_last_update = service.current_cache_signature(f)

            if filter_match_count == 0:
                table.add_row(label, "[dim]aucun match joué[/dim]", "0")
                skipped += 1
                continue

            if not force and not cache_repo.is_stale(
                key,
                filter_match_count,
                current_last_match_update=filter_last_update,
            ):
                table.add_row(label, "[dim]à jour[/dim]", str(filter_match_count))
                skipped += 1
                continue

            try:
                stats_data = service.get_all_stats(f)
                cache_repo.upsert(
                    key,
                    stats_data,
                    filter_match_count,
                    last_match_update=filter_last_update,
                )
                session.commit()
                table.add_row(label, "[green]✓ calculé[/green]", str(filter_match_count))
                computed += 1
            except Exception as exc:
                session.rollback()
                table.add_row(label, f"[red]✗ {exc}[/red]", str(filter_match_count))

        console.print(table)
        console.print(
            f"[green]✓ {computed} combinaison(s) calculée(s)[/green], "
            f"[dim]{skipped} déjà à jour[/dim]"
        )


@app.command("compute-player-stats")
def compute_player_stats(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s",
        help="Restreindre aux matchs d'une saison (23/24) ou plage (22/25).",
    ),
    entity: Optional[str] = typer.Option(
        None, "--entity", "-e",
        help="Restreindre aux matchs d'une entité (ex: ABCCS).",
    ),
    match_id: Optional[int] = typer.Option(
        None, "--match-id", help="Recalculer un match précis (ID).",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n", help="Nombre max de matchs à traiter.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Recalculer même si les stats sont déjà à jour.",
    ),
    clear: bool = typer.Option(
        False, "--clear", help="Vider la table des stats joueurs avant calcul.",
    ),
):
    """🧮 Calcule et persiste les statistiques détaillées joueur par match.

    Cette commande remplit la table ``joueur_match_stats`` pour éviter les
    recalculs coûteux à l'affichage (web/API).
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from pyvolley.database.connection import get_db, init_db
    from pyvolley.database.models import CompetitionDB, EntiteFFVBDB, MatchDB, ParticipationMatchDB
    from pyvolley.database.player_stats_service import JoueurMatchStatsService
    from pyvolley.database.repositories import JoueurMatchStatsRepository

    init_db()

    with get_db() as session:
        stats_repo = JoueurMatchStatsRepository(session)
        if clear:
            deleted = stats_repo.delete_all()
            session.commit()
            console.print(
                f"[yellow]🗑 Stats joueurs vidées ({deleted} ligne(s) supprimée(s))[/yellow]"
            )

        stmt = (
            select(MatchDB)
            .options(
                selectinload(MatchDB.participations).selectinload(ParticipationMatchDB.joueur),
                selectinload(MatchDB.sets),
            )
            .where(MatchDB.has_details == True)  # noqa: E712
        )
        if match_id is not None:
            stmt = stmt.where(MatchDB.id == match_id)
        if saison is not None:
            try:
                requested_codes = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)

            from pyvolley.database.models import SaisonDB

            saison_ids = [
                s.id for s in session.scalars(
                    select(SaisonDB).where(SaisonDB.code.in_(requested_codes))
                ).all()
            ]
            if not saison_ids:
                console.print(f"[yellow]Aucune saison trouvée pour '{saison}'[/yellow]")
                return
            stmt = stmt.where(MatchDB.saison_id.in_(saison_ids))
        if entity is not None:
            entity_code = entity.strip().upper()
            entite_db = session.scalars(
                select(EntiteFFVBDB).where(EntiteFFVBDB.code == entity_code)
            ).first()
            if entite_db is None:
                console.print(f"[yellow]Entité '{entity}' non trouvée[/yellow]")
                return

            competition_ids = [
                c.id
                for c in session.scalars(
                    select(CompetitionDB).where(CompetitionDB.entite_id == entite_db.id)
                ).all()
            ]
            if not competition_ids:
                console.print(
                    f"[yellow]Aucune compétition trouvée pour l'entité '{entity_code}'[/yellow]"
                )
                return
            stmt = stmt.where(MatchDB.competition_id.in_(competition_ids))
        stmt = stmt.order_by(MatchDB.date_match.desc(), MatchDB.id.desc())
        if limit:
            stmt = stmt.limit(limit)

        matches = list(session.scalars(stmt).all())
        if not matches:
            console.print("[yellow]Aucun match détaillé à traiter[/yellow]")
            return

        service = JoueurMatchStatsService(session)
        stats_repo = JoueurMatchStatsRepository(session)
        processed = 0
        skipped_up_to_date = 0
        skipped_not_played = 0
        skipped_not_parsed = 0
        skipped_no_expected_players = 0
        updated_rows = 0
        errors = 0

        with make_progress(console) as progress:
            task = progress.add_task("Calcul stats joueurs...", total=len(matches))

            for m_full in matches:
                try:
                    if not m_full.match_joue:
                        skipped_not_played += 1
                        progress.update(
                            task,
                            advance=1,
                            description=f"[dim]↷ match #{m_full.id} non joué[/dim]",
                        )
                        continue

                    if m_full.parsing_status != "parsed":
                        skipped_not_parsed += 1
                        progress.update(
                            task,
                            advance=1,
                            description=(
                                f"[dim]↷ match #{m_full.id} non parsé "
                                f"({m_full.parsing_status})[/dim]"
                            ),
                        )
                        continue

                    participants = list(m_full.participations or [])
                    valid_participants = [
                        p
                        for p in participants
                        if p.joueur and p.joueur.licence
                    ]
                    expected_ids = [p.joueur_id for p in valid_participants]

                    is_stale = True
                    if not force:
                        is_stale = stats_repo.is_match_stale(
                            m_full.id,
                            expected_joueur_ids=expected_ids,
                            match_updated_at=m_full.updated_at,
                        )

                    if not expected_ids and not is_stale and not force:
                        skipped_no_expected_players += 1
                        progress.update(
                            task,
                            advance=1,
                            description=(
                                f"[dim]↷ match #{m_full.id} sans joueurs exploitables[/dim]"
                            ),
                        )
                        continue

                    if not force and not is_stale:
                        skipped_up_to_date += 1
                        progress.update(
                            task,
                            advance=1,
                            description=f"[dim]↷ match #{m_full.id} déjà à jour[/dim]",
                        )
                        continue

                    count = service.compute_and_store_for_match(m_full, force=True)
                    updated_rows += count
                    processed += 1
                    progress.update(
                        task,
                        advance=1,
                        description=f"[green]✓ match #{m_full.id} ({count} joueur(s))[/green]",
                    )

                    if processed % 100 == 0:
                        session.commit()
                        session.commit()

                except Exception as exc:
                    session.rollback()
                    errors += 1
                    progress.update(
                        task,
                        advance=1,
                        description=f"[red]✗ match #{m.id}: {str(exc)[:40]}[/red]",
                    )

            session.commit()

        console.print(Panel(
            f"[green]✓ Matchs traités : {processed}[/green]\n"
            f"[dim]↷ Matchs ignorés (déjà à jour) : {skipped_up_to_date}[/dim]\n"
            f"[dim]↷ Matchs ignorés (non joués) : {skipped_not_played}[/dim]\n"
            f"[dim]↷ Matchs ignorés (non parsés) : {skipped_not_parsed}[/dim]\n"
            f"[dim]↷ Matchs ignorés (sans joueurs exploitables) : {skipped_no_expected_players}[/dim]\n"
            f"[cyan]👥 Lignes stats écrites : {updated_rows}[/cyan]\n"
            f"[red]✗ Erreurs : {errors}[/red]",
            title="Statistiques joueurs",
        ))


@app.command("plausibility-audit")
def plausibility_audit(
    saison: Optional[List[str]] = typer.Option(
        None, "--saison", "-s",
        help="Restreindre à une saison (23/24) ou une plage (22/25).",
    ),
    entity: Optional[List[str]] = typer.Option(
        None, "--entity", "-e",
        help="Filtrer par code entité (ex: ABCCS). Répétable.",
    ),
    status: Optional[List[str]] = typer.Option(
        None, "--status",
        help="Filtrer par statut parsing (discovered, downloaded, parsed, error). Répétable.",
    ),
    played_only: bool = typer.Option(
        False, "--played-only",
        help="Ne traiter que les matchs joués.",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n",
        help="Nombre max de matchs à analyser.",
    ),
    policy: str = typer.Option(
        "auto", "--policy",
        help="Politique de plausibilité: auto, report-only, strict.",
    ),
    review_fixes: bool = typer.Option(
        False, "--review-fixes",
        help="Valider manuellement les corrections qui demandent revue.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Analyse sans modifier la base.",
    ),
    report_file: Optional[Path] = typer.Option(
        None, "--report-file",
        help="Chemin du rapport JSON de l'audit (par défaut dans data/reports).",
    ),
    include_issues: bool = typer.Option(
        True, "--include-issues/--summary-only",
        help="Inclure le détail des anomalies dans le rapport JSON.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Affichage détaillé par match.",
    ),
):
    """🧪 Exécute les contrôles de vraisemblance a posteriori sur les matchs en base."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from pyvolley.database.connection import DatabaseSession, init_db
    from pyvolley.database.converters import match_db_to_core
    from pyvolley.database.models import ImportLogDB, MatchDB
    from pyvolley.parsers.plausibility import PlausibilityEngine

    normalized_policy = (policy or "auto").strip().lower()
    if normalized_policy not in {"auto", "report-only", "strict"}:
        console.print(
            f"[yellow]Politique '{policy}' invalide, fallback sur 'auto'[/yellow]"
        )
        normalized_policy = "auto"

    if report_file is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = Path("data/reports") / f"plausibility_audit_{stamp}.json"

    init_db()
    reviewer = build_plausibility_reviewer(console) if review_fixes else None
    engine = PlausibilityEngine()

    summary_data = {
        "checked": 0,
        "with_issues": 0,
        "with_changes": 0,
        "total_issues": 0,
        "by_action": {},
        "by_rule": {},
    }
    report_rows: list[dict[str, object]] = []

    with DatabaseSession() as session:
        stmt = (
            select(MatchDB)
            .options(joinedload(MatchDB.sets))
            .options(joinedload(MatchDB.saison))
            .options(joinedload(MatchDB.equipe_a))
            .options(joinedload(MatchDB.equipe_b))
            .order_by(MatchDB.date_match.desc(), MatchDB.id.desc())
        )

        stmt, _ = add_saison_filter(session, stmt, saison)
        stmt = add_entity_filter(session, stmt, entity)

        if status:
            stmt = stmt.where(MatchDB.parsing_status.in_(status))
        if played_only:
            stmt = stmt.where(MatchDB.match_joue == True)  # noqa: E712
        if limit:
            stmt = stmt.limit(limit)

        matches = list(session.scalars(stmt).unique().all())
        if not matches:
            console.print("[yellow]Aucun match trouvé pour cet audit[/yellow]")
            raise typer.Exit(0)

        log_entry = None
        if not dry_run:
            log_entry = ImportLogDB(
                operation="plausibility-audit",
                source=(
                    f"saison={','.join(saison or []) or '*'};"
                    f"entity={','.join(entity or []) or '*'};"
                    f"status={','.join(status or []) or '*'}"
                ),
                total_attempted=len(matches),
            )
            session.add(log_entry)
            session.flush()

        with make_progress(console) as progress:
            task = progress.add_task("Audit plausibilité...", total=len(matches))

            for idx, match_db in enumerate(matches, start=1):
                core_match = match_db_to_core(
                    match_db,
                    participants_a=[],
                    participants_b=[],
                )
                plausibility_report = engine.check(
                    core_match,
                    policy=normalized_policy,
                    approve=reviewer,
                )
                summary = plausibility_report.summary()
                changes = apply_plausibility_core_to_match_db(
                    match_db,
                    core_match,
                    apply_changes=(not dry_run),
                )

                summary_data["checked"] += 1
                total_issues_raw = summary.get("total", 0)
                total_issues = int(total_issues_raw) if isinstance(total_issues_raw, (int, float, str)) else 0
                summary_data["total_issues"] += total_issues
                if total_issues > 0:
                    summary_data["with_issues"] += 1
                if changes:
                    summary_data["with_changes"] += 1

                by_action = summary.get("by_action", {}) or {}
                if isinstance(by_action, dict):
                    for action, count in by_action.items():
                        current = int(summary_data["by_action"].get(action, 0))
                        summary_data["by_action"][action] = current + int(count)

                by_rule = summary.get("by_rule", {}) or {}
                if isinstance(by_rule, dict):
                    for rule_id, count in by_rule.items():
                        current = int(summary_data["by_rule"].get(rule_id, 0))
                        summary_data["by_rule"][rule_id] = current + int(count)

                if changes and not dry_run:
                    match_db.updated_at = datetime.now()

                if total_issues > 0 or changes:
                    row = {
                        "match_id": match_db.id,
                        "code_match": match_db.code_match,
                        "saison": match_db.saison.code if match_db.saison else None,
                        "summary": summary,
                        "changes": changes,
                    }
                    if include_issues:
                        row["issues"] = [
                            issue.to_dict() for issue in plausibility_report.issues
                        ]
                    report_rows.append(row)

                if verbose and (summary.get("total", 0) or changes):
                    progress.console.print(
                        f"  [magenta]#{match_db.id} {match_db.code_match}[/magenta] "
                        f"issues={summary.get('total', 0)} changes={len(changes)}"
                    )

                if not dry_run and idx % 200 == 0:
                    session.commit()

                progress.update(
                    task,
                    advance=1,
                    description=(
                        f"[cyan]Audit plausibilité[/cyan] "
                        f"({summary_data['checked']}/{len(matches)})"
                    ),
                )

        report_payload = {
            "generated_at": datetime.now().isoformat(),
            "config": {
                "policy": normalized_policy,
                "dry_run": dry_run,
                "review_fixes": review_fixes,
                "saison": saison or [],
                "entity": entity or [],
                "status": status or [],
                "played_only": played_only,
                "limit": limit,
            },
            "summary": summary_data,
            "matches": report_rows,
        }

        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if log_entry is not None:
            log_entry.finished_at = datetime.now()
            log_entry.imported = summary_data["with_changes"]
            log_entry.duplicates = max(summary_data["checked"] - summary_data["with_changes"], 0)
            log_entry.errors = 0
            log_entry.updated = summary_data["with_changes"]
            log_entry.summary = json.dumps(
                {
                    "plausibility": {
                        "policy": normalized_policy,
                        "checked": summary_data["checked"],
                        "with_issues": summary_data["with_issues"],
                        "with_changes": summary_data["with_changes"],
                        "total_issues": summary_data["total_issues"],
                        "by_action": summary_data["by_action"],
                        "by_rule": summary_data["by_rule"],
                        "dry_run": dry_run,
                    },
                    "report_file": str(report_file),
                },
                ensure_ascii=False,
            )
            log_entry.status = "success"
            session.commit()

    console.print(Panel(
        f"[cyan]Matchs analysés : {summary_data['checked']}[/cyan]\n"
        f"[yellow]Matchs avec anomalies : {summary_data['with_issues']}[/yellow]\n"
        f"[magenta]{'Matchs modifiables' if dry_run else 'Matchs modifiés'} : "
        f"{summary_data['with_changes']}[/magenta]\n"
        f"[green]Rapport : {report_file}[/green]",
        title="Audit de plausibilité",
    ))

    summary_table = Table(title="🧪 Actions de plausibilité")
    summary_table.add_column("Action", style="magenta")
    summary_table.add_column("Occurrences", justify="right", style="cyan")
    for action, count in sorted(
        summary_data["by_action"].items(), key=lambda i: i[1], reverse=True,
    ):
        summary_table.add_row(action, str(count))
    if summary_data["by_action"]:
        console.print(summary_table)

    rules_table = Table(title="🧩 Règles touchées")
    rules_table.add_column("Règle", style="white")
    rules_table.add_column("Occurrences", justify="right", style="yellow")
    for rule_id, count in sorted(
        summary_data["by_rule"].items(), key=lambda i: i[1], reverse=True,
    ):
        rules_table.add_row(rule_id, str(count))
    if summary_data["by_rule"]:
        console.print(rules_table)


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

# Sous-commandes de rôles (inférence, diffusion réseau, audit)
from pyvolley.cli.roles_cli import roles_app
app.add_typer(roles_app, name="roles")

# Sous-commandes de développement
dev_app = typer.Typer(help="Outils de développement")
app.add_typer(dev_app, name="dev")


@dev_app.command("layout-editor")
@app.command("layout-editor")
def launch_layout_editor(
    pdf_path: Optional[Path] = typer.Argument(
        None, help="Chemin d'accès optionnel vers un fichier PDF de feuille de match"
    )
):
    """Lancer l'éditeur interactif de layout et inspecteur de parsing PDF (Dev Tool)."""
    console.print("[cyan]Lancement du Layout Editor & Inspector (GUI)...[/cyan]")
    import sys
    import subprocess
    script_path = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "layout_editor.py"
    cmd = [sys.executable, str(script_path)]
    if pdf_path:
        cmd.append(str(pdf_path))
    subprocess.run(cmd)


@dev_app.command("profile-parser")
def profile_parser_cli(
    pdf_path: Optional[Path] = typer.Option(
        None, "--pdf", "-p", help="Fichier PDF spécifique à profiler. Si omis, profile l'ensemble des PDFs d'exemple."
    ),
    iterations: int = typer.Option(
        1, "--iterations", "-n", help="Nombre d'itérations par PDF pour moyenner les mesures."
    )
):
    """Profilage complet de la vitesse d'exécution du FastMatchSheetParser avec métriques détaillées."""
    import time
    import glob
    import pymupdf
    from pyvolley.parsers.fast_parser import FastMatchSheetParser
    from pyvolley.parsers.layout_config import DEFAULT_FFVB_LAYOUT
    from pyvolley.parsers.extractors.fast import (
        normalize_words,
        extract_fast_header,
        extract_fast_rosters,
        extract_fast_arbitres,
        extract_fast_resultats,
        extract_fast_sets,
    )

    console.print(Panel("[bold cyan][PROFILER] PROFILAGE DÉTAILLÉ DE LA VITESSE D'EXÉCUTION DU PARSER FAST (DEV CLI)[/bold cyan]"))

    pdf_files = [pdf_path] if pdf_path else [Path(p) for p in sorted(glob.glob("data/data_sample/*.pdf"))]
    if not pdf_files:
        console.print("[red]Aucun fichier PDF trouvé à profiler.[/red]")
        return

    table = Table(title="Performance par Fichier PDF", show_header=True, header_style="bold magenta")
    table.add_column("Fichier PDF", style="cyan", width=16)
    table.add_column("PyMuPDF IO", justify="right", width=12)
    table.add_column("Extraction Fast", justify="right", width=16)
    table.add_column("Modèle Match", justify="right", width=14)
    table.add_column("Temps Total", justify="right", width=12, style="bold green")

    results = []
    parser = FastMatchSheetParser()

    for pfile in pdf_files:
        if not pfile.exists():
            continue

        tot_io, tot_extract, tot_model, tot_full = 0.0, 0.0, 0.0, 0.0
        for _ in range(iterations):
            # Benchmark Parse direct
            t_start = time.perf_counter_ns()
            res = parser.parse(pfile)
            t_end = time.perf_counter_ns()
            tot_full += (t_end - t_start) / 1e6

            # Décomposition des sous-étapes
            t0 = time.perf_counter_ns()
            doc = pymupdf.open(pfile)
            page = doc[0]
            raw_words = page.get_text("words")
            sorted_words, y0_list = normalize_words(raw_words)
            image_info_list = page.get_image_info(hashes=True)
            captain_image_bboxes = [img["bbox"] for img in image_info_list if "bbox" in img]
            doc.close()
            t1 = time.perf_counter_ns()

            # Extraction modulaire complète
            hdr = extract_fast_header(sorted_words, y0_list, DEFAULT_FFVB_LAYOUT, image_blocks=image_info_list)
            eq_a, eq_b, _, _ = extract_fast_rosters(
                sorted_words, y0_list, DEFAULT_FFVB_LAYOUT,
                nom_gauche=hdr.nom_gauche, nom_droite=hdr.nom_droite,
                gauche_est_equipe_a=hdr.gauche_est_equipe_a,
                captain_image_bboxes=captain_image_bboxes
            )
            arbs = extract_fast_arbitres(sorted_words, y0_list, DEFAULT_FFVB_LAYOUT)
            res_data = extract_fast_resultats(sorted_words, y0_list, DEFAULT_FFVB_LAYOUT)
            sets_list = extract_fast_sets(
                sorted_words, y0_list, DEFAULT_FFVB_LAYOUT,
                gauche_est_equipe_a=hdr.gauche_est_equipe_a,
                sets_summary=res_data.sets_summary
            )
            t2 = time.perf_counter_ns()

            tot_io += (t1 - t0) / 1e6
            tot_extract += (t2 - t1) / 1e6
            tot_model += max(0.0, ((t_end - t_start) / 1e6) - ((t1 - t0) / 1e6) - ((t2 - t1) / 1e6))

        avg_io = tot_io / iterations
        avg_extract = tot_extract / iterations
        avg_model = tot_model / iterations
        avg_full = tot_full / iterations

        results.append({
            "file": pfile.name,
            "io": avg_io,
            "extract": avg_extract,
            "model": avg_model,
            "full": avg_full,
        })
        table.add_row(
            pfile.name,
            f"{avg_io:.2f} ms",
            f"{avg_extract:.2f} ms",
            f"{avg_model:.2f} ms",
            f"{avg_full:.2f} ms",
        )

    console.print(table)

    if results:
        mean_io = sum(r["io"] for r in results) / len(results)
        mean_extract = sum(r["extract"] for r in results) / len(results)
        mean_model = sum(r["model"] for r in results) / len(results)
        mean_full = sum(r["full"] for r in results) / len(results)

        summary_table = Table(title="[STATISTIQUES] Répartition Moyenne du Temps d'Exécution", show_header=True, header_style="bold yellow")
        summary_table.add_column("Étape", style="bold white")
        summary_table.add_column("Temps Moyen", justify="right", style="cyan")
        summary_table.add_column("Pourcentage", justify="right", style="bold green")

        summary_table.add_row("1. Lecture IO PyMuPDF (words + hashes)", f"{mean_io:.2f} ms", f"{mean_io/mean_full*100:.1f}%")
        summary_table.add_row("2. Extraction directe (Header, Rosters, Sets, Arbitres, Résultats)", f"{mean_extract:.2f} ms", f"{mean_extract/mean_full*100:.1f}%")
        summary_table.add_row("3. Modèles Pydantic & Instanciation Match", f"{mean_model:.2f} ms", f"{mean_model/mean_full*100:.1f}%")
        summary_table.add_row("[bold]TOTAL MOYEN PER PDF[/bold]", f"[bold]{mean_full:.2f} ms[/bold]", "[bold]100.0%[/bold]")

        console.print(summary_table)


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
    from pyvolley.database.connection import get_db
    from pyvolley.database.models import SaisonDB
    from pyvolley.database.rollup_service import RollupStatsService
    from sqlalchemy import select

    with get_db() as session:
        saison_id = None
        if saison:
            s_obj = session.scalars(select(SaisonDB).where(SaisonDB.code == saison)).first()
            if not s_obj:
                console.print(f"[red]Saison '{saison}' introuvable.[/red]")
                raise typer.Exit(1)
            saison_id = s_obj.id

        service = RollupStatsService(session)
        console.print("[cyan][...] Calcul et synchronisation des stats joueur par match...[/cyan]")
        n_jms = service.compute_all_player_match_stats(saison_id=saison_id)
        console.print(f"[green][OK] {n_jms} lignes joueur_match_stats synchronisees.[/green]")

        console.print("[cyan][...] Calcul des statistiques joueur par saison...[/cyan]")
        n_js = service.compute_player_season_stats(saison_id=saison_id)
        console.print(f"[green][OK] {n_js} lignes stats_joueur_saison calculees.[/green]")

        console.print("[cyan][...] Calcul des bilans d'equipe par saison...[/cyan]")
        n_es = service.compute_team_season_stats(saison_id=saison_id)
        console.print(f"[green][OK] {n_es} lignes stats_equipe_saison calculees.[/green]")

        console.print("[cyan][...] Calcul des syntheses de carriere joueur...[/cyan]")
        n_jc = service.compute_player_career_stats()
        console.print(f"[green][OK] {n_jc} lignes stats_joueur_carriere calculees.[/green]")

    console.print(
        Panel(
            f"[bold green]Statistiques agglomerees generees avec succes ![/bold green]\n"
            f"- Stats Joueur/Match  : [bold]{n_jms}[/bold]\n"
            f"- Stats Joueur/Saison : [bold]{n_js}[/bold]\n"
            f"- Stats Equipe/Saison : [bold]{n_es}[/bold]\n"
            f"- Stats Carriere      : [bold]{n_jc}[/bold]",
            title="Bilan des Rollups",
        )
    )


@app.command("compute-rollups")
def app_compute_rollups(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Code de la saison (ex: 2025-2026)."
    ),
):
    """Calcule et synchronise les statistiques de match et agglomerees (raccourci vers db compute-rollups)."""
    db_compute_rollups(saison=saison)





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

    if deleted:
        console.print(f"[dim]🗑 {deleted} PDFs supprimés (déjà parsés)[/dim]")


_apply_plausibility_core_to_match_db = apply_plausibility_core_to_match_db


# ════════════════════════════════════════════════════════════════════
# Point d'entrée
# ════════════════════════════════════════════════════════════════════


def main():
    """Point d'entrée principal."""
    app()


if __name__ == "__main__":
    main()
