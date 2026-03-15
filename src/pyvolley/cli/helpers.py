"""
Utilitaires partagés pour le CLI PyVolley.

Ce module centralise le code commun aux commandes CLI :
- Résolution des entités et saisons
- Index de fichiers PDF
- Barre de progression standard
- Filtres SQLAlchemy réutilisables
"""

from __future__ import annotations

import re
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

from pyvolley.shared.pdf_storage import (
    build_pdf_storage_path,
    extract_match_code_from_pdf_path,
)

console = Console()

_SAISON_RE = re.compile(r"^\s*(\d{2}|\d{4})\s*[-/]\s*(\d{2}|\d{4})\s*$")


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
        return expand_saison_inputs(saison)
    return expand_saison_inputs([scraper._get_current_saison()])


def _two_digits(year: int) -> str:
    """Retourne une année sur 2 chiffres (ex: 2024 -> 24)."""
    return f"{year % 100:02d}"


def _to_full_year(value: str) -> int:
    """Convertit un token année (YY ou YYYY) en année complète."""
    if len(value) == 4:
        return int(value)
    return 2000 + int(value)


def format_saison_short(saison_code: str) -> str:
    """Normalise une saison en format CLI court ``YY/YY``.

    Accepte ``YY/YY``, ``YYYY/YYYY`` et ``YYYY-YYYY``.
    """
    expanded = expand_saison_inputs([saison_code])
    if not expanded:
        raise ValueError("Saison invalide")
    start, end = expanded[0].split("/")
    return f"{_two_digits(int(start))}/{_two_digits(int(end))}"


def expand_saison_inputs(saisons: List[str]) -> list[str]:
    """Déplie des saisies CLI en saisons explicites ``YYYY/YYYY``.

    Exemples:
    - ``23/24``   -> ``["2023/2024"]``
    - ``22/25``   -> ``["2022/2023", "2023/2024", "2024/2025"]``
    - ``2023-2024`` -> ``["2023/2024"]``
    """
    expanded: list[str] = []
    seen: set[str] = set()

    for raw in saisons:
        token = (raw or "").strip()
        if not token:
            continue

        match = _SAISON_RE.match(token)
        if not match:
            raise ValueError(
                f"Format de saison invalide: '{raw}'. Utilisez YY/YY (ex: 23/24) ou une plage (ex: 22/25)."
            )

        start_year = _to_full_year(match.group(1))
        end_year = _to_full_year(match.group(2))

        if end_year <= start_year:
            raise ValueError(
                f"Plage de saison invalide: '{raw}'. La fin doit être supérieure au début."
            )

        for first_year in range(start_year, end_year):
            season = f"{first_year}/{first_year + 1}"
            if season not in seen:
                expanded.append(season)
                seen.add(season)

    return expanded


def saison_to_db_code(saison_code: str) -> str:
    """Convertit une saison CLI en format DB ``YYYY-YYYY``."""
    expanded = expand_saison_inputs([saison_code])
    if not expanded:
        raise ValueError(f"Saison invalide: '{saison_code}'")
    return expanded[0].replace("/", "-")


def saisons_to_db_codes(saisons: List[str]) -> list[str]:
    """Convertit une liste de saisons/plages CLI en codes DB uniques."""
    return [s.replace("/", "-") for s in expand_saison_inputs(saisons)]


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


def build_pdf_index(pdf_base_dir: Path) -> dict[tuple[Optional[str], str], Path]:
    """Construit un index {(saison, code_match): chemin} des PDFs locaux.

    La saison est déduite du premier niveau de dossier sous ``pdf_base_dir``
    (ex: ``data/pdfs/2024-2025/LIRA/EMA/EMA001.pdf`` → saison ``2024-2025``).

    Le format cible est ``data/pdfs/<saison>/<entite>/<poule>/<code_match>.pdf``.

    Indexe à la fois le nom complet du fichier (stem) et le code match extrait
    du chemin (compatibilité lecture). Si le nom contient un underscore
    (ancien format ``{entity}_{code}.pdf``), la partie après l'underscore
    est aussi indexée.

    Les PDFs sans dossier de saison (legacy) sont indexés avec ``saison=None``.
    """
    index: dict[tuple[Optional[str], str], Path] = {}
    if not pdf_base_dir.exists():
        return index

    for pdf_file in pdf_base_dir.glob("**/*.pdf"):
        rel = pdf_file.relative_to(pdf_base_dir)
        saison_code: Optional[str] = (
            rel.parts[0]
            if rel.parts and re.match(r"^\d{4}-\d{4}$", rel.parts[0])
            else None
        )
        stem = pdf_file.stem
        code_from_path = extract_match_code_from_pdf_path(pdf_file)

        index[(saison_code, stem)] = pdf_file
        index[(saison_code, code_from_path)] = pdf_file

        if "_" in stem:
            code_part = stem.split("_", 1)[1]
            key = (saison_code, code_part)
            if key not in index:
                index[key] = pdf_file

    return index


def find_pdf_for_match(
    match_db,
    pdf_base_dir: Path,
    pdf_index: dict[tuple[Optional[str], str], Path],
    saison_code: Optional[str] = None,
) -> Optional[Path]:
    """Localise le PDF d'un match en utilisant plusieurs stratégies.

    1. Chemin stocké en DB (source_pdf)
    2. Chemin structuré attendu (saison/entite/poule/code_match)
    3. Recherche par (saison, code_match) dans l'index
    4. Fallback legacy sans saison
    """
    code = match_db.code_match

    if saison_code is None:
        saison_obj = getattr(match_db, "saison", None)
        saison_code = getattr(saison_obj, "code", None)

    # 1. Chemin stocké en DB
    if match_db.source_pdf:
        p = Path(match_db.source_pdf)
        if p.exists():
            return p

    # 2. Chemin structuré attendu (nouveau format)
    if saison_code:
        comp = getattr(match_db, "competition", None)
        entite = getattr(getattr(comp, "entite", None), "code", None)
        poule = getattr(getattr(match_db, "poule", None), "code", None)
        journee = getattr(match_db, "journee", None)
        match_id = getattr(match_db, "id", None)
        expected = build_pdf_storage_path(
            pdf_base_dir,
            saison_code=saison_code,
            entite_code=entite,
            poule_code=poule,
            match_code=code,
            journee=journee,
            unique_hint=match_id,
        )
        if expected.exists():
            return expected

    # 2b. Chemin saison/codematch ancien format
    if saison_code:
        legacy_expected = pdf_base_dir / saison_code / f"{code}.pdf"
        if legacy_expected.exists():
            return legacy_expected

    # 3. Index saisonnier (couvre aussi les noms legacy {entity}_{code}.pdf)
    if saison_code:
        seasonal_key = (saison_code, code)
        if seasonal_key in pdf_index:
            return pdf_index[seasonal_key]

    # 4. Fallback legacy sans saison
    legacy_key = (None, code)
    if legacy_key in pdf_index:
        return pdf_index[legacy_key]

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

    normalized = saisons_to_db_codes(saison)
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
