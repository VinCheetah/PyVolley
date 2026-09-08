"""Sous-commandes de développement et benchmarks (`pyvolley dev`)."""

from __future__ import annotations

import glob
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
dev_app = typer.Typer(help="🛠️ Outils de développement et benchmarks")


@dev_app.command("compare")
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
        for p_arg in parsers:
            for piece in p_arg.split(","):
                piece = piece.strip().lower()
                if piece:
                    raw_parser_names.append(piece)

    if not raw_parser_names:
        available = ParserFactory.list_available()
        default_p = ["legacy", "zone", "fast"]
        raw_parser_names = [p for p in default_p if p in available]
        if len(raw_parser_names) < 2:
            raw_parser_names = available[:2]

    # Vérification et instanciation des parsers
    parser_instances = []
    for name in raw_parser_names:
        try:
            p_inst = ParserFactory.get(name)
            label = "Fast" if name.lower() == "fast" else ("Legacy" if name.lower() in ("legacy", "pdfplumber") else name.capitalize())
            parser_instances.append((label, p_inst))
        except (KeyError, ValueError):
            console.print(f"[red]Parser '{name}' non reconnu[/red]")
            raise typer.Exit(1)

    if len(parser_instances) < 1:
        console.print("[red]Veuillez spécifier au moins un parser valide à exécuter.[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold blue]Comparaison des Parsers PyVolley :[/bold blue] {', '.join([n for n, _ in parser_instances])}\n"
        f"[cyan]Fichiers PDF cibles :[/cyan] {len(pdf_files)}",
        title="Comparaison des Parsers PyVolley",
    ))

    # Métriques
    total_times: dict[str, float] = {name: 0.0 for name, _ in parser_instances}
    success_counts: dict[str, int] = {name: 0 for name, _ in parser_instances}
    field_matches: int = 0
    field_diffs: int = 0
    all_comparison_details: list[tuple[str, list[str], list[str]]] = []

    # Table de suivi
    table = Table(title="Résultats détaillés par fichier", show_header=True)
    table.add_column("Fichier", style="cyan", width=18)
    for label, _ in parser_instances:
        table.add_column(f"{label} (ms)", justify="right")
        table.add_column(f"{label} (Statut)", justify="center")
    if len(parser_instances) >= 2:
        table.add_column("Parité", justify="center", style="bold")

    for pdf_path_item in pdf_files:
        row = [pdf_path_item.name]
        results_by_parser = {}

        for label, inst in parser_instances:
            try:
                t0 = time.perf_counter()
                res = inst.parse(pdf_path_item)
                t1 = time.perf_counter()
                elapsed_ms = (t1 - t0) * 1000.0
                total_times[label] += elapsed_ms
                results_by_parser[label] = res

                if res.success and res.match:
                    success_counts[label] += 1
                    row.append(f"{elapsed_ms:.1f}")
                    row.append("[green]OK[/green]")
                else:
                    row.append(f"{elapsed_ms:.1f}")
                    row.append("[red]ERR[/red]")
            except Exception as e:
                results_by_parser[label] = None
                row.append("—")
                row.append(f"[red]EXC: {type(e).__name__}[/red]")

        # Comparaison de parité si au moins 2 parsers
        if len(parser_instances) >= 2:
            p1_name, _ = parser_instances[0]
            p2_name, _ = parser_instances[1]
            r1 = results_by_parser.get(p1_name)
            r2 = results_by_parser.get(p2_name)

            if r1 and r2 and r1.success and r2.success and r1.match and r2.match:
                m1, m2 = r1.match, r2.match
                m_diffs: list[str] = []
                m_matches: list[str] = []

                # En-tête / Métadonnées
                if (m1.code_match or "").strip() == (m2.code_match or "").strip():
                    m_matches.append(f"code_match: {m1.code_match}")
                else:
                    m_diffs.append(f"code_match: '{m1.code_match}' vs '{m2.code_match}'")

                if (m1.date or "") == (m2.date or ""):
                    m_matches.append(f"date: {m1.date}")
                else:
                    m_diffs.append(f"date: '{m1.date}' vs '{m2.date}'")

                if (m1.heure or "") == (m2.heure or ""):
                    m_matches.append(f"heure: {m1.heure}")
                else:
                    m_diffs.append(f"heure: '{m1.heure}' vs '{m2.heure}'")

                # Équipes et scores
                c1_a = normalize_club_name(m1.equipe_a.nom) if m1.equipe_a else ""
                c2_a = normalize_club_name(m2.equipe_a.nom) if m2.equipe_a else ""
                if c1_a == c2_a:
                    m_matches.append(f"equipe_a: {c1_a}")
                else:
                    m_diffs.append(f"equipe_a: '{m1.equipe_a.nom if m1.equipe_a else None}' vs '{m2.equipe_a.nom if m2.equipe_a else None}'")

                c1_b = normalize_club_name(m1.equipe_b.nom) if m1.equipe_b else ""
                c2_b = normalize_club_name(m2.equipe_b.nom) if m2.equipe_b else ""
                if c1_b == c2_b:
                    m_matches.append(f"equipe_b: {c1_b}")
                else:
                    m_diffs.append(f"equipe_b: '{m1.equipe_b.nom if m1.equipe_b else None}' vs '{m2.equipe_b.nom if m2.equipe_b else None}'")

                if (m1.score_final or "").strip() == (m2.score_final or "").strip():
                    m_matches.append(f"score_final: {m1.score_final}")
                else:
                    m_diffs.append(f"score_final: '{m1.score_final}' vs '{m2.score_final}'")

                if len(m1.sets or []) == len(m2.sets or []):
                    m_matches.append(f"sets_count: {len(m1.sets or [])}")
                else:
                    m_diffs.append(f"sets_count: {len(m1.sets or [])} vs {len(m2.sets or [])}")

                nb_j1 = len(m1.equipe_a.joueurs or []) + len(m1.equipe_b.joueurs or []) if m1.equipe_a and m1.equipe_b else 0
                nb_j2 = len(m2.equipe_a.joueurs or []) + len(m2.equipe_b.joueurs or []) if m2.equipe_a and m2.equipe_b else 0
                if nb_j1 == nb_j2:
                    m_matches.append(f"joueurs_total: {nb_j1}")
                else:
                    m_diffs.append(f"joueurs_total: {nb_j1} vs {nb_j2}")

                field_matches += len(m_matches)
                field_diffs += len(m_diffs)
                all_comparison_details.append((pdf_path_item.name, m_matches, m_diffs))

                if not m_diffs:
                    row.append("[green]✓ 100%[/green]")
                else:
                    row.append(f"[yellow]Δ {len(m_diffs)}[/yellow]")
            else:
                row.append("[dim]—[/dim]")

        table.add_row(*row)

    console.print(table)

    # Résumé
    total_matches = len(pdf_files)
    total_fields = field_matches + field_diffs
    parity_rate = (field_matches / total_fields * 100.0) if total_fields > 0 else 0.0

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
        console.print("\n[bold cyan]Détail exhaustif par fichier (-v activé) :[/bold cyan]")
        for fname, matches_list, diffs_list in all_comparison_details:
            console.print(f"\n[bold cyan]Fichier: {fname}[/bold cyan]")
            if matches_list:
                console.print(f"  [bold green]Champs Concordants ({len(matches_list)} champs) :[/bold green]")
                for m in matches_list:
                    console.print(f"     [green]+ {m}[/green]")
            if diffs_list:
                console.print(f"  [bold yellow]Différences Surlignées ({len(diffs_list)} écarts) :[/bold yellow]")
                for d in diffs_list:
                    console.print(f"     [bold yellow]- {d}[/bold yellow]")
            else:
                console.print("  [bold green]Aucune différence constatée (100% Identique)[/bold green]")


@dev_app.command("layout-editor")
def launch_layout_editor(
    pdf_path: Optional[Path] = typer.Argument(
        None, help="Chemin d'accès optionnel vers un fichier PDF de feuille de match"
    )
):
    """Lancer l'éditeur interactif de layout et inspecteur de parsing PDF (Dev Tool)."""
    console.print("[cyan]Lancement du Layout Editor & Inspector (GUI)...[/cyan]")
    script_path = Path(__file__).resolve().parent.parent.parent.parent.parent / "scripts" / "layout_editor.py"
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
            t_start = time.perf_counter_ns()
            parser.parse(pfile)
            t_end = time.perf_counter_ns()
            tot_full += (t_end - t_start) / 1e6

            t0 = time.perf_counter_ns()
            doc = pymupdf.open(pfile)
            page = doc[0]
            raw_words = page.get_text("words")
            sorted_words, y0_list = normalize_words(raw_words)
            image_info_list = page.get_image_info(hashes=True)
            captain_image_bboxes = [img["bbox"] for img in image_info_list if "bbox" in img]
            doc.close()
            t1 = time.perf_counter_ns()

            hdr = extract_fast_header(sorted_words, y0_list, DEFAULT_FFVB_LAYOUT, image_blocks=image_info_list)
            extract_fast_rosters(
                sorted_words, y0_list, DEFAULT_FFVB_LAYOUT,
                nom_gauche=hdr.nom_gauche, nom_droite=hdr.nom_droite,
                gauche_est_equipe_a=hdr.gauche_est_equipe_a,
                captain_image_bboxes=captain_image_bboxes
            )
            extract_fast_arbitres(sorted_words, y0_list, DEFAULT_FFVB_LAYOUT)
            res_data = extract_fast_resultats(sorted_words, y0_list, DEFAULT_FFVB_LAYOUT)
            extract_fast_sets(
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
