"""
Interface CLI principale pour PyVolley.

Point d'entrée modulaire orchestrant les commandes racines et les sous-applications :
- ``import``        : importer des données FFVB (scrape → download → parse)
- ``status``        : tableau de bord du pipeline
- ``list``          : sous-application de consultation FFVB en ligne (entités, poules, matchs)
- ``parse``         : analyser un PDF de feuille de match
- ``cleanup``       : nettoyer les PDFs locaux
- ``serve``         : lancer le serveur web
- ``simulate``      : visualiser un match en HTML interactif
- ``stats``         : statistiques globales de la base de données
- ``sync-logos``    : synchroniser les logos des clubs
- ``compute``       : sous-application de calculs statistiques (rollups, palmarès, joueurs)
- ``roles``         : sous-application d'inférence, diffusion réseau et audit des rôles
- ``audit``         : sous-application d'audits et de contrôles de vraisemblance
- ``db``            : sous-application de gestion et exploration de la base de données
- ``report``        : sous-application de génération de rapports détaillés
- ``dev``           : sous-application d'outils développeur et benchmarks
"""

from __future__ import annotations

import sys
import typer
from rich.console import Console

# Configuration console Windows UTF-8
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Application Typer racine
app = typer.Typer(
    name="pyvolley",
    help="PyVolley — Outils pour les données volleyball FFVB",
    add_completion=False,
)
console = Console()
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

# ── Sous-applications (Namespaces) ─────────────────────────────────────────
from pyvolley.cli.list_commands import list_app
from pyvolley.cli.reports import report_app
from pyvolley.cli.roles_cli import roles_app
from pyvolley.cli.commands.dev_cmd import dev_app, compare_parsers, launch_layout_editor
from pyvolley.cli.commands.compute_cmd import (
    compute_app,
    compute_stats,
    compute_player_stats,
    compute_rollups,
)
from pyvolley.cli.commands.db_cmd import db_app, init_database
from pyvolley.cli.commands.audit_cmd import audit_app, plausibility_audit
from pyvolley.cli.commands.import_cmd import (
    import_data,
    _is_local_pdf_usable,
    _get_pdf_redownload_reason,
    _import_dry_run,
    _import_scrape,
    _import_download,
    _import_parse,
    _import_stream,
    _cleanup_parsed_pdfs,
    _configure_parser_plausibility,
)
from pyvolley.cli.commands.pipeline_cmd import (
    status,
    cleanup,
    serve,
    simulate,
    stats,
)
from pyvolley.cli.commands.parse_cmd import parse
from pyvolley.cli.commands.sync_cmd import sync_logos
from pyvolley.cli.plausibility_cli import apply_plausibility_core_to_match_db

# Enregistrement des sous-applications
app.add_typer(list_app, name="list")
app.add_typer(db_app, name="db")
app.add_typer(report_app, name="report")
app.add_typer(roles_app, name="roles")
app.add_typer(dev_app, name="dev")
app.add_typer(compute_app, name="compute")
app.add_typer(audit_app, name="audit")

# ── Commandes racines (préservation intégrale de la rétrocompatibilité) ────
app.command("import")(import_data)
app.command("status")(status)
app.command("parse")(parse)
app.command("compare")(compare_parsers)
app.command("cleanup")(cleanup)
app.command("serve")(serve)
app.command("simulate")(simulate)
app.command("stats")(stats)
app.command("sync-logos")(sync_logos)
app.command("compute-stats")(compute_stats)
app.command("compute-player-stats")(compute_player_stats)
app.command("compute-rollups")(compute_rollups)
app.command("plausibility-audit")(plausibility_audit)
app.command("init")(init_database)
app.command("layout-editor")(launch_layout_editor)

# Alias rétrocompatibilité
_apply_plausibility_core_to_match_db = apply_plausibility_core_to_match_db


def main():
    """Point d'entrée principal du CLI."""
    app()


if __name__ == "__main__":
    main()
