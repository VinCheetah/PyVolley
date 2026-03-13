"""
Utilitaires partagés pour le CLI PyVolley.

Ce module centralise le code commun aux commandes CLI :
- Résolution des entités et saisons
- Index de fichiers PDF
- Barre de progression standard
- Filtres SQLAlchemy réutilisables
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, List

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich.table import Table

console = Console()


# ── Résolution des entités ──────────────────────────────────────────


def resolve_entities(
    scraper,
    *,
    entity: Optional[List[str]] = None,
    entity_type: Optional[str] = None,
    all_entities: bool = False,
    pro: bool = False,
) -> list[str]:
    """Résout les codes d'entités à partir des options CLI.

    Gère les cas : entités explicites, filtrage par type, --all, --pro.
    Retourne une liste de codes d'entités à traiter.
    """
    if pro:
        from pyvolley.scrapers.lnv import PRO_ENTITY_CODE
        if not entity:
            return [PRO_ENTITY_CODE]
        return list(entity)

    if all_entities:
        all_ents = scraper.get_entities()
        if entity_type:
            all_ents = [e for e in all_ents if e.type == entity_type.lower()]
        return [e.code for e in all_ents]

    if entity_type and not entity:
        all_ents = scraper.get_entities()
        return [e.code for e in all_ents if e.type == entity_type.lower()]

    if entity:
        return list(entity)

    return []


def resolve_saisons(
    scraper,
    saison: Optional[List[str]] = None,
) -> list[str]:
    """Résout les saisons à traiter.

    Si aucune saison spécifiée, retourne la saison courante.
    """
    if saison and len(saison) > 0:
        return list(saison)
    return [scraper._get_current_saison()]


def display_entities(scraper, console: Console) -> None:
    """Affiche les entités disponibles, groupées par type."""
    with console.status("[bold blue]Récupération des entités..."):
        entities = scraper.get_entities()

    nationales = [e for e in entities if e.type == "nationale"]
    ligues = [e for e in entities if e.type == "ligue"]
    comites = [e for e in entities if e.type == "comite"]

    for label, group in [
        ("Nationales", nationales),
        ("Ligues", ligues),
        ("Comités", comites),
    ]:
        if not group:
            continue
        console.print(f"\n[bold]{label} ({len(group)})[/bold]")
        table = Table(show_header=True)
        table.add_column("Code", style="cyan", width=12)
        table.add_column("Nom", style="white")
        for e in sorted(group, key=lambda x: x.code):
            table.add_row(e.code, e.nom)
        console.print(table)

    console.print(f"\n[green]Total: {len(entities)} entités[/green]")


# ── Index des PDFs locaux ───────────────────────────────────────────


def build_pdf_index(pdf_base_dir: Path) -> dict[str, Path]:
    """Construit un index {code_match: chemin} des PDFs locaux.

    Indexe à la fois le nom complet du fichier (stem) et, si le nom
    contient un underscore (ancien format ``{entity}_{code}.pdf``),
    la partie après l'underscore.
    """
    index: dict[str, Path] = {}
    if not pdf_base_dir.exists():
        return index

    for pdf_file in pdf_base_dir.glob("**/*.pdf"):
        stem = pdf_file.stem
        index[stem] = pdf_file
        if "_" in stem:
            code_part = stem.split("_", 1)[1]
            if code_part not in index:
                index[code_part] = pdf_file

    return index


def find_pdf_for_match(
    match_db,
    pdf_base_dir: Path,
    pdf_index: dict[str, Path],
) -> Optional[Path]:
    """Localise le PDF d'un match en utilisant plusieurs stratégies.

    1. Chemin stocké en DB (source_pdf)
    2. Recherche par code_match dans l'index
    """
    code = match_db.code_match

    # 1. Chemin stocké en DB
    if match_db.source_pdf:
        p = Path(match_db.source_pdf)
        if p.exists():
            return p

    # 2. Index rapide (couvre tous les formats)
    if code in pdf_index:
        return pdf_index[code]

    return None


# ── Filtres SQLAlchemy ──────────────────────────────────────────────


def add_saison_filter(session, stmt, saison: Optional[List[str]]):
    """Ajoute un filtre saison à une requête SQLAlchemy.

    Normalise les formats ``YYYY/YYYY`` → ``YYYY-YYYY``.
    Retourne le statement modifié et les IDs de saisons trouvées.
    """
    if not saison:
        return stmt, None

    from pyvolley.database.models import MatchDB, SaisonDB
    from sqlalchemy import select

    normalized = [s.replace("/", "-") for s in saison]
    saison_ids = [
        s.id for s in session.scalars(
            select(SaisonDB).where(SaisonDB.code.in_(normalized))
        ).all()
    ]
    if saison_ids:
        stmt = stmt.where(MatchDB.saison_id.in_(saison_ids))
        return stmt, saison_ids
    return stmt, []


def add_entity_filter(session, stmt, entity: Optional[List[str]]):
    """Ajoute un filtre entité à une requête SQLAlchemy (via compétition)."""
    if not entity:
        return stmt

    from pyvolley.database.models import MatchDB, EntiteFFVBDB, CompetitionDB
    from sqlalchemy import select

    entite_ids = [
        e.id for e in session.scalars(
            select(EntiteFFVBDB).where(EntiteFFVBDB.code.in_(entity))
        ).all()
    ]
    if entite_ids:
        comp_ids = [
            c.id for c in session.scalars(
                select(CompetitionDB).where(CompetitionDB.entite_id.in_(entite_ids))
            ).all()
        ]
        if comp_ids:
            stmt = stmt.where(MatchDB.competition_id.in_(comp_ids))

    return stmt


# ── Barre de progression ────────────────────────────────────────────


def make_progress(console: Console) -> Progress:
    """Crée une barre de progression Rich standardisée."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        "[",
        TextColumn("{task.completed}/{task.total}"),
        "]",
        TimeRemainingColumn(),
        console=console,
    )


# ── Utilitaires divers ─────────────────────────────────────────────


def sanitize_filename(name: str) -> str:
    """Nettoie un nom pour l'utiliser comme nom de fichier/dossier."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name[:100].strip()


def format_entities_display(entities: list[str], max_show: int = 5) -> str:
    """Formate une liste d'entités pour l'affichage."""
    display = ', '.join(entities[:max_show])
    if len(entities) > max_show:
        display += f"... (+{len(entities) - max_show})"
    return display
