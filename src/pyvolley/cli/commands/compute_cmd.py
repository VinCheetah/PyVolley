"""Commandes de calcul et d'actualisation des statistiques (`pyvolley compute-*` ou `pyvolley compute`)."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from pyvolley.cli.helpers import make_progress, saisons_to_db_codes

console = Console()


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

        console.print(
            f"\n[green]✓ {computed} calculées[/green] | "
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


@compute_app.command("rollups")
def compute_rollups(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Code de la saison (ex: 2025-2026)."
    ),
):
    """Calcule et génère les statistiques agglomérées (joueur-saison, équipes, carrières)."""
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
        console.print(f"[green][OK] {n_jms} lignes joueur_match_stats synchronisées.[/green]")

        console.print("[cyan][...] Calcul des statistiques joueur par saison...[/cyan]")
        n_js = service.compute_player_season_stats(saison_id=saison_id)
        console.print(f"[green][OK] {n_js} lignes stats_joueur_saison calculées.[/green]")

        console.print("[cyan][...] Calcul des bilans d'équipe par saison...[/cyan]")
        n_es = service.compute_team_season_stats(saison_id=saison_id)
        console.print(f"[green][OK] {n_es} lignes stats_equipe_saison calculées.[/green]")

        console.print("[cyan][...] Calcul des synthèses de carrière joueur...[/cyan]")
        n_jc = service.compute_player_career_stats()
        console.print(f"[green][OK] {n_jc} lignes stats_joueur_carriere calculées.[/green]")

    console.print(
        Panel(
            f"[bold green]Statistiques agglomérées générées avec succès ![/bold green]\n"
            f"- Stats Joueur/Match  : [bold]{n_jms}[/bold]\n"
            f"- Stats Joueur/Saison : [bold]{n_js}[/bold]\n"
            f"- Stats Equipe/Saison : [bold]{n_es}[/bold]\n"
            f"- Stats Carrière      : [bold]{n_jc}[/bold]",
            title="Bilan des Rollups",
        )
    )


@compute_app.command("all")
def compute_all(
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Code de la saison (ex: 23/24 ou 2025-2026)."
    ),
    force: bool = typer.Option(False, "--force", help="Forcer le recalcul complet."),
):
    """Exécute l'ensemble des calculs statistiques (joueurs, rollups, palmarès)."""
    console.print("[bold blue]=== 1/3 Statistiques Joueurs par Match ===[/bold blue]")
    compute_player_stats(saison=saison, force=force)

    console.print("\n[bold blue]=== 2/3 Statistiques Agglomérées (Rollups) ===[/bold blue]")
    compute_rollups(saison=saison)

    console.print("\n[bold blue]=== 3/3 Statistiques Palmarès ===[/bold blue]")
    compute_stats(saison=saison, force=force)
