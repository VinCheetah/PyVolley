"""
Interface CLI principale pour PyVolley.

Point d'entrée modulaire orchestrant les commandes principales et les sous-applications :
- ``import``        : importer des données FFVB (scrape → download → parse)
- ``status``        : tableau de bord du pipeline d'import
- ``parse``         : analyser un PDF de feuille de match
- ``serve``         : lancer le serveur web
- ``simulate``      : visualiser un match en HTML interactif
- ``cleanup``       : nettoyer les PDFs locaux

Sous-applications :
- ``compute``       : calculs statistiques (all, players, rollups, palmares)
- ``audit``         : audits de qualité des données et de vraisemblance
- ``db``            : gestion, initialisation, migrations et exploration de la base de données
- ``dev``           : outils développeur et benchmarks parsers
- ``list``          : consultation FFVB en ligne (entités, poules, matchs)
- ``report``        : génération de rapports détaillés
- ``roles``         : inférence, diffusion réseau et audit des rôles
- ``sync``          : synchronisation des données externes (logos, etc.)
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

# Helpers exportés pour tests unitaires
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
    PipelineTimer,
    format_duration,
    format_rate,
)

# ── Sous-applications (Namespaces) ─────────────────────────────────────────
from pyvolley.cli.commands.list_cmd import list_app
from pyvolley.cli.commands.report_cmd import report_app
from pyvolley.cli.commands.roles_cmd import roles_app
from pyvolley.cli.commands.dev_cmd import dev_app
from pyvolley.cli.commands.compute_cmd import (
    compute_app,
    compute_stats,
    compute_player_stats,
    compute_rollups,
)
from pyvolley.cli.commands.db_cmd import db_app
from pyvolley.cli.commands.audit_cmd import audit_app
from pyvolley.cli.commands.sync_cmd import sync_app, sync_geocode
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
)
from pyvolley.cli.commands.parse_cmd import parse
from pyvolley.cli.plausibility_cli import apply_plausibility_core_to_match_db

# Enregistrement des sous-applications
app.add_typer(list_app, name="list")
app.add_typer(db_app, name="db")
app.add_typer(report_app, name="report")
app.add_typer(roles_app, name="roles")
app.add_typer(dev_app, name="dev")
app.add_typer(compute_app, name="compute")
app.add_typer(audit_app, name="audit")
app.add_typer(sync_app, name="sync")

# ── Commandes racines principales ──────────────────────────────────────────
app.command("import")(import_data)
app.command("status")(status)
app.command("parse")(parse)
app.command("serve")(serve)
app.command("simulate")(simulate)
app.command("cleanup")(cleanup)
app.command("geocode")(sync_geocode)


# Export interne pour compatibilité des tests existants
_apply_plausibility_core_to_match_db = apply_plausibility_core_to_match_db


def main():
    """Point d'entrée principal du CLI."""
    app()


if __name__ == "__main__":
    main()
