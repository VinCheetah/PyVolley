"""Commandes de gestion du cycle de vie du pipeline (`status`, `cleanup`, `serve`, `simulate`, `stats`)."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, List

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pyvolley.cli.helpers import saisons_to_db_codes
from pyvolley.shared.pdf_storage import extract_match_code_from_pdf_path

console = Console()


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
        upcoming = total - played
        played_to_download = session.scalar(
            select(func.count()).select_from(
                base_filter.where(
                    MatchDB.parsing_status == "discovered",
                    MatchDB.match_joue == True,  # noqa: E712
                ).subquery()
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
            box=box.ROUNDED,
            border_style="dim",
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
        table.add_row("[dim]Matchs joués[/dim]", f"[dim]{played}[/dim]", f"[dim]{played / total * 100:.1f}%[/dim]" if total > 0 else "—")
        table.add_row("[dim]Matchs à venir[/dim]", f"[dim]{upcoming}[/dim]", f"[dim]{upcoming / total * 100:.1f}%[/dim]" if total > 0 else "—")
        table.add_row(
            "[dim]PDFs locaux[/dim]",
            f"[dim]{pdf_count}[/dim]",
            f"[dim]{pdf_display}[/dim]",
        )

        console.print(table)

        # Barre de progression (basée sur les matchs joués, les seuls éligibles au parsing)
        if played > 0:
            pct_played = status_counts["parsed"] / played * 100
            console.print(
                f"\n[bold]Progression (matchs joués) :[/bold] "
                f"[green]{'█' * int(pct_played // 2)}[/green]"
                f"[dim]{'░' * (50 - int(pct_played // 2))}[/dim] "
                f"[bold]{pct_played:.1f}%[/bold] ({status_counts['parsed']}/{played})"
            )
            if upcoming > 0:
                pct_total = status_counts["parsed"] / total * 100
                console.print(f"[dim]Total général (inclus {upcoming} matchs à venir) : {pct_total:.1f}%[/dim]")
        elif total > 0:
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

            detail = Table(
                show_header=True,
                box=box.ROUNDED,
                border_style="dim",
                header_style="bold cyan",
            )
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
        if played_to_download > 0:
            console.print(
                f"\n[yellow]💡 {played_to_download} match(s) joué(s) en attente de téléchargement → "
                f"pyvolley import --only download[/yellow]"
            )
        elif upcoming > 0 and status_counts["discovered"] > 0:
            console.print(
                f"\n[dim]ℹ {status_counts['discovered']} match(s) non parsé(s) dont {upcoming} match(s) à venir (aucun PDF disponible sur FFVB).[/dim]"
            )
        if status_counts["downloaded"] > 0:
            console.print(
                f"[yellow]💡 {status_counts['downloaded']} match(s) à parser → "
                f"pyvolley import --only parse[/yellow]"
            )
        if status_counts["error"] > 0:
            console.print(
                f"[yellow]💡 {status_counts['error']} match(s) en erreur → "
                f"pyvolley import --only parse[/yellow]"
            )


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


def find_pids_on_port(port: int) -> list[int]:
    """Retourne la liste des PIDs écoutant ou connectés sur le port spécifié."""
    pids: set[int] = set()
    current_pid = os.getpid()
    if sys.platform == "win32":
        try:
            res = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True)
            output = res.stdout.decode("latin-1", errors="replace")
            for line in output.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0].upper() == "TCP":
                    local_addr = parts[1]
                    if local_addr.endswith(f":{port}"):
                        try:
                            pid = int(parts[4])
                            if pid > 0 and pid != current_pid:
                                pids.add(pid)
                        except ValueError:
                            pass
        except Exception:
            pass
    else:
        try:
            res = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    if pid > 0 and pid != current_pid:
                        pids.add(pid)
        except Exception:
            pass
    return sorted(pids)


def find_pyvolley_serve_pids() -> list[int]:
    """Recherche tous les processus Python exécutant pyvolley serve ou web_app."""
    pids: set[int] = set()
    current_pid = os.getpid()
    parent_pid = os.getppid() if hasattr(os, "getppid") else 0
    excluded_pids = {current_pid, parent_pid, 0}

    # Match exclusif pour le serveur web pyvolley (évite kill_serve, kill-serve, etc.)
    pattern = re.compile(r"(?:(?<![_-])\bserve\b|pyvolley\.web\.app)", re.IGNORECASE)

    if sys.platform == "win32":
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' } | Select-Object ProcessId, CommandLine | ConvertTo-Json",
            ]
            res = subprocess.run(cmd, capture_output=True, timeout=5)
            raw = res.stdout.decode("utf-8", errors="replace").strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    pid = item.get("ProcessId")
                    cmdline = item.get("CommandLine") or ""
                    if not pid or pid in excluded_pids:
                        continue
                    if " -c " in cmdline or "kill-serve" in cmdline or "kill_serve" in cmdline:
                        continue
                    if "pyvolley" in cmdline.lower() and pattern.search(cmdline):
                        pids.add(pid)
        except Exception:
            pass
    else:
        try:
            res = subprocess.run(
                ["ps", "-eo", "pid,command"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in res.stdout.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and parts[0].isdigit():
                    pid = int(parts[0])
                    cmdline = parts[1]
                    if pid in excluded_pids:
                        continue
                    if " -c " in cmdline or "kill-serve" in cmdline or "kill_serve" in cmdline:
                        continue
                    if "python" in cmdline and "pyvolley" in cmdline.lower() and pattern.search(cmdline):
                        pids.add(pid)
        except Exception:
            pass
    return sorted(pids)


def kill_pids(pids: list[int], force: bool = True) -> list[int]:
    """Arrête les processus donnés (arborescence comprise sous Windows)."""
    killed: list[int] = []
    current_pid = os.getpid()
    parent_pid = os.getppid() if hasattr(os, "getppid") else 0
    excluded = {current_pid, parent_pid, 0}
    for pid in set(pids):
        if pid in excluded or pid <= 0:
            continue
        try:
            if sys.platform == "win32":
                args = ["taskkill"]
                if force:
                    args.append("/F")
                args.extend(["/T", "/PID", str(pid)])
                res = subprocess.run(args, capture_output=True)
                if res.returncode == 0:
                    killed.append(pid)
            else:
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.kill(pid, sig)
                killed.append(pid)
        except Exception:
            pass
    return sorted(killed)


def find_parent_pids(pids: list[int]) -> list[int]:
    """Trouve les processus parents des PIDs donnés."""
    parents: set[int] = set()
    current_pid = os.getpid()
    if sys.platform == "win32" and pids:
        try:
            pid_filter = " or ".join(f"ProcessId = {p}" for p in pids)
            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"Get-CimInstance Win32_Process -Filter '{pid_filter}' | Select-Object -ExpandProperty ParentProcessId",
            ]
            res = subprocess.run(cmd, capture_output=True, timeout=5)
            output = res.stdout.decode("latin-1", errors="replace")
            for line in output.splitlines():
                line = line.strip()
                if line.isdigit():
                    ppid = int(line)
                    if ppid > 0 and ppid != current_pid:
                        parents.add(ppid)
        except Exception:
            pass
    return sorted(parents)


def kill_active_serve(port: int = 8000, force: bool = True) -> list[int]:
    """Tue tous les processus actifs liés à pyvolley serve et/ou occupant le port."""
    pids_port = find_pids_on_port(port)
    pids_parents = find_parent_pids(pids_port)
    pids_cmd = find_pyvolley_serve_pids()
    target_pids = sorted(set(pids_port) | set(pids_parents) | set(pids_cmd))
    if not target_pids:
        return []
    killed = kill_pids(target_pids, force=force)
    time.sleep(0.3)
    return killed


def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Adresse d'écoute."),
    port: int = typer.Option(8000, "--port", "-p", help="Port d'écoute."),
    reload: bool = typer.Option(True, "--reload", "-r", help="Rechargement auto."),
    kill: bool = typer.Option(
        True,
        "--kill/--no-kill",
        help="Tuer tout processus pyvolley serve ou occupant le port avant de démarrer.",
    ),
):
    """🌐 Lance le serveur web."""
    import uvicorn

    if kill:
        killed = kill_active_serve(port=port)
        if killed:
            console.print(
                f"[yellow]⚠️ {len(killed)} processus actif(s) sur le port {port} arrêté(s) (PIDs: {', '.join(map(str, killed))})[/yellow]"
            )

    try:
        console.print(f"[blue]🏐 PyVolley sur http://{host}:{port}[/blue]")
    except UnicodeEncodeError:
        console.print(f"[blue]PyVolley sur http://{host}:{port}[/blue]")
    uvicorn.run("pyvolley.web.app:web_app", host=host, port=port, reload=reload)


def kill_serve(
    port: int = typer.Option(8000, "--port", "-p", help="Port d'écoute du serveur web."),
    force: bool = typer.Option(True, "--force/--no-force", "-f", help="Forcer l'arrêt immédiat."),
):
    """🛑 Arrête et tue les processus actifs du serveur PyVolley."""
    killed = kill_active_serve(port=port, force=force)
    if killed:
        console.print(
            f"[green]✓ {len(killed)} processus pyvolley serve arrêté(s) sur le port {port} (PIDs: {', '.join(map(str, killed))})[/green]"
        )
    else:
        console.print(f"[dim]Aucun processus actif trouvé sur le port {port}.[/dim]")



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



