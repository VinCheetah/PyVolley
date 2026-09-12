"""Commandes de calcul et d'actualisation des statistiques (`pyvolley compute-*` ou `pyvolley compute`)."""

from __future__ import annotations

import time
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from pyvolley.cli.helpers import (
    make_progress,
    saisons_to_db_codes,
    PipelineTimer,
    format_duration,
    format_rate,
)

console = Console()


def _unwrap(val, default=None):
    """Déballe un paramètre Typer (OptionInfo) si la fonction est appelée directement en Python."""
    if hasattr(val, "default"):
        return val.default if val.default is not ... else default
    return val if val is not None else default


def _get_make_progress():
    import sys
    mod = sys.modules.get("pyvolley.cli.main")
    if mod and hasattr(mod, "make_progress"):
        return mod.make_progress
    return make_progress
compute_app = typer.Typer(
    help="🧮 Calcul et synchronisation des statistiques (rollups, joueurs, palmarès)",
    no_args_is_help=True,
)


@compute_app.command("palmares")
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
    saison = _unwrap(saison)
    force = bool(_unwrap(force, False))
    clear = bool(_unwrap(clear, False))

    from pyvolley.database.connection import get_db, init_db
    from pyvolley.database.repositories import (
        StatsCacheRepository, SaisonRepository,
    )
    from pyvolley.database.stats_service import StatsAmusantesService, StatsFilters

    init_db()

    with get_db() as session:
        if clear:
            cache_repo = StatsCacheRepository(session)
            deleted = cache_repo.clear()
            session.commit()
            console.print(f"[yellow]🗑 Cache vidé ({deleted} entrées supprimées)[/yellow]")

        service = StatsAmusantesService(session)
        saison_repo = SaisonRepository(session)

        filter_combos: list[tuple[str, StatsFilters]] = [
            ("Toutes saisons", StatsFilters()),
        ]

        if saison:
            try:
                requested_codes = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)

            target_saisons = [
                s for s in saison_repo.get_all()
                if s.code in requested_codes
            ]
        else:
            target_saisons = saison_repo.get_all()

        for s in target_saisons:
            filter_combos.append(
                (f"Saison {s.code}", StatsFilters(saison=s.code))
            )

        console.print(
            f"[blue]Calcul des statistiques pour "
            f"{len(filter_combos)} combinaison(s)...[/blue]\n"
        )

        computed = 0
        skipped = 0

        t0 = time.perf_counter()
        with make_progress(console) as progress:
            task = progress.add_task("Calcul...", total=len(filter_combos))

            for label, filters in filter_combos:
                if not force and service.is_cache_valid(filters):
                    skipped += 1
                    progress.update(
                        task, advance=1,
                        description=f"[dim]↷ {label} (à jour)[/dim]",
                    )
                    continue

                service.compute_and_cache(filters)
                computed += 1
                progress.update(
                    task, advance=1,
                    description=f"[green]✓ {label}[/green]",
                )

        duration = time.perf_counter() - t0
        rate_str = format_rate(computed, duration, "combos")
        console.print(
            f"\n[green]✓ {computed} calculées en {format_duration(duration)} ({rate_str})[/green] | "
            f"[dim]{skipped} déjà à jour[/dim]"
        )


@compute_app.command("players")
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
    saison = _unwrap(saison)
    entity = _unwrap(entity)
    match_id = _unwrap(match_id)
    limit = _unwrap(limit)
    force = bool(_unwrap(force, False))
    clear = bool(_unwrap(clear, False))

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

        t0 = time.perf_counter()
        with _get_make_progress()(console) as progress:
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

                except Exception as exc:
                    session.rollback()
                    errors += 1
                    progress.update(
                        task,
                        advance=1,
                        description=f"[red]✗ match #{m_full.id}: {str(exc)[:40]}[/red]",
                    )

            session.commit()

        duration = time.perf_counter() - t0
        console.print(Panel(
            f"[green]✓ Matchs traités : {processed}[/green]\n"
            f"[dim]↷ Matchs ignorés (déjà à jour) : {skipped_up_to_date}[/dim]\n"
            f"[dim]↷ Matchs ignorés (non joués) : {skipped_not_played}[/dim]\n"
            f"[dim]↷ Matchs ignorés (non parsés) : {skipped_not_parsed}[/dim]\n"
            f"[dim]↷ Matchs ignorés (sans joueurs exploitables) : {skipped_no_expected_players}[/dim]\n"
            f"[cyan]👥 Lignes stats écrites : {updated_rows}[/cyan]\n"
            f"[red]✗ Erreurs : {errors}[/red]\n"
            f"[yellow]⏱ Durée de calcul : {format_duration(duration)} "
            f"({format_rate(processed, duration, 'matchs')}, {format_rate(updated_rows, duration, 'lignes')})[/yellow]",
            title=f"Statistiques joueurs (calculées en {format_duration(duration)})",
        ))


@compute_app.command("rollups")
def compute_rollups(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Code de la saison (ex: 2025-2026)."
    ),
):
    """Calcule et génère les statistiques agglomérées (joueur-saison, équipes, carrières)."""
    saison = _unwrap(saison)

    from pyvolley.database.connection import get_db
    from pyvolley.database.models import SaisonDB
    from pyvolley.database.rollup_service import RollupStatsService
    from sqlalchemy import select

    with get_db() as session:
        saison_id = None
        if saison:
            try:
                requested_codes = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)
            s_obj = session.scalars(select(SaisonDB).where(SaisonDB.code.in_(requested_codes))).first()
            if not s_obj:
                console.print(f"[red]Saison '{saison}' introuvable.[/red]")
                raise typer.Exit(1)
            saison_id = s_obj.id

        t_all_start = time.perf_counter()
        service = RollupStatsService(session)

        t0 = time.perf_counter()
        console.print("[cyan][...] Calcul et synchronisation des stats joueur par match...[/cyan]")
        n_jms = service.compute_all_player_match_stats(saison_id=saison_id)
        d0 = time.perf_counter() - t0
        console.print(f"[green][OK] {n_jms} lignes joueur_match_stats synchronisées en {format_duration(d0)} ({format_rate(n_jms, d0, 'lignes')}).[/green]")

        t1 = time.perf_counter()
        console.print("[cyan][...] Calcul des statistiques joueur par saison...[/cyan]")
        n_js = service.compute_player_season_stats(saison_id=saison_id)
        d1 = time.perf_counter() - t1
        console.print(f"[green][OK] {n_js} lignes stats_joueur_saison calculées en {format_duration(d1)} ({format_rate(n_js, d1, 'lignes')}).[/green]")

        t2 = time.perf_counter()
        console.print("[cyan][...] Calcul des bilans d'équipe par saison...[/cyan]")
        n_es = service.compute_team_season_stats(saison_id=saison_id)
        d2 = time.perf_counter() - t2
        console.print(f"[green][OK] {n_es} lignes stats_equipe_saison calculées en {format_duration(d2)} ({format_rate(n_es, d2, 'lignes')}).[/green]")

        t3 = time.perf_counter()
        console.print("[cyan][...] Calcul des statistiques agglomérées par club...[/cyan]")
        n_cs = service.compute_club_stats(saison_id=saison_id)
        service.compute_club_stats(saison_id=None)
        d3 = time.perf_counter() - t3
        console.print(f"[green][OK] {n_cs} lignes stats_club calculées en {format_duration(d3)} ({format_rate(n_cs, d3, 'lignes')}).[/green]")

        t4 = time.perf_counter()
        console.print("[cyan][...] Calcul des synthèses de carrière joueur...[/cyan]")
        n_jc = service.compute_player_career_stats()
        d4 = time.perf_counter() - t4
        console.print(f"[green][OK] {n_jc} lignes stats_joueur_carriere calculées en {format_duration(d4)} ({format_rate(n_jc, d4, 'lignes')}).[/green]")

        total_rollups_duration = time.perf_counter() - t_all_start

    console.print(
        Panel(
            f"[bold green]Statistiques agglomérées générées avec succès ![/bold green]\n"
            f"- Stats Joueur/Match  : [bold]{n_jms}[/bold] ({format_duration(d0)})\n"
            f"- Stats Joueur/Saison : [bold]{n_js}[/bold] ({format_duration(d1)})\n"
            f"- Stats Equipe/Saison : [bold]{n_es}[/bold] ({format_duration(d2)})\n"
            f"- Stats Club          : [bold]{n_cs}[/bold] ({format_duration(d3)})\n"
            f"- Stats Carrière      : [bold]{n_jc}[/bold] ({format_duration(d4)})\n"
            f"[yellow]⏱ Durée totale rollups : {format_duration(total_rollups_duration)}[/yellow]",
            title=f"Bilan des Rollups (calculés en {format_duration(total_rollups_duration)})",
        )
    )


@compute_app.command("clubs")
def compute_clubs(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Code de la saison (ex: 2025-2026)."
    ),
):
    """Calcule les statistiques agglomérées de clubs."""
    saison = _unwrap(saison)

    from pyvolley.database.connection import get_db
    from pyvolley.database.models import SaisonDB
    from pyvolley.database.rollup_service import RollupStatsService
    from sqlalchemy import select

    t0 = time.perf_counter()
    with get_db() as session:
        saison_id = None
        if saison:
            try:
                requested_codes = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)
            s_obj = session.scalars(select(SaisonDB).where(SaisonDB.code.in_(requested_codes))).first()
            if not s_obj:
                console.print(f"[red]Saison '{saison}' introuvable.[/red]")
                raise typer.Exit(1)
            saison_id = s_obj.id

        service = RollupStatsService(session)
        console.print("[cyan][...] Calcul des statistiques par club...[/cyan]")
        n_saison = service.compute_club_stats(saison_id=saison_id)
        n_global = service.compute_club_stats(saison_id=None)
        session.commit()
        duration = time.perf_counter() - t0
        console.print(
            f"[green]✓ Calcul terminé en {format_duration(duration)} : "
            f"{n_saison} entrées saison, {n_global} entrées historiques.[/green]"
        )


@compute_app.command("geo")
def compute_geo(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Code de la saison (ex: 2025-2026)."
    ),
):
    """Calcule les agrégats territoriaux (France, régions, départements)."""
    saison = _unwrap(saison)

    from pyvolley.database.connection import get_db
    from pyvolley.database.models import SaisonDB
    from pyvolley.database.geographic_service import GeographicStatsService
    from sqlalchemy import select

    t0 = time.perf_counter()
    with get_db() as session:
        saison_id = None
        if saison:
            try:
                requested_codes = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)
            s_obj = session.scalars(select(SaisonDB).where(SaisonDB.code.in_(requested_codes))).first()
            if not s_obj:
                console.print(f"[red]Saison '{saison}' introuvable.[/red]")
                raise typer.Exit(1)
            saison_id = s_obj.id

        service = GeographicStatsService(session)
        console.print("[cyan][...] Calcul des agrégats territoriaux...[/cyan]")
        count = service.compute_territorial_rollups(saison_id=saison_id)
        if saison_id is not None:
            service.compute_territorial_rollups(saison_id=None)
        duration = time.perf_counter() - t0
        console.print(
            f"[green]✓ {count} agrégats territoriaux générés en {format_duration(duration)} "
            f"(National, Ligues, Départements).[/green]"
        )


@compute_app.command("licences")
def compute_licences(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Code de la saison (ex: 2025-2026)."
    ),
):
    """Calcule le statut des licences (nouvelles, reprises, renouvellements)."""
    saison = _unwrap(saison)

    from pyvolley.database.connection import get_db
    from pyvolley.database.models import SaisonDB
    from pyvolley.database.licence_analysis_service import LicenceAnalysisService
    from sqlalchemy import select

    t0 = time.perf_counter()
    with get_db() as session:
        service = LicenceAnalysisService(session)
        if saison:
            try:
                requested_codes = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)
            s_obj = session.scalars(select(SaisonDB).where(SaisonDB.code.in_(requested_codes))).first()
            if not s_obj:
                console.print(f"[red]Saison '{saison}' introuvable.[/red]")
                raise typer.Exit(1)
            console.print(f"[cyan][...] Analyse des licences pour la saison {s_obj.code}...[/cyan]")
            count = service.compute_licence_history(s_obj.id)
            report = service.get_licence_report(s_obj.id)
            duration = time.perf_counter() - t0
            console.print(
                f"[green]✓ {count} licences analysées en {format_duration(duration)} : "
                f"{report.nouvelles_licences} nouvelles, {report.reprises} reprises, "
                f"{report.continues} continues ({report.taux_renouvellement}% rétention).[/green]"
            )
        else:
            console.print("[cyan][...] Analyse des licences sur l'ensemble des saisons...[/cyan]")
            count = service.compute_all_seasons_licence_history()
            duration = time.perf_counter() - t0
            console.print(
                f"[green]✓ {count} enregistrements d'historique de licence générés en "
                f"{format_duration(duration)}.[/green]"
            )


@compute_app.command("all")
def compute_all(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Code de la saison (ex: 23/24 ou 2025-2026)."
    ),
    force: bool = typer.Option(False, "--force", help="Forcer le recalcul complet."),
    skip_roles: bool = typer.Option(False, "--skip-roles", help="Ignorer l'étape de diffusion réseau des rôles."),
    timing_detail: str = typer.Option(
        "summary", "--timing-detail", "--timing-summary", "-T",
        help="Niveau de détail du récapitulatif temporel : 'none', 'summary' ou 'detailed'.",
    ),
):
    """Exécute l'ensemble de la chaîne de calculs statistiques dans l'ordre rigoureux des dépendances :
    1. Statistiques joueurs par match (timeline et évidences locales)
    2. Diffusion réseau des rôles (propagation multi-passes avec coéquipiers)
    3. Statistiques agglomérées (rollups avec rôles stabilisés)
    4. Agrégats territoriaux
    5. Analyse du cycle des licences
    6. Palmarès et caches
    """
    saison = _unwrap(saison)
    force = bool(_unwrap(force, False))
    skip_roles = bool(_unwrap(skip_roles, False))
    timing_detail = str(_unwrap(timing_detail, "summary"))

    timer = PipelineTimer(label="Chaîne Complète de Calculs (compute all)")

    # 1. Joueurs par match
    console.print("[bold blue]=== 1/6 Statistiques Joueurs par Match ===[/bold blue]")
    with timer.step("players", "1/6 Stats Joueurs par Match", items_unit="matchs") as s:
        compute_player_stats(
            saison=saison,
            entity=None,
            match_id=None,
            limit=None,
            force=force,
            clear=False,
        )
    console.print(f"[green]✓ Étape 1/6 terminée en {format_duration(s.duration)}[/green]\n")

    # 2. Diffusion rôles
    if not skip_roles:
        console.print("[bold blue]=== 2/6 Diffusion Réseau des Rôles (3 passes) ===[/bold blue]")
        from pyvolley.cli.commands.roles_cmd import diffuse_roles
        with timer.step("roles", "2/6 Diffusion Réseau des Rôles", items_unit="passes") as s:
            diffuse_roles(
                iterations=3,
                saison=saison,
                entity=None,
                match_id=None,
                commit=True,
            )
        console.print(f"[green]✓ Étape 2/6 terminée en {format_duration(s.duration)}[/green]\n")
    else:
        console.print("[dim]=== 2/6 Diffusion Réseau des Rôles (ignorée via --skip-roles) ===[/dim]\n")
        timer.start_step("roles", "2/6 Diffusion Réseau des Rôles").finish(status="skipped")

    # 3. Rollups
    console.print("[bold blue]=== 3/6 Statistiques Agglomérées (Rollups Joueurs, Équipes, Clubs) ===[/bold blue]")
    with timer.step("rollups", "3/6 Statistiques Agglomérées (Rollups)", items_unit="catégories") as s:
        compute_rollups(saison=saison)
    console.print(f"[green]✓ Étape 3/6 terminée en {format_duration(s.duration)}[/green]\n")

    # 4. Geo
    console.print("[bold blue]=== 4/6 Agrégats Territoriaux & Géographiques ===[/bold blue]")
    with timer.step("geo", "4/6 Agrégats Territoriaux & Géographiques", items_unit="agrégats") as s:
        compute_geo(saison=saison)
    console.print(f"[green]✓ Étape 4/6 terminée en {format_duration(s.duration)}[/green]\n")

    # 5. Licences
    console.print("[bold blue]=== 5/6 Analyse du Cycle des Licences ===[/bold blue]")
    with timer.step("licences", "5/6 Analyse du Cycle des Licences", items_unit="licences") as s:
        compute_licences(saison=saison)
    console.print(f"[green]✓ Étape 5/6 terminée en {format_duration(s.duration)}[/green]\n")

    # 6. Palmarès
    console.print("[bold blue]=== 6/6 Statistiques Palmarès & Caches ===[/bold blue]")
    with timer.step("palmares", "6/6 Statistiques Palmarès & Caches", items_unit="combos") as s:
        compute_stats(saison=saison, force=force, clear=False)
    console.print(f"[green]✓ Étape 6/6 terminée en {format_duration(s.duration)}[/green]\n")

    timer.stop_pipeline()
    console.print(Panel(
        f"[bold green]Chaîne complète de calculs terminée avec succès en {format_duration(timer.total_duration)}[/bold green]",
        title="✅ Calculs Terminés",
    ))
    timer.display_summary(
        console,
        detail_level=timing_detail,
        title="⏱️ Récapitulatif de la Chaîne de Calculs",
    )

