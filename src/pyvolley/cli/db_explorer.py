"""
Commandes CLI pour explorer et interroger la base de données PyVolley.

Fournit un accès simplifié aux données : recherche, filtres,
affichage structuré, statistiques et exploration du schéma.
"""

from typing import Optional, List
from datetime import date

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
from rich.columns import Columns
from rich.text import Text
from rich import box

from sqlalchemy import inspect, func, select, or_, text

from pyvolley.cli.helpers import saisons_to_db_codes

console = Console()

explore_app = typer.Typer(
    name="explore",
    help="🔍 Explorer et interroger la base de données",
)


# ============== Helpers ==============

_db_initialized = False


def _init_quiet_db():
    """Initialise la DB silencieusement (sans logs SQL)."""
    global _db_initialized
    if _db_initialized:
        return
    import logging
    for name in ["sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine",
                 "sqlalchemy.pool", "sqlalchemy.dialects", "sqlalchemy.orm"]:
        logging.getLogger(name).setLevel(logging.WARNING)

    from pyvolley.database.connection import get_engine
    engine = get_engine()
    engine.echo = False
    _db_initialized = True


def _get_session():
    """Crée une session DB. Initialise si nécessaire."""
    _init_quiet_db()
    from pyvolley.database.connection import get_session_factory
    return get_session_factory()()


def _get_engine():
    """Récupère l'engine."""
    _init_quiet_db()
    from pyvolley.database.connection import get_engine
    return get_engine()


def _model_map():
    """Retourne un mapping nom_table -> modèle SQLAlchemy."""
    from pyvolley.database.models import (
        SaisonDB, ClubDB, ClubAliasDB, EquipeDB, JoueurDB, CompetitionDB,
        PouleDB, EntiteFFVBDB, OfficielMatchDB,
        MatchDB, SetDB, FormationDB, ChangementDB, TimeoutDB,
        ArbitreDB, ArbitreMatchDB, SanctionDB,
        ParticipationMatchDB,
    )
    return {
        "saisons": SaisonDB,
        "entites_ffvb": EntiteFFVBDB,
        "clubs": ClubDB,
        "club_aliases": ClubAliasDB,
        "equipes": EquipeDB,
        "joueurs": JoueurDB,
        "competitions": CompetitionDB,
        "poules": PouleDB,
        "matchs": MatchDB,
        "sets": SetDB,
        "formations": FormationDB,
        "changements": ChangementDB,
        "timeouts": TimeoutDB,
        "arbitres": ArbitreDB,
        "arbitre_match": ArbitreMatchDB,
        "sanctions": SanctionDB,
        "participations_match": ParticipationMatchDB,
        "officiels_match": OfficielMatchDB,
    }


def _table_aliases():
    """Alias courts pour les noms de tables."""
    return {
        "saison": "saisons",
        "club": "clubs",
        "alias": "club_aliases",
        "equipe": "equipes",
        "joueur": "joueurs",
        "competition": "competitions",
        "poule": "poules",
        "entite": "entites_ffvb",
        "match": "matchs",
        "set": "sets",
        "formation": "formations",
        "changement": "changements",
        "timeout": "timeouts",
        "arbitre": "arbitres",
        "sanction": "sanctions",
        "participation": "participations_match",
        "officiel": "officiels_match",
    }


def _resolve_table(name: str) -> str:
    """Résout un nom de table (avec alias)."""
    aliases = _table_aliases()
    return aliases.get(name.lower(), name.lower())


def _format_value(val, max_len: int = 50) -> str:
    """Formate une valeur pour l'affichage."""
    if val is None:
        return "[dim]NULL[/dim]"
    s = str(val)
    if len(s) > max_len:
        return s[:max_len - 3] + "..."
    return s


# ============== Commande: schema ==============

@explore_app.command("schema")
def schema(
    table: Optional[str] = typer.Argument(
        None, help="Nom de la table (optionnel, affiche toutes si omis)"
    ),
):
    """
    🏗️ Affiche la structure de la base de données (tables, colonnes, types).
    
    Exemples:
        pyvolley db explore schema
        pyvolley db explore schema matchs
        pyvolley db explore schema joueur
    """
    engine = _get_engine()
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if not tables:
        console.print("[yellow]Aucune table trouvée dans la base de données[/yellow]")
        return

    if table:
        table_name = _resolve_table(table)
        if table_name not in tables:
            console.print(f"[red]Table '{table_name}' introuvable.[/red]")
            console.print(f"[blue]Tables disponibles: {', '.join(sorted(tables))}[/blue]")
            return
        _show_table_schema(inspector, table_name)
    else:
        # Vue d'ensemble : arbre de toutes les tables
        tree = Tree("🗄️ [bold]Base de données PyVolley[/bold]")

        session = _get_session()
        try:
            for t in sorted(tables):
                columns = inspector.get_columns(t)
                count = session.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
                
                count_style = "green" if count > 0 else "dim"
                branch = tree.add(
                    f"[cyan]{t}[/cyan]  [bold {count_style}]({count} lignes)[/bold {count_style}]"
                )
                for col in columns:
                    pk = " 🔑" if col.get("primary_key") or col["name"] == "id" else ""
                    nullable = "" if col.get("nullable", True) else " [red]*[/red]"
                    branch.add(
                        f"[white]{col['name']}[/white] "
                        f"[dim]{col['type']}[/dim]{pk}{nullable}"
                    )
        finally:
            session.close()

        console.print(tree)


def _show_table_schema(inspector, table_name: str):
    """Affiche le schéma détaillé d'une table."""
    columns = inspector.get_columns(table_name)
    pk_cols = inspector.get_pk_constraint(table_name)
    fks = inspector.get_foreign_keys(table_name)
    indexes = inspector.get_indexes(table_name)
    uniques = inspector.get_unique_constraints(table_name)

    pk_names = set(pk_cols.get("constrained_columns", []))
    fk_map = {}
    for fk in fks:
        for col in fk["constrained_columns"]:
            ref = f"{fk['referred_table']}.{fk['referred_columns'][0]}"
            fk_map[col] = ref

    session = _get_session()
    try:
        count = session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
    finally:
        session.close()

    table = Table(
        title=f"🏗️ Table: {table_name}  ({count} lignes)",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("Colonne", style="cyan", no_wrap=True)
    table.add_column("Type", style="yellow")
    table.add_column("PK", justify="center", width=4)
    table.add_column("Nullable", justify="center", width=8)
    table.add_column("FK → Réf.", style="magenta")

    for col in columns:
        is_pk = "🔑" if col["name"] in pk_names else ""
        nullable = "✓" if col.get("nullable", True) else "[red]✗[/red]"
        fk_ref = fk_map.get(col["name"], "")
        table.add_row(
            col["name"],
            str(col["type"]),
            is_pk,
            nullable,
            fk_ref,
        )

    console.print(table)

    # Indexes
    if indexes:
        idx_table = Table(title="📇 Index", box=box.SIMPLE)
        idx_table.add_column("Nom", style="cyan")
        idx_table.add_column("Colonnes", style="white")
        idx_table.add_column("Unique", justify="center", width=8)
        for idx in indexes:
            idx_table.add_row(
                idx["name"],
                ", ".join(idx["column_names"]),
                "✓" if idx.get("unique") else "",
            )
        console.print(idx_table)

    # Unique constraints
    if uniques:
        uq_table = Table(title="🔒 Contraintes d'unicité", box=box.SIMPLE)
        uq_table.add_column("Nom", style="cyan")
        uq_table.add_column("Colonnes", style="white")
        for uq in uniques:
            uq_table.add_row(uq["name"], ", ".join(uq["column_names"]))
        console.print(uq_table)


# ============== Commande: tables ==============

@explore_app.command("tables")
def tables():
    """
    📋 Liste toutes les tables avec le nombre de lignes.
    
    Exemple:
        pyvolley db explore tables
    """
    engine = _get_engine()
    inspector = inspect(engine)
    table_names = sorted(inspector.get_table_names())

    if not table_names:
        console.print("[yellow]Aucune table trouvée[/yellow]")
        return

    session = _get_session()
    try:
        tbl = Table(title="📋 Tables de la base de données", box=box.ROUNDED)
        tbl.add_column("#", justify="right", style="dim", width=4)
        tbl.add_column("Table", style="cyan", min_width=25)
        tbl.add_column("Lignes", justify="right", style="green", min_width=10)
        tbl.add_column("Colonnes", justify="right", style="yellow", min_width=10)

        total_rows = 0
        for i, t in enumerate(table_names, 1):
            count = session.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
            col_count = len(inspector.get_columns(t))
            total_rows += count
            
            count_str = f"{count:,}".replace(",", " ")
            tbl.add_row(str(i), t, count_str, str(col_count))

        tbl.add_section()
        tbl.add_row("", "[bold]Total[/bold]", f"[bold]{total_rows:,}".replace(",", " ") + "[/bold]", "")

        console.print(tbl)
    finally:
        session.close()


# ============== Commande: show ==============

@explore_app.command("show")
def show(
    table: str = typer.Argument(..., help="Nom de la table (ex: matchs, joueurs, clubs)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Nombre de lignes à afficher"),
    offset: int = typer.Option(0, "--offset", "--skip", help="Nombre de lignes à sauter"),
    sort: Optional[str] = typer.Option(None, "--sort", "-s", help="Colonne de tri"),
    desc: bool = typer.Option(False, "--desc", "-d", help="Tri décroissant"),
    columns: Optional[str] = typer.Option(
        None, "--columns", "-c",
        help="Colonnes à afficher (séparées par des virgules)"
    ),
    where: Optional[str] = typer.Option(
        None, "--where", "-w",
        help="Filtre SQL simplifié (ex: 'nom LIKE %%Paris%%' ou 'id > 10')"
    ),
):
    """
    👁️ Affiche le contenu d'une table avec pagination et filtres.
    
    Exemples:
        pyvolley db explore show matchs
        pyvolley db explore show joueurs -n 50 --sort nom
        pyvolley db explore show clubs --where "ligue = 'LIFL'"
        pyvolley db explore show matchs -c code_match,score_final,date_match --sort date_match -d
    """
    table_name = _resolve_table(table)
    engine = _get_engine()
    inspector = inspect(engine)

    all_tables = inspector.get_table_names()
    if table_name not in all_tables:
        console.print(f"[red]Table '{table_name}' introuvable.[/red]")
        console.print(f"[blue]Tables: {', '.join(sorted(all_tables))}[/blue]")
        return

    all_columns = [c["name"] for c in inspector.get_columns(table_name)]

    # Sélection des colonnes
    if columns:
        selected_cols = [c.strip() for c in columns.split(",")]
        invalid = [c for c in selected_cols if c not in all_columns]
        if invalid:
            console.print(f"[red]Colonnes invalides: {', '.join(invalid)}[/red]")
            console.print(f"[blue]Colonnes disponibles: {', '.join(all_columns)}[/blue]")
            return
    else:
        selected_cols = all_columns

    # Construire la requête
    cols_sql = ", ".join(f'"{c}"' for c in selected_cols)
    query = f'SELECT {cols_sql} FROM "{table_name}"'

    if where:
        query += f" WHERE {where}"

    if sort:
        if sort not in all_columns:
            console.print(f"[red]Colonne de tri '{sort}' invalide[/red]")
            return
        query += f' ORDER BY "{sort}"'
        if desc:
            query += " DESC"
    elif "id" in all_columns:
        query += ' ORDER BY "id"'

    # Compter le total
    count_query = f'SELECT COUNT(*) FROM "{table_name}"'
    if where:
        count_query += f" WHERE {where}"

    query += f" LIMIT {limit} OFFSET {offset}"

    session = _get_session()
    try:
        total = session.execute(text(count_query)).scalar()
        rows = session.execute(text(query)).fetchall()

        if not rows:
            console.print(f"[yellow]Aucune donnée dans '{table_name}'[/yellow]")
            if where:
                console.print(f"[dim]Filtre appliqué: {where}[/dim]")
            return

        # Construire le tableau
        page_info = f"lignes {offset + 1}-{offset + len(rows)} sur {total}"
        tbl = Table(
            title=f"👁️ {table_name}  ({page_info})",
            box=box.ROUNDED,
            show_lines=False,
            row_styles=["", "dim"],
        )

        for col_name in selected_cols:
            style = "cyan" if col_name == "id" else "white"
            tbl.add_column(col_name, style=style, overflow="ellipsis", max_width=40)

        for row in rows:
            tbl.add_row(*[_format_value(v) for v in row])

        console.print(tbl)

        # Info pagination
        if total > offset + limit:
            remaining = total - offset - limit
            next_cmd = f"pyvolley db explore show {table} -n {limit} --skip {offset + limit}"
            console.print(
                f"\n[dim]{remaining} lignes restantes. "
                f"Suite: [cyan]{next_cmd}[/cyan][/dim]"
            )
    finally:
        session.close()


# ============== Commande: count ==============

@explore_app.command("count")
def count():
    """
    🔢 Affiche un résumé des quantités de données par table.
    
    Exemple:
        pyvolley db explore count
    """
    engine = _get_engine()
    inspector = inspect(engine)
    table_names = sorted(inspector.get_table_names())

    session = _get_session()
    try:
        panels = []
        total = 0
        for t in table_names:
            c = session.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
            total += c
            color = "green" if c > 0 else "dim"
            bar_len = min(c // 10, 40) if c > 0 else 0
            bar = "█" * bar_len
            panels.append(f"[cyan]{t:<25}[/cyan] [{color}]{c:>8,}[/{color}]  [{color}]{bar}[/{color}]".replace(",", " "))

        console.print(Panel(
            "\n".join(panels) + f"\n\n[bold]Total: {total:,} enregistrements[/bold]".replace(",", " "),
            title="🔢 Quantité de données",
            border_style="blue",
        ))
    finally:
        session.close()


# ============== Commande: matchs ==============

@explore_app.command("matchs")
def search_matchs(
    query: Optional[str] = typer.Argument(None, help="Recherche libre (code, équipe, lieu...)"),
    saison: Optional[str] = typer.Option(None, "--saison", "-s", help="Filtrer par saison (ex: 23/24 ou plage 22/25)"),
    equipe: Optional[str] = typer.Option(None, "--equipe", "-e", help="Filtrer par nom d'équipe"),
    competition: Optional[str] = typer.Option(None, "--competition", "-c", help="Filtrer par compétition"),
    date_debut: Optional[str] = typer.Option(None, "--from", help="Date min (YYYY-MM-DD)"),
    date_fin: Optional[str] = typer.Option(None, "--to", help="Date max (YYYY-MM-DD)"),
    score: Optional[str] = typer.Option(None, "--score", help="Filtrer par score (ex: 3-0, 3-2)"),
    limit: int = typer.Option(30, "--limit", "-n", help="Nombre max de résultats"),
    detail: bool = typer.Option(False, "--detail", "-d", help="Afficher plus de colonnes"),
):
    """
    🏐 Recherche et liste les matchs avec filtres multiples.
    
    Exemples:
        pyvolley db explore matchs
        pyvolley db explore matchs "Paris"
        pyvolley db explore matchs --saison 23/24 --score 3-0
        pyvolley db explore matchs -e "Nantes" --from 2025-01-01
        pyvolley db explore matchs -c PMA -n 50
    """
    from pyvolley.database.models import MatchDB, EquipeDB, CompetitionDB, SaisonDB

    session = _get_session()
    try:
        stmt = (
            select(MatchDB)
            .outerjoin(EquipeDB, MatchDB.equipe_a_id == EquipeDB.id)
            .outerjoin(CompetitionDB, MatchDB.competition_id == CompetitionDB.id)
            .outerjoin(SaisonDB, MatchDB.saison_id == SaisonDB.id)
        )

        # Filtres
        conditions = []

        if query:
            pattern = f"%{query}%"
            # Alias pour equipe_b
            from sqlalchemy.orm import aliased
            equipe_b_alias = aliased(EquipeDB)
            stmt = stmt.outerjoin(equipe_b_alias, MatchDB.equipe_b_id == equipe_b_alias.id)
            conditions.append(
                or_(
                    MatchDB.code_match.ilike(pattern),
                    MatchDB.salle.ilike(pattern),
                    MatchDB.vainqueur.ilike(pattern),
                    EquipeDB.nom.ilike(pattern),
                    equipe_b_alias.nom.ilike(pattern),
                )
            )

        if saison:
            try:
                saison_codes = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)
            conditions.append(SaisonDB.code.in_(saison_codes))

        if equipe:
            pattern = f"%{equipe}%"
            from sqlalchemy.orm import aliased
            if not query:
                equipe_b_alias = aliased(EquipeDB)
                stmt = stmt.outerjoin(equipe_b_alias, MatchDB.equipe_b_id == equipe_b_alias.id)
            conditions.append(
                or_(
                    EquipeDB.nom.ilike(pattern),
                    equipe_b_alias.nom.ilike(pattern),
                )
            )

        if competition:
            conditions.append(
                or_(
                    CompetitionDB.code_competition.ilike(f"%{competition}%"),
                    CompetitionDB.nom.ilike(f"%{competition}%"),
                )
            )

        if date_debut:
            conditions.append(MatchDB.date_match >= date_debut)

        if date_fin:
            conditions.append(MatchDB.date_match <= date_fin)

        if score:
            conditions.append(MatchDB.score_sets == score)

        if conditions:
            stmt = stmt.where(*conditions)

        stmt = stmt.order_by(MatchDB.date_match.desc().nullslast(), MatchDB.id.desc()).limit(limit)
        matchs = list(session.scalars(stmt))

        if not matchs:
            console.print("[yellow]Aucun match trouvé avec ces critères[/yellow]")
            return

        # Affichage
        tbl = Table(
            title=f"🏐 Matchs ({len(matchs)} résultat{'s' if len(matchs) > 1 else ''})",
            box=box.ROUNDED,
            row_styles=["", "dim"],
        )
        tbl.add_column("ID", style="dim", width=5, justify="right")
        tbl.add_column("Code", style="cyan", no_wrap=True)
        tbl.add_column("Date", style="yellow", width=12)
        tbl.add_column("Équipe A", style="white", min_width=20, max_width=30, overflow="ellipsis")
        tbl.add_column("Score", style="bold green", justify="center", width=7)
        tbl.add_column("Équipe B", style="white", min_width=20, max_width=30, overflow="ellipsis")
        if detail:
            tbl.add_column("Compét.", style="magenta", max_width=12, overflow="ellipsis")
            tbl.add_column("Salle", style="dim", max_width=20, overflow="ellipsis")
            tbl.add_column("Durée", style="dim", width=6)

        for m in matchs:
            equipe_a_nom = m.equipe_a.nom if m.equipe_a else "-"
            equipe_b_nom = m.equipe_b.nom if m.equipe_b else "-"
            date_str = str(m.date_match) if m.date_match else "-"
            score_str = m.score_sets or "-"
            comp_code = m.competition.code_competition if m.competition else "-"

            row = [
                str(m.id), m.code_match, date_str,
                equipe_a_nom, score_str, equipe_b_nom,
            ]
            if detail:
                row.extend([comp_code, m.salle or "-", m.duree_totale or "-"])
            tbl.add_row(*row)

        console.print(tbl)
    finally:
        session.close()


# ============== Commande: match (détail) ==============

@explore_app.command("match")
def match_detail(
    match_id: str = typer.Argument(..., help="ID ou code du match"),
):
    """
    📋 Affiche les détails complets d'un match.
    
    Exemples:
        pyvolley db explore match 42
        pyvolley db explore match PMAA001
    """
    from pyvolley.database.models import MatchDB

    session = _get_session()
    try:
        # Chercher par ID ou code
        if match_id.isdigit():
            match = session.get(MatchDB, int(match_id))
        else:
            stmt = select(MatchDB).where(MatchDB.code_match == match_id)
            match = session.scalar(stmt)

        if not match:
            console.print(f"[red]Match '{match_id}' introuvable[/red]")
            return

        # Infos générales
        eq_a = match.equipe_a.nom if match.equipe_a else "?"
        eq_b = match.equipe_b.nom if match.equipe_b else "?"
        date_str = str(match.date_match) if match.date_match else "?"
        heure_str = str(match.heure_match) if match.heure_match else "?"

        console.print(Panel(
            f"[bold cyan]{match.code_match}[/bold cyan]\n\n"
            f"[bold]{eq_a}[/bold]  [bold green]{match.score_sets or '? - ?'}[/bold green]  [bold]{eq_b}[/bold]\n\n"
            f"📅 Date: {date_str}  🕐 Heure: {heure_str}\n"
            f"📍 Salle: {match.salle or '?'}\n"
            f"🏆 Compétition: {match.competition.nom if match.competition else '?'} ({match.competition.code_competition if match.competition else '?'})\n"
            f"📅 Saison: {match.saison.code if match.saison else '?'}\n"
            f"📆 Journée: {match.journee or '?'}\n"
            f"🏆 Vainqueur: {match.vainqueur or '?'}\n"
            f"⏱️ Durée: {match.duree_totale or '?'}",
            title="🏐 Détails du match",
            border_style="blue",
        ))

        # Sets
        if match.sets:
            sets_tbl = Table(title="📊 Sets", box=box.SIMPLE)
            sets_tbl.add_column("Set", justify="center", style="cyan", width=5)
            sets_tbl.add_column(eq_a[:20], justify="center", style="white", width=10)
            sets_tbl.add_column(eq_b[:20], justify="center", style="white", width=10)
            sets_tbl.add_column("Durée", justify="center", style="dim", width=8)
            sets_tbl.add_column("Service", justify="center", style="dim", width=8)

            for s in match.sets:
                dur = f"{s.duree_minutes}min" if s.duree_minutes else "-"
                sets_tbl.add_row(
                    str(s.numero),
                    str(s.score_a) if s.score_a is not None else "-",
                    str(s.score_b) if s.score_b is not None else "-",
                    dur,
                    s.service_initial or "-",
                )
            console.print(sets_tbl)

        # Joueurs
        if match.participations:
            for side, equipe_id, equipe_nom in [
                ("A", match.equipe_a_id, eq_a),
                ("B", match.equipe_b_id, eq_b),
            ]:
                participants = [
                    p for p in match.participations if p.equipe_id == equipe_id
                ]
                if not participants:
                    continue

                p_tbl = Table(
                    title=f"👥 {equipe_nom}",
                    box=box.SIMPLE,
                )
                p_tbl.add_column("N°", justify="center", width=4)
                p_tbl.add_column("Nom", style="white", min_width=15)
                p_tbl.add_column("Prénom", style="white", min_width=10)
                p_tbl.add_column("Licence", style="dim", width=12)
                p_tbl.add_column("Rôle", style="cyan", width=12)

                for p in sorted(participants, key=lambda x: x.numero_maillot or "99"):
                    roles = []
                    if p.est_capitaine:
                        roles.append("C")
                    if p.est_libero:
                        roles.append("L")
                    role_str = " ".join(roles) or "-"

                    p_tbl.add_row(
                        p.numero_maillot or "-",
                        p.joueur.nom if p.joueur else "-",
                        p.joueur.prenom if p.joueur else "-",
                        p.joueur.licence if p.joueur else "-",
                        role_str,
                    )
                console.print(p_tbl)

        # Arbitres
        if match.arbitrages:
            arb_tbl = Table(title="🧑‍⚖️ Arbitres", box=box.SIMPLE)
            arb_tbl.add_column("Rôle", style="cyan", width=12)
            arb_tbl.add_column("Nom", style="white")
            arb_tbl.add_column("Licence", style="dim", width=12)
            for a in match.arbitrages:
                arb_tbl.add_row(
                    a.role,
                    a.arbitre.nom_complet if a.arbitre else "-",
                    a.arbitre.licence if a.arbitre else "-",
                )
            console.print(arb_tbl)

        # Sanctions
        if match.sanctions:
            san_tbl = Table(title="🟨 Sanctions", box=box.SIMPLE)
            san_tbl.add_column("Type", justify="center", width=6)
            san_tbl.add_column("Set", justify="center", width=5)
            san_tbl.add_column("Équipe", justify="center", width=8)
            san_tbl.add_column("N° Joueur", justify="center", width=10)
            san_tbl.add_column("Score", justify="center", width=8)
            for s in match.sanctions:
                score = f"{s.score_a}-{s.score_b}" if s.score_a is not None else "-"
                san_tbl.add_row(
                    s.type_sanction, str(s.set_numero),
                    s.equipe, s.joueur_numero or "-", score,
                )
            console.print(san_tbl)

        # Métadonnées
        console.print(Panel(
            f"Source PDF: {match.source_pdf or '?'}\n"
            f"Parsé le: {match.parsed_at or '?'}\n"
            f"Créé le: {match.created_at}\n"
            f"MàJ le: {match.updated_at}\n"
            f"Remarques: {match.remarques or '-'}",
            title="ℹ️ Métadonnées",
            border_style="dim",
        ))
    finally:
        session.close()


# ============== Commande: joueurs ==============

@explore_app.command("joueurs")
def search_joueurs(
    query: Optional[str] = typer.Argument(None, help="Recherche par nom, prénom ou licence"),
    equipe: Optional[str] = typer.Option(None, "--equipe", "-e", help="Filtrer par équipe"),
    club: Optional[str] = typer.Option(None, "--club", "-c", help="Filtrer par club"),
    limit: int = typer.Option(30, "--limit", "-n", help="Nombre max de résultats"),
    sort: str = typer.Option("nom", "--sort", "-s", help="Colonne de tri (nom, prenom, licence, matchs_joues)"),
    desc: bool = typer.Option(False, "--desc", "-d", help="Tri décroissant"),
):
    """
    👤 Recherche et liste les joueurs.
    
    Exemples:
        pyvolley db explore joueurs
        pyvolley db explore joueurs "Dupont"
        pyvolley db explore joueurs --equipe "Paris" --sort nom -d
        pyvolley db explore joueurs --club "Nantes"
    """
    from pyvolley.database.models import JoueurDB, EquipeDB, ClubDB, ParticipationMatchDB

    session = _get_session()
    try:
        stmt = select(JoueurDB)

        conditions = []

        if query:
            pattern = f"%{query}%"
            conditions.append(
                or_(
                    JoueurDB.nom.ilike(pattern),
                    JoueurDB.prenom.ilike(pattern),
                    JoueurDB.licence.ilike(pattern),
                    (
                        func.coalesce(JoueurDB.nom, "")
                        + " "
                        + func.coalesce(JoueurDB.prenom, "")
                    ).ilike(pattern),
                )
            )

        if equipe:
            stmt = stmt.join(ParticipationMatchDB).join(EquipeDB, ParticipationMatchDB.equipe_id == EquipeDB.id)
            conditions.append(EquipeDB.nom.ilike(f"%{equipe}%"))

        if club:
            if not equipe:
                stmt = stmt.join(ParticipationMatchDB).join(EquipeDB, ParticipationMatchDB.equipe_id == EquipeDB.id)
            stmt = stmt.join(ClubDB, EquipeDB.club_id == ClubDB.id)
            conditions.append(ClubDB.nom.ilike(f"%{club}%"))

        if conditions:
            stmt = stmt.where(*conditions)

        stmt = stmt.distinct()

        # Tri
        sort_col = getattr(JoueurDB, sort, JoueurDB.nom)
        stmt = stmt.order_by(sort_col.desc() if desc else sort_col.asc())
        stmt = stmt.limit(limit)

        joueurs = list(session.scalars(stmt))

        if not joueurs:
            console.print("[yellow]Aucun joueur trouvé avec ces critères[/yellow]")
            return

        tbl = Table(
            title=f"👤 Joueurs ({len(joueurs)} résultat{'s' if len(joueurs) > 1 else ''})",
            box=box.ROUNDED,
            row_styles=["", "dim"],
        )
        tbl.add_column("ID", style="dim", width=5, justify="right")
        tbl.add_column("Licence", style="cyan", width=12)
        tbl.add_column("Nom", style="bold white", min_width=15)
        tbl.add_column("Prénom", style="white", min_width=12)
        tbl.add_column("Matchs", justify="right", style="green", width=7)
        tbl.add_column("Équipes", style="magenta", max_width=30, overflow="ellipsis")

        for j in joueurs:
            # Compter les matchs via participations
            nb_matchs = session.scalar(
                select(func.count()).select_from(ParticipationMatchDB)
                .where(ParticipationMatchDB.joueur_id == j.id)
            ) or 0
            # Trouver les équipes via participations
            equipe_noms = list(session.scalars(
                select(EquipeDB.nom).distinct()
                .join(ParticipationMatchDB, ParticipationMatchDB.equipe_id == EquipeDB.id)
                .where(ParticipationMatchDB.joueur_id == j.id)
                .limit(4)
            ))
            equipes_str = ", ".join(equipe_noms[:3])
            if len(equipe_noms) > 3:
                equipes_str += "..."
            
            tbl.add_row(
                str(j.id),
                j.licence,
                j.nom,
                j.prenom,
                str(nb_matchs),
                equipes_str or "-",
            )

        console.print(tbl)
    finally:
        session.close()


# ============== Commande: joueur (détail) ==============

@explore_app.command("joueur")
def joueur_detail(
    joueur_id: str = typer.Argument(..., help="ID ou licence du joueur"),
):
    """
    📋 Affiche les détails complets d'un joueur.
    
    Exemples:
        pyvolley db explore joueur 42
        pyvolley db explore joueur 1234567
    """
    from pyvolley.database.models import JoueurDB, ParticipationMatchDB, MatchDB, EquipeDB

    session = _get_session()
    try:
        if joueur_id.isdigit() and len(joueur_id) <= 6:
            joueur = session.get(JoueurDB, int(joueur_id))
        else:
            stmt = select(JoueurDB).where(JoueurDB.licence == joueur_id)
            joueur = session.scalar(stmt)

        if not joueur:
            console.print(f"[red]Joueur '{joueur_id}' introuvable[/red]")
            return

        # Compter les matchs via participations
        nb_matchs = session.scalar(
            select(func.count()).select_from(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur.id)
        ) or 0

        # Infos générales
        console.print(Panel(
            f"[bold cyan]{joueur.nom} {joueur.prenom}[/bold cyan]\n\n"
            f"📋 Licence: {joueur.licence}\n"
            f"🏐 Matchs joués: {nb_matchs}",
            title="👤 Profil joueur",
            border_style="blue",
        ))

        # Équipes (via participations)
        equipes = list(session.scalars(
            select(EquipeDB).distinct()
            .join(ParticipationMatchDB, ParticipationMatchDB.equipe_id == EquipeDB.id)
            .where(ParticipationMatchDB.joueur_id == joueur.id)
        ))
        if equipes:
            eq_tbl = Table(title="🏠 Équipes", box=box.SIMPLE)
            eq_tbl.add_column("Équipe", style="white")
            eq_tbl.add_column("Club", style="cyan")
            eq_tbl.add_column("Catégorie", style="dim")
            for e in equipes:
                eq_tbl.add_row(
                    e.nom,
                    e.club.nom if e.club else "-",
                    e.categorie or "-",
                )
            console.print(eq_tbl)

        # Derniers matchs
        stmt = (
            select(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == joueur.id)
            .join(MatchDB)
            .order_by(MatchDB.date_match.desc().nullslast())
            .limit(10)
        )
        participations = list(session.scalars(stmt))

        if participations:
            m_tbl = Table(title="🏐 Derniers matchs (10 max)", box=box.SIMPLE)
            m_tbl.add_column("Date", style="yellow", width=12)
            m_tbl.add_column("Code", style="cyan", width=12)
            m_tbl.add_column("Adversaire", style="white", max_width=25)
            m_tbl.add_column("Score", style="green", justify="center", width=7)
            m_tbl.add_column("N° Maillot", justify="center", width=10)
            m_tbl.add_column("Rôle", style="dim", width=10)

            for p in participations:
                match = p.match
                # Déterminer l'adversaire
                if p.equipe_id == match.equipe_a_id:
                    adversaire = match.equipe_b.nom if match.equipe_b else "?"
                else:
                    adversaire = match.equipe_a.nom if match.equipe_a else "?"

                roles = []
                if p.est_capitaine:
                    roles.append("C")
                if p.est_libero:
                    roles.append("L")

                m_tbl.add_row(
                    str(match.date_match) if match.date_match else "-",
                    match.code_match,
                    adversaire,
                    match.score_sets or "-",
                    p.numero_maillot or "-",
                    " ".join(roles) or "-",
                )
            console.print(m_tbl)
    finally:
        session.close()


# ============== Commande: clubs ==============

@explore_app.command("clubs")
def search_clubs(
    query: Optional[str] = typer.Argument(None, help="Recherche par nom de club"),
    limit: int = typer.Option(30, "--limit", "-n", help="Nombre max de résultats"),
):
    """
    🏠 Recherche et liste les clubs.
    
    Exemples:
        pyvolley db explore clubs
        pyvolley db explore clubs "Paris"
    """
    from pyvolley.database.models import ClubDB

    session = _get_session()
    try:
        stmt = select(ClubDB)
        conditions = []

        if query:
            conditions.append(
                or_(
                    ClubDB.nom.ilike(f"%{query}%"),
                    ClubDB.nom_court.ilike(f"%{query}%"),
                    ClubDB.ville.ilike(f"%{query}%"),
                )
            )

        if conditions:
            stmt = stmt.where(*conditions)

        stmt = stmt.order_by(ClubDB.nom).limit(limit)
        clubs = list(session.scalars(stmt))

        if not clubs:
            console.print("[yellow]Aucun club trouvé[/yellow]")
            return

        tbl = Table(
            title=f"🏠 Clubs ({len(clubs)})",
            box=box.ROUNDED,
            row_styles=["", "dim"],
        )
        tbl.add_column("ID", style="dim", width=5, justify="right")
        tbl.add_column("Nom", style="bold white", min_width=25)
        tbl.add_column("Code FFVB", style="cyan", width=10)
        tbl.add_column("Ville", style="yellow", width=15)
        tbl.add_column("Dép.", style="magenta", width=6)
        tbl.add_column("Équipes", justify="right", style="green", width=8)

        for c in clubs:
            tbl.add_row(
                str(c.id),
                c.nom,
                c.code_ffvb or "-",
                c.ville or "-",
                c.departement or "-",
                str(len(c.equipes)),
            )

        console.print(tbl)
    finally:
        session.close()


# ============== Commande: equipes ==============

@explore_app.command("equipes")
def search_equipes(
    query: Optional[str] = typer.Argument(None, help="Recherche par nom d'équipe"),
    club: Optional[str] = typer.Option(None, "--club", "-c", help="Filtrer par club"),
    categorie: Optional[str] = typer.Option(None, "--categorie", "-k", help="Filtrer par catégorie"),
    genre: Optional[str] = typer.Option(None, "--genre", "-g", help="Filtrer par genre (M/F)"),
    limit: int = typer.Option(30, "--limit", "-n", help="Nombre max de résultats"),
):
    """
    👥 Recherche et liste les équipes.
    
    Exemples:
        pyvolley db explore equipes
        pyvolley db explore equipes "Volley"
        pyvolley db explore equipes --club "Paris" --genre M
    """
    from pyvolley.database.models import EquipeDB, ClubDB, ParticipationMatchDB

    session = _get_session()
    try:
        stmt = select(EquipeDB)
        conditions = []

        if query:
            conditions.append(EquipeDB.nom.ilike(f"%{query}%"))
        if club:
            stmt = stmt.join(ClubDB, EquipeDB.club_id == ClubDB.id)
            conditions.append(ClubDB.nom.ilike(f"%{club}%"))
        if categorie:
            conditions.append(EquipeDB.categorie.ilike(f"%{categorie}%"))
        if genre:
            conditions.append(EquipeDB.genre.ilike(f"%{genre}%"))

        if conditions:
            stmt = stmt.where(*conditions)

        stmt = stmt.order_by(EquipeDB.nom).limit(limit)
        equipes = list(session.scalars(stmt))

        if not equipes:
            console.print("[yellow]Aucune équipe trouvée[/yellow]")
            return

        tbl = Table(
            title=f"👥 Équipes ({len(equipes)})",
            box=box.ROUNDED,
            row_styles=["", "dim"],
        )
        tbl.add_column("ID", style="dim", width=5, justify="right")
        tbl.add_column("Nom", style="bold white", min_width=25)
        tbl.add_column("Club", style="cyan", max_width=20, overflow="ellipsis")
        tbl.add_column("Catégorie", style="yellow", width=12)
        tbl.add_column("Genre", justify="center", width=6)
        tbl.add_column("Joueurs", justify="right", style="green", width=8)

        for e in equipes:
            nb_joueurs = session.scalar(
                select(func.count(func.distinct(ParticipationMatchDB.joueur_id)))
                .where(ParticipationMatchDB.equipe_id == e.id)
            ) or 0
            tbl.add_row(
                str(e.id),
                e.nom,
                e.club.nom if e.club else "-",
                e.categorie or "-",
                e.genre or "-",
                str(nb_joueurs),
            )

        console.print(tbl)
    finally:
        session.close()


# ============== Commande: competitions ==============

@explore_app.command("competitions")
def search_competitions(
    query: Optional[str] = typer.Argument(None, help="Recherche par nom ou code"),
    saison: Optional[str] = typer.Option(None, "--saison", "-s", help="Filtrer par saison (23/24 ou 22/25)"),
    genre: Optional[str] = typer.Option(None, "--genre", "-g", help="Filtrer par genre"),
    entite: Optional[str] = typer.Option(None, "--entite", "-e", help="Filtrer par entité organisatrice"),
    limit: int = typer.Option(30, "--limit", "-n", help="Nombre max de résultats"),
):
    """
    🏆 Recherche et liste les compétitions.
    
    Exemples:
        pyvolley db explore competitions
        pyvolley db explore competitions "Nationale"
        pyvolley db explore competitions --saison 23/24
    """
    from pyvolley.database.models import CompetitionDB, SaisonDB, EntiteFFVBDB

    session = _get_session()
    try:
        stmt = select(CompetitionDB).outerjoin(SaisonDB).outerjoin(EntiteFFVBDB)
        conditions = []

        if query:
            pattern = f"%{query}%"
            conditions.append(
                or_(
                    CompetitionDB.code_competition.ilike(pattern),
                    CompetitionDB.nom.ilike(pattern),
                )
            )
        if saison:
            try:
                saison_codes = saisons_to_db_codes([saison])
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)
            conditions.append(SaisonDB.code.in_(saison_codes))
        if genre:
            conditions.append(CompetitionDB.genre.ilike(f"%{genre}%"))
        if entite:
            conditions.append(
                or_(
                    EntiteFFVBDB.code.ilike(f"%{entite}%"),
                    EntiteFFVBDB.nom.ilike(f"%{entite}%"),
                )
            )

        if conditions:
            stmt = stmt.where(*conditions)

        stmt = stmt.order_by(CompetitionDB.nom).limit(limit)
        competitions = list(session.scalars(stmt))

        if not competitions:
            console.print("[yellow]Aucune compétition trouvée[/yellow]")
            return

        tbl = Table(
            title=f"🏆 Compétitions ({len(competitions)})",
            box=box.ROUNDED,
            row_styles=["", "dim"],
        )
        tbl.add_column("ID", style="dim", width=5, justify="right")
        tbl.add_column("Code", style="cyan", width=10)
        tbl.add_column("Nom", style="bold white", min_width=25)
        tbl.add_column("Saison", style="yellow", width=12)
        tbl.add_column("Genre", justify="center", width=6)
        tbl.add_column("Catégorie", style="dim", width=12)
        tbl.add_column("Entité", style="magenta", width=10)
        tbl.add_column("Matchs", justify="right", style="green", width=7)

        for c in competitions:
            tbl.add_row(
                str(c.id),
                c.code_competition or "-",
                c.nom,
                c.saison.code if c.saison else "-",
                c.genre or "-",
                c.categorie or "-",
                c.entite.code if c.entite else "-",
                str(len(c.matchs)),
            )

        console.print(tbl)
    finally:
        session.close()


# ============== Commande: saisons ==============

@explore_app.command("saisons")
def list_saisons():
    """
    📅 Liste toutes les saisons avec statistiques.
    
    Exemple:
        pyvolley db explore saisons
    """
    from pyvolley.database.models import SaisonDB, MatchDB, CompetitionDB

    session = _get_session()
    try:
        stmt = select(SaisonDB).order_by(SaisonDB.code.desc())
        saisons = list(session.scalars(stmt))

        if not saisons:
            console.print("[yellow]Aucune saison trouvée[/yellow]")
            return

        tbl = Table(title="📅 Saisons", box=box.ROUNDED)
        tbl.add_column("ID", style="dim", width=5, justify="right")
        tbl.add_column("Code", style="cyan", width=12)
        tbl.add_column("Nom", style="white", min_width=20)
        tbl.add_column("Début", style="yellow", width=12)
        tbl.add_column("Fin", style="yellow", width=12)
        tbl.add_column("Compétitions", justify="right", style="magenta", width=12)
        tbl.add_column("Matchs", justify="right", style="green", width=8)

        for s in saisons:
            nb_comp = session.scalar(
                select(func.count()).select_from(CompetitionDB).where(CompetitionDB.saison_id == s.id)
            ) or 0
            nb_matchs = session.scalar(
                select(func.count()).select_from(MatchDB).where(MatchDB.saison_id == s.id)
            ) or 0
            tbl.add_row(
                str(s.id),
                s.code,
                s.nom or "-",
                str(s.date_debut) if s.date_debut else "-",
                str(s.date_fin) if s.date_fin else "-",
                str(nb_comp),
                str(nb_matchs),
            )

        console.print(tbl)
    finally:
        session.close()


# ============== Commande: arbitres ==============

@explore_app.command("arbitres")
def search_arbitres(
    query: Optional[str] = typer.Argument(None, help="Recherche par nom"),
    ligue: Optional[str] = typer.Option(None, "--ligue", "-l", help="Filtrer par ligue"),
    limit: int = typer.Option(30, "--limit", "-n", help="Nombre max de résultats"),
):
    """
    🧑‍⚖️ Recherche et liste les arbitres.
    
    Exemples:
        pyvolley db explore arbitres
        pyvolley db explore arbitres "Martin"
        pyvolley db explore arbitres --ligue LIFL
    """
    from pyvolley.database.models import ArbitreDB, ArbitreMatchDB

    session = _get_session()
    try:
        stmt = select(ArbitreDB)
        conditions = []

        if query:
            pattern = f"%{query}%"
            conditions.append(
                or_(
                    ArbitreDB.nom.ilike(pattern),
                    ArbitreDB.prenom.ilike(pattern),
                )
            )
        if ligue:
            conditions.append(ArbitreDB.ligue.ilike(f"%{ligue}%"))

        if conditions:
            stmt = stmt.where(*conditions)

        stmt = stmt.order_by(ArbitreDB.nom).limit(limit)
        arbitres = list(session.scalars(stmt))

        if not arbitres:
            console.print("[yellow]Aucun arbitre trouvé[/yellow]")
            return

        tbl = Table(
            title=f"🧑‍⚖️ Arbitres ({len(arbitres)})",
            box=box.ROUNDED,
            row_styles=["", "dim"],
        )
        tbl.add_column("ID", style="dim", width=5, justify="right")
        tbl.add_column("Licence", style="cyan", width=12)
        tbl.add_column("Nom", style="bold white", min_width=15)
        tbl.add_column("Prénom", style="white", min_width=10)
        tbl.add_column("Ligue", style="magenta", width=10)
        tbl.add_column("Matchs", justify="right", style="green", width=7)

        for a in arbitres:
            nb_matchs = session.scalar(
                select(func.count()).select_from(ArbitreMatchDB).where(ArbitreMatchDB.arbitre_id == a.id)
            ) or 0
            tbl.add_row(
                str(a.id),
                a.licence or "-",
                a.nom,
                a.prenom or "-",
                a.ligue or "-",
                str(nb_matchs),
            )

        console.print(tbl)
    finally:
        session.close()


# ============== Commande: search (recherche globale) ==============

@explore_app.command("search")
def global_search(
    query: str = typer.Argument(..., help="Terme de recherche (cherche partout)"),
    limit: int = typer.Option(10, "--limit", "-n", help="Nombre max de résultats par catégorie"),
):
    """
    🔎 Recherche globale dans toutes les tables.
    
    Cherche le terme dans les joueurs, clubs, équipes, matchs,
    compétitions et arbitres simultanément.
    
    Exemples:
        pyvolley db explore search "Paris"
        pyvolley db explore search "Dupont"
        pyvolley db explore search "PMAA001"
    """
    from pyvolley.database.models import (
        JoueurDB, ClubDB, EquipeDB, MatchDB, CompetitionDB, ArbitreDB,
    )

    session = _get_session()
    pattern = f"%{query}%"
    found_any = False

    try:
        # Joueurs
        joueurs = list(session.scalars(
            select(JoueurDB).where(
                or_(
                    JoueurDB.nom.ilike(pattern),
                    JoueurDB.prenom.ilike(pattern),
                    JoueurDB.licence.ilike(pattern),
                )
            ).limit(limit)
        ))
        if joueurs:
            found_any = True
            console.print(f"\n[bold cyan]👤 Joueurs ({len(joueurs)} résultat{'s' if len(joueurs) > 1 else ''})[/bold cyan]")
            for j in joueurs:
                console.print(f"  [{j.id}] {j.nom} {j.prenom} — licence: {j.licence}")

        # Clubs
        clubs = list(session.scalars(
            select(ClubDB).where(ClubDB.nom.ilike(pattern)).limit(limit)
        ))
        if clubs:
            found_any = True
            console.print(f"\n[bold cyan]🏠 Clubs ({len(clubs)})[/bold cyan]")
            for c in clubs:
                console.print(f"  [{c.id}] {c.nom} — ville: {c.ville or '?'}")

        # Équipes
        equipes = list(session.scalars(
            select(EquipeDB).where(EquipeDB.nom.ilike(pattern)).limit(limit)
        ))
        if equipes:
            found_any = True
            console.print(f"\n[bold cyan]👥 Équipes ({len(equipes)})[/bold cyan]")
            for e in equipes:
                club_name = e.club.nom if e.club else "?"
                console.print(f"  [{e.id}] {e.nom} — club: {club_name}")

        # Matchs
        matchs = list(session.scalars(
            select(MatchDB).where(
                or_(
                    MatchDB.code_match.ilike(pattern),
                    MatchDB.salle.ilike(pattern),
                    MatchDB.vainqueur.ilike(pattern),
                )
            ).limit(limit)
        ))
        if matchs:
            found_any = True
            console.print(f"\n[bold cyan]🏐 Matchs ({len(matchs)})[/bold cyan]")
            for m in matchs:
                eq_a = m.equipe_a.nom[:20] if m.equipe_a else "?"
                eq_b = m.equipe_b.nom[:20] if m.equipe_b else "?"
                console.print(f"  [{m.id}] {m.code_match}: {eq_a} {m.score_sets or '?'} {eq_b} ({m.date_match or '?'})")

        # Compétitions
        competitions = list(session.scalars(
            select(CompetitionDB).where(
                or_(
                    CompetitionDB.code_competition.ilike(pattern),
                    CompetitionDB.nom.ilike(pattern),
                )
            ).limit(limit)
        ))
        if competitions:
            found_any = True
            console.print(f"\n[bold cyan]🏆 Compétitions ({len(competitions)})[/bold cyan]")
            for c in competitions:
                console.print(f"  [{c.id}] {c.code_competition or '-'}: {c.nom}")

        # Arbitres
        arbitres = list(session.scalars(
            select(ArbitreDB).where(
                or_(
                    ArbitreDB.nom.ilike(pattern),
                    ArbitreDB.prenom.ilike(pattern),
                )
            ).limit(limit)
        ))
        if arbitres:
            found_any = True
            console.print(f"\n[bold cyan]🧑‍⚖️ Arbitres ({len(arbitres)})[/bold cyan]")
            for a in arbitres:
                console.print(f"  [{a.id}] {a.nom_complet} — ligue: {a.ligue or '?'}")

        if not found_any:
            console.print(f"[yellow]Aucun résultat pour '{query}'[/yellow]")
        else:
            console.print()
    finally:
        session.close()


# ============== Commande: sql ==============

@explore_app.command("sql")
def run_sql(
    query: str = typer.Argument(..., help="Requête SQL SELECT à exécuter"),
    limit: int = typer.Option(50, "--limit", "-n", help="Nombre max de lignes"),
):
    """
    💻 Exécute une requête SQL SELECT en lecture seule.
    
    Exemples:
        pyvolley db explore sql "SELECT code_match, score_final FROM matchs WHERE score_final = '3-0' LIMIT 10"
        pyvolley db explore sql "SELECT nom, COUNT(*) as nb FROM clubs GROUP BY ligue"
    """
    # Sécurité : interdire les modifications
    query_upper = query.strip().upper()
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]
    for kw in forbidden:
        if kw in query_upper.split():
            console.print(f"[red]Opération interdite: {kw}. Seules les requêtes SELECT sont autorisées.[/red]")
            return

    if not query_upper.startswith("SELECT"):
        console.print("[red]Seules les requêtes SELECT sont autorisées.[/red]")
        return

    # Ajouter LIMIT si absent
    if "LIMIT" not in query_upper:
        query = query.rstrip(";") + f" LIMIT {limit}"

    session = _get_session()
    try:
        result = session.execute(text(query))
        rows = result.fetchall()
        col_names = list(result.keys())

        if not rows:
            console.print("[yellow]Aucun résultat[/yellow]")
            return

        tbl = Table(title=f"💻 Résultat SQL ({len(rows)} lignes)", box=box.ROUNDED)
        for col in col_names:
            tbl.add_column(col, style="white", overflow="ellipsis", max_width=40)

        for row in rows:
            tbl.add_row(*[_format_value(v) for v in row])

        console.print(tbl)
    except Exception as e:
        console.print(f"[red]Erreur SQL: {e}[/red]")
    finally:
        session.close()
