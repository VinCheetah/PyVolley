"""Interface CLI dédiée pour la gestion, l'inférence et la diffusion réseau des rôles joueurs."""

from __future__ import annotations

from collections import Counter
from typing import Optional, List

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from sqlalchemy import select, or_, and_, desc
from sqlalchemy.orm import selectinload

import time
from pyvolley.cli.helpers import (
    make_progress,
    saisons_to_db_codes,
    format_duration,
    format_rate,
)
from pyvolley.database.connection import get_db, init_db
from pyvolley.database.models import (
    JoueurDB,
    MatchDB,
    ParticipationMatchDB,
    SaisonDB,
    EntiteFFVBDB,
    CompetitionDB,
    JoueurMatchStatsDB,
    JoueurSaisonStatsDB,
    JoueurCarriereStatsDB,
)
from pyvolley.database.role_diffusion_service import RoleDiffusionService
from pyvolley.analysis.role_solver import (
    ROLE_LABELS,
    ALL_ROLES,
    extract_team_context,
    TeamRoleSolver,
)
from pyvolley.database.converters import match_db_to_core

roles_app = typer.Typer(
    name="roles",
    help="🧠 Outils d'inférence, diffusion réseau et audit des rôles joueurs.",
    no_args_is_help=True,
)
console = Console()


def _unwrap(val, default=None):
    """Déballe un paramètre Typer (OptionInfo) si la fonction est appelée directement en Python."""
    if hasattr(val, "default"):
        return val.default if val.default is not ... else default
    return val if val is not None else default


@roles_app.command("diffuse")
def diffuse_roles(
    iterations: int = typer.Option(
        3, "--iterations", "-i", help="Nombre maximal de passes de diffusion réseau (1-6)."
    ),
    saison: Optional[str] = typer.Option(
        None, "--saison", "-s", help="Restreindre aux matchs d'une saison (ex: 23/24)."
    ),
    entity: Optional[str] = typer.Option(
        None, "--entity", "-e", help="Restreindre à une entité FFVB (ex: ABCCS)."
    ),
    match_id: Optional[int] = typer.Option(
        None, "--match-id", help="Restreindre à un match spécifique (ID)."
    ),
    commit: bool = typer.Option(
        True, "--commit/--dry-run", help="Sauvegarder les résultats en base ou mode simulation."
    ),
):
    """🔄 Exécute la diffusion réseau multi-passes pour fiabiliser les rôles des joueurs.

    Propagera les certitudes entre coéquipiers (binômes en rotation, règles de composition)
    et stabilisera les rôles de chaque joueur sur l'ensemble de ses matchs.
    """
    iterations = int(_unwrap(iterations, 3))
    saison = _unwrap(saison)
    entity = _unwrap(entity)
    match_id = _unwrap(match_id)
    commit = bool(_unwrap(commit, True))

    init_db()

    with get_db() as session:
        saison_ids: Optional[list[int]] = None
        if saison:
            try:
                db_codes = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)
            s_objs = list(session.scalars(select(SaisonDB).where(SaisonDB.code.in_(db_codes))).all())
            if not s_objs:
                console.print(f"[yellow]Aucune saison trouvée pour '{saison}'[/yellow]")
                return
            saison_ids = [s.id for s in s_objs]

        competition_ids: Optional[list[int]] = None
        if entity:
            entite_db = session.scalars(
                select(EntiteFFVBDB).where(EntiteFFVBDB.code == entity.strip().upper())
            ).first()
            if not entite_db:
                console.print(f"[yellow]Entité '{entity}' non trouvée.[/yellow]")
                return
            competition_ids = [
                c.id for c in session.scalars(
                    select(CompetitionDB).where(CompetitionDB.entite_id == entite_db.id)
                ).all()
            ]

        match_ids_filter = [match_id] if match_id else None

        service = RoleDiffusionService(session)

        console.print(
            Panel(
                f"[bold cyan]Lancement de la diffusion réseau des rôles[/bold cyan]\n"
                f"• Passes max : [bold]{iterations}[/bold]\n"
                f"• Saison : [bold]{saison or 'Toutes'}[/bold]\n"
                f"• Entité : [bold]{entity or 'Toutes'}[/bold]\n"
                f"• Mode : [bold]{'Enregistrement en base' if commit else 'Dry-run (simulation)'}[/bold]",
                title="⚙️ Configuration",
            )
        )

        pass_durations: dict[int, float] = {}
        last_step: Optional[int] = None
        last_step_t: float = time.perf_counter()
        t_diffusion_start = time.perf_counter()

        with make_progress(console) as progress:
            task = progress.add_task("Diffusion des rôles...", total=iterations + 1)

            def progress_hook(step: int, total_steps: int, msg: str):
                nonlocal last_step, last_step_t
                now = time.perf_counter()
                if last_step is not None:
                    pass_durations[last_step] = now - last_step_t
                last_step = step
                last_step_t = now
                progress.update(task, completed=step, description=f"[cyan]{msg}[/cyan]")

            report = service.run_diffusion(
                saison_ids=saison_ids,
                competition_ids=competition_ids,
                match_ids=match_ids_filter,
                max_iterations=iterations,
                commit=commit,
                progress_callback=progress_hook,
            )
            now = time.perf_counter()
            if last_step is not None:
                pass_durations[last_step] = now - last_step_t
            progress.update(task, completed=iterations + 1, description="[green]✓ Terminé ![/green]")

        total_diffusion_duration = time.perf_counter() - t_diffusion_start

        if report.total_matches == 0:
            console.print("[yellow]Aucun match détaillé trouvé pour ces critères.[/yellow]")
            return

        # Tableau des itérations
        iter_table = Table(title="📈 Historique de convergence par passe")
        iter_table.add_column("Passe", justify="center", style="bold")
        iter_table.add_column("Rôles ajustés", justify="right", style="cyan")
        iter_table.add_column("Confiance moyenne", justify="right", style="green")
        iter_table.add_column("Haute confiance (≥70%)", justify="right", style="gold1")
        iter_table.add_column("Rôles d'exception (atypiques)", justify="right", style="magenta")
        iter_table.add_column("Durée", justify="right", style="cyan")

        for metric in report.iterations_history:
            d_sec = pass_durations.get(metric.iteration)
            d_str = format_duration(d_sec) if d_sec is not None else "—"
            iter_table.add_row(
                f"Passe {metric.iteration}" if metric.iteration > 0 else "Passe 0 (Locale)",
                str(metric.changed_roles_count) if metric.iteration > 0 else "—",
                f"{round(metric.average_confidence * 100, 1)}%",
                f"{metric.high_confidence_count} ({round(metric.high_confidence_count / max(1, report.total_player_matches) * 100, 1)}%)",
                str(metric.atypical_roles_count),
                d_str,
            )
        console.print(iter_table)

        # Tableau de distribution finale
        dist_table = Table(title="👥 Répartition finale des rôles")
        dist_table.add_column("Rôle", style="bold")
        dist_table.add_column("Nombre de matchs", justify="right", style="cyan")
        dist_table.add_column("Part", justify="right", style="green")

        total_roles = sum(report.final_role_distribution.values())
        for role_code in ALL_ROLES:
            count = report.final_role_distribution.get(role_code, 0)
            pct = round((count / max(1, total_roles)) * 100, 1)
            dist_table.add_row(ROLE_LABELS.get(role_code, role_code), str(count), f"{pct}%")

        unknown_count = report.final_role_distribution.get("INCONNU", 0)
        if unknown_count > 0:
            dist_table.add_row("Non déterminé", str(unknown_count), f"{round((unknown_count / max(1, total_roles)) * 100, 1)}%")

        console.print(dist_table)

        status_msg = (
            "[bold green]✓ Convergence atteinte avec succès ![/bold green]"
            if report.converged
            else "[bold yellow]Fin des itérations planifiées.[/bold yellow]"
        )
        rate_str = format_rate(report.total_matches, total_diffusion_duration, "m")
        console.print(
            Panel(
                f"{status_msg}\n"
                f"• Matchs traités : [bold]{report.total_matches}[/bold]\n"
                f"• Joueurs concernés : [bold]{report.total_players}[/bold]\n"
                f"• Participations évaluées : [bold]{report.total_player_matches}[/bold]\n"
                f"• Confiance moyenne finale : [bold green]{round(report.average_final_confidence * 100, 1)}%[/bold green]\n"
                f"• Changements de poste d'exception : [bold magenta]{report.atypical_match_roles}[/bold magenta]\n"
                f"• Durée totale : [bold]{format_duration(total_diffusion_duration)}[/bold] ({rate_str})",
                title="Bilan",
            )
        )


@roles_app.command("inspect")
def inspect_player_roles(
    joueur: str = typer.Argument(..., help="Numéro de licence, ID joueur ou nom partiel.")
):
    """🔍 Affiche le profil de rôle d'un joueur à travers sa Carrière, ses Saisons et ses Matchs."""
    init_db()

    with get_db() as session:
        # Trouver le joueur
        j_obj = None
        if joueur.isdigit():
            j_obj = session.get(JoueurDB, int(joueur))

        if not j_obj:
            j_obj = session.scalars(select(JoueurDB).where(JoueurDB.licence == joueur)).first()

        if not j_obj:
            j_obj = session.scalars(
                select(JoueurDB).where(
                    or_(
                        JoueurDB.nom.ilike(f"%{joueur}%"),
                        JoueurDB.prenom.ilike(f"%{joueur}%"),
                    )
                )
            ).first()

        if not j_obj:
            console.print(f"[red]Joueur '{joueur}' introuvable.[/red]")
            raise typer.Exit(1)

        # 1. Carrière
        career = session.scalars(
            select(JoueurCarriereStatsDB).where(JoueurCarriereStatsDB.joueur_id == j_obj.id)
        ).first()

        c_role = career.role_principal if career else None
        c_conf = career.role_confiance if career else 0.0
        c_dist = career.role_distribution if career else {}

        console.print(
            Panel(
                f"[bold cyan]{j_obj.prenom} {j_obj.nom}[/bold cyan] (Licence : {j_obj.licence or 'N/A'})\n"
                f"• Rôle Carrière : [bold]{ROLE_LABELS.get(c_role, c_role or 'Non déterminé')}[/bold] "
                f"([green]{round(c_conf * 100, 1)}% de confiance[/green])\n"
                f"• Matchs totaux : {career.total_matchs if career else 0} | Saisons : {career.saisons_count if career else 0}",
                title="👤 Profil Carrière",
            )
        )

        # 2. Saisons
        seasons_stmt = (
            select(JoueurSaisonStatsDB, SaisonDB)
            .join(SaisonDB, JoueurSaisonStatsDB.saison_id == SaisonDB.id)
            .where(JoueurSaisonStatsDB.joueur_id == j_obj.id)
            .order_by(desc(SaisonDB.code))
        )
        season_rows = session.execute(seasons_stmt).all()

        if season_rows:
            s_table = Table(title="📅 Historique par Saison")
            s_table.add_column("Saison", style="bold")
            s_table.add_column("Matchs", justify="right")
            s_table.add_column("Rôle principal", style="cyan")
            s_table.add_column("Confiance", justify="right", style="green")
            s_table.add_column("Fréquence / Distribution", style="dim")

            for sjs, s_db in season_rows:
                freq_str = ", ".join(
                    f"{ROLE_LABELS.get(r, r)}: {cnt}" for r, cnt in (sjs.roles_frequence or {}).items()
                )
                s_table.add_row(
                    s_db.code,
                    str(sjs.matchs_joues),
                    ROLE_LABELS.get(sjs.role_principal, sjs.role_principal or "—"),
                    f"{round(sjs.role_confiance * 100, 1)}%" if sjs.role_confiance else "—",
                    freq_str or "—",
                )
            console.print(s_table)

        # 3. Matchs détaillés récents
        match_stmt = (
            select(JoueurMatchStatsDB, MatchDB)
            .join(MatchDB, JoueurMatchStatsDB.match_id == MatchDB.id)
            .options(selectinload(MatchDB.equipe_a), selectinload(MatchDB.equipe_b))
            .where(JoueurMatchStatsDB.joueur_id == j_obj.id)
            .order_by(desc(MatchDB.date_match), desc(MatchDB.id))
            .limit(20)
        )
        match_rows = session.execute(match_stmt).all()

        if match_rows:
            m_table = Table(title="🏐 Derniers Matchs (Rôle & Confiance)")
            m_table.add_column("Date", style="dim")
            m_table.add_column("Match", style="white")
            m_table.add_column("Rôle inféré", style="bold cyan")
            m_table.add_column("Confiance", justify="right")
            m_table.add_column("Statut", justify="center")
            m_table.add_column("Indices clés", style="dim")

            for jms, m_db in match_rows:
                r_code = jms.role_principal
                conf = jms.role_confiance or 0.0
                hints = ", ".join((jms.indices_roles or [])[:2])

                # Détection changement de rôle ponctuel
                is_switch = False
                if c_role and r_code and r_code != c_role and conf >= 0.40:
                    is_switch = True

                conf_style = "green" if conf >= 0.70 else ("yellow" if conf >= 0.45 else "red")
                status_badge = "[bold magenta]⚠️ Exception[/bold magenta]" if is_switch else "[dim]Normal[/dim]"

                eq_a_name = m_db.equipe_a.nom if m_db.equipe_a else "Équipe A"
                eq_b_name = m_db.equipe_b.nom if m_db.equipe_b else "Équipe B"
                match_desc = f"#{m_db.id} ({eq_a_name} vs {eq_b_name})"
                date_str = m_db.date_match.strftime("%d/%m/%Y") if m_db.date_match else "—"

                m_table.add_row(
                    date_str,
                    match_desc,
                    ROLE_LABELS.get(r_code, r_code or "Non déterminé"),
                    f"[{conf_style}]{round(conf * 100, 1)}%[/{conf_style}]",
                    status_badge,
                    hints or "—",
                )
            console.print(m_table)


@roles_app.command("audit")
def audit_roles():
    """📊 Réalise un audit global de la fiabilité et de la couverture des rôles en base."""
    init_db()

    with get_db() as session:
        from sqlalchemy import func, case

        # Requête agrégée sur JoueurMatchStatsDB
        metrics = session.execute(
            select(
                func.count().label("total"),
                func.coalesce(func.avg(JoueurMatchStatsDB.role_confiance), 0.0).label("avg_conf"),
                func.count(case((JoueurMatchStatsDB.role_confiance >= 0.75, 1))).label("high"),
                func.count(
                    case(
                        (
                            and_(
                                JoueurMatchStatsDB.role_confiance >= 0.50,
                                JoueurMatchStatsDB.role_confiance < 0.75,
                            ),
                            1,
                        )
                    )
                ).label("mid"),
                func.count(
                    case(
                        (
                            or_(
                                JoueurMatchStatsDB.role_confiance < 0.50,
                                JoueurMatchStatsDB.role_confiance.is_(None),
                            ),
                            1,
                        )
                    )
                ).label("low"),
            )
        ).one()

        total_count = metrics.total
        if not total_count:
            console.print("[yellow]Aucune statistique joueur-match en base.[/yellow]")
            return

        conf_tiers = {"high": metrics.high, "mid": metrics.mid, "low": metrics.low}
        avg_conf = float(metrics.avg_conf)

        table = Table(title="📊 Audit global des rôles (Joueur-Match)")
        table.add_column("Métrique", style="bold")
        table.add_column("Valeur", justify="right", style="cyan")
        table.add_column("Pourcentage", justify="right", style="green")

        table.add_row("Total lignes de stats", str(total_count), "100.0%")
        table.add_row(
            "Confiance haute (≥75%)",
            str(conf_tiers["high"]),
            f"{round(conf_tiers['high'] / total_count * 100, 1)}%",
        )
        table.add_row(
            "Confiance moyenne (50-75%)",
            str(conf_tiers["mid"]),
            f"{round(conf_tiers['mid'] / total_count * 100, 1)}%",
        )
        table.add_row(
            "Confiance faible (<50%)",
            str(conf_tiers["low"]),
            f"{round(conf_tiers['low'] / total_count * 100, 1)}%",
        )
        table.add_row("Confiance moyenne globale", f"{round(avg_conf * 100, 1)}%", "—")

        console.print(table)

        # Répartition par rôle via GROUP BY SQL
        role_rows = session.execute(
            select(
                JoueurMatchStatsDB.role_principal,
                func.count(),
            ).group_by(JoueurMatchStatsDB.role_principal)
        ).all()
        roles_counter: dict[str, int] = {
            (r or "INCONNU"): count for r, count in role_rows
        }

        r_table = Table(title="🏐 Répartition par Rôle")
        r_table.add_column("Rôle", style="bold")
        r_table.add_column("Occurrences", justify="right", style="cyan")
        r_table.add_column("Part", justify="right", style="green")

        for role_code in ALL_ROLES:
            cnt = roles_counter.get(role_code, 0)
            r_table.add_row(ROLE_LABELS.get(role_code, role_code), str(cnt), f"{round(cnt / total_count * 100, 1)}%")

        unkn = roles_counter.get("INCONNU", 0)
        if unkn > 0:
            r_table.add_row("Non déterminé", str(unkn), f"{round(unkn / total_count * 100, 1)}%")

        console.print(r_table)


@roles_app.command("evaluate-match")
def evaluate_match_roles(
    match_id: int = typer.Argument(..., help="ID du match à analyser.")
):
    """🔬 Décompose l'inférence des rôles pour les deux équipes d'un match précis."""
    init_db()

    with get_db() as session:
        stmt = (
            select(MatchDB)
            .options(
                selectinload(MatchDB.participations).selectinload(ParticipationMatchDB.joueur),
                selectinload(MatchDB.sets),
            )
            .where(MatchDB.id == match_id)
        )
        match_db = session.scalars(stmt).first()
        if not match_db:
            console.print(f"[red]Match #{match_id} non trouvé.[/red]")
            raise typer.Exit(1)

        participants = list(match_db.participations or [])
        parts_a = [p for p in participants if p.equipe_id == match_db.equipe_a_id]
        parts_b = [p for p in participants if p.equipe_id == match_db.equipe_b_id]

        core_match = match_db_to_core(match_db, parts_a, parts_b)
        team_a_nom = core_match.equipe_a.nom if core_match.equipe_a else "Équipe A"
        team_b_nom = core_match.equipe_b.nom if core_match.equipe_b else "Équipe B"

        console.print(
            Panel(
                f"[bold cyan]Match #{match_id}[/bold cyan] : {team_a_nom} vs {team_b_nom}\n"
                f"Date : {match_db.date_match} | Sets : {len(core_match.sets)}",
                title="Détail du match",
            )
        )

        for side, team_nom, parts in [("A", team_a_nom, parts_a), ("B", team_b_nom, parts_b)]:
            ctx = extract_team_context(core_match, side)
            solver = TeamRoleSolver(ctx)
            results = solver.solve()

            t_table = Table(title=f"Équipe {side} : {team_nom}")
            t_table.add_column("N°", justify="center", style="bold")
            t_table.add_column("Joueur", style="white")
            t_table.add_column("Rôle inféré", style="bold cyan")
            t_table.add_column("Confiance", justify="right", style="green")
            t_table.add_column("Plausibles", style="dim")
            t_table.add_column("Indices explicatifs", style="dim")

            core_team = core_match.equipe(side)
            p_map = {
                str(j.numero or "").strip().lstrip("0") or "0": j
                for j in ((core_team.joueurs or []) + (core_team.liberos or []))
            } if core_team else {}

            for num, inf in results.items():
                p = p_map.get(num)
                name = f"{p.prenom} {p.nom}" if p else f"#{num}"
                plaus_str = ", ".join(ROLE_LABELS.get(r, r) for r in inf.roles_possibles)
                hints_str = "; ".join(inf.indices[:2])

                t_table.add_row(
                    num,
                    name,
                    ROLE_LABELS.get(inf.role_principal, inf.role_principal or "—"),
                    f"{round(inf.role_confiance * 100, 1)}%",
                    plaus_str,
                    hints_str or "—",
                )

            console.print(t_table)

            if ctx.rotation_pairs:
                pairs_str = ", ".join(f"#{p1} ↔ #{p2} ({cnt} sets)" for (p1, p2), cnt in ctx.rotation_pairs.items())
                console.print(f"[dim]Binômes opposés en rotation observés : {pairs_str}[/dim]\n")
