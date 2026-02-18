"""
Commandes CLI pour générer des rapports d'entités PyVolley.

Chaque commande charge une entité par identifiant (id, licence, code…)
et délègue la construction au module ``pyvolley.reports``.

Usage :
    pyvolley report joueur "Dupont"
    pyvolley report club "PARIS VOLLEY"
    pyvolley report equipe 42
    pyvolley report match "ABC123"
    pyvolley report arbitre "Martin"
    pyvolley report competition "N2M"
    pyvolley report saison "2025-2026"

Options communes :
    --include / -i  : sections à inclure (exclusif)
    --exclude / -e  : sections à exclure
    --show-empty    : afficher les sections sans données
    --sections      : lister les sections disponibles sans contenu
"""

from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from sqlalchemy import select, or_, func

console = Console()

report_app = typer.Typer(
    name="report",
    help="📝 Générer des rapports détaillés (joueur, club, équipe, match, arbitre, compétition, saison)",
)


# ── Helpers ─────────────────────────────────────────────────────

def _get_session():
    """Ouvre une session DB (import tardif pour éviter les dépendances circulaires)."""
    from pyvolley.database.connection import get_session_factory
    return get_session_factory()()


def _parse_set(values: Optional[List[str]]) -> Optional[set[str]]:
    """Transforme une liste typer en set, ou None si vide."""
    if not values:
        return None
    return set(values)


def _list_sections(report_cls, session, entity, **kwargs):
    """Instancie le rapport et affiche les sections disponibles."""
    rpt = report_cls(session, entity, **kwargs)
    rpt.hide_empty = False
    sections = rpt.build()
    tbl = Table(title="Sections disponibles", box=box.SIMPLE)
    tbl.add_column("Clé", style="cyan")
    tbl.add_column("Titre", style="white")
    tbl.add_column("Ordre", justify="right")
    tbl.add_column("Vide ?", justify="center")
    for s in sections:
        tbl.add_row(s.key, s.title, str(s.order), "✓" if s.empty else "")
    console.print(tbl)


# ── Commande : joueur ──────────────────────────────────────────

@report_app.command("joueur")
def report_joueur(
    identifier: str = typer.Argument(help="ID, licence, ou nom du joueur"),
    include: Optional[List[str]] = typer.Option(None, "--include", "-i", help="Sections à inclure"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude", "-e", help="Sections à exclure"),
    show_empty: bool = typer.Option(False, "--show-empty", help="Afficher les sections vides"),
    sections: bool = typer.Option(False, "--sections", help="Lister les sections disponibles"),
    max_matchs: int = typer.Option(20, "--max-matchs", help="Nombre max de matchs affichés"),
):
    """📋 Rapport détaillé d'un joueur (profil, stats, matchs, coéquipiers…)."""
    from pyvolley.reports import JoueurReport
    from pyvolley.database.models import JoueurDB

    session = _get_session()
    try:
        joueur = _find_joueur(session, identifier)
        if not joueur:
            console.print(f"[red]Joueur introuvable : {identifier}[/red]")
            raise typer.Exit(1)

        if sections:
            _list_sections(JoueurReport, session, joueur, max_matchs=max_matchs)
            return

        rpt = JoueurReport(
            session, joueur,
            max_matchs=max_matchs,
            exclude=_parse_set(exclude) or set(),
            include=_parse_set(include),
            hide_empty=not show_empty,
        )
        rpt.render(console)
    finally:
        session.close()


def _find_joueur(session, identifier: str):
    from pyvolley.database.models import JoueurDB

    # Par ID
    if identifier.isdigit():
        return session.get(JoueurDB, int(identifier))

    # Par licence
    j = session.scalar(select(JoueurDB).where(JoueurDB.licence == identifier))
    if j:
        return j

    # Par nom (recherche partielle, insensible casse)
    term = f"%{identifier}%"
    j = session.scalar(
        select(JoueurDB).where(
            or_(
                func.lower(JoueurDB.nom).like(func.lower(term)),
                func.lower(JoueurDB.prenom).like(func.lower(term)),
                func.lower(JoueurDB.nom + " " + JoueurDB.prenom).like(func.lower(term)),
            )
        )
    )
    return j


# ── Commande : club ────────────────────────────────────────────

@report_app.command("club")
def report_club(
    identifier: str = typer.Argument(help="ID, code FFVB, ou nom du club"),
    include: Optional[List[str]] = typer.Option(None, "--include", "-i", help="Sections à inclure"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude", "-e", help="Sections à exclure"),
    show_empty: bool = typer.Option(False, "--show-empty", help="Afficher les sections vides"),
    sections: bool = typer.Option(False, "--sections", help="Lister les sections disponibles"),
):
    """📋 Rapport détaillé d'un club (profil, équipes, bilan, joueurs…)."""
    from pyvolley.reports import ClubReport
    from pyvolley.database.models import ClubDB, ClubAliasDB

    session = _get_session()
    try:
        club = _find_club(session, identifier)
        if not club:
            console.print(f"[red]Club introuvable : {identifier}[/red]")
            raise typer.Exit(1)

        if sections:
            _list_sections(ClubReport, session, club)
            return

        rpt = ClubReport(
            session, club,
            exclude=_parse_set(exclude) or set(),
            include=_parse_set(include),
            hide_empty=not show_empty,
        )
        rpt.render(console)
    finally:
        session.close()


def _find_club(session, identifier: str):
    from pyvolley.database.models import ClubDB, ClubAliasDB

    if identifier.isdigit():
        return session.get(ClubDB, int(identifier))

    # Par code FFVB
    c = session.scalar(select(ClubDB).where(ClubDB.code_ffvb == identifier))
    if c:
        return c

    # Par nom
    term = f"%{identifier}%"
    c = session.scalar(
        select(ClubDB).where(func.lower(ClubDB.nom).like(func.lower(term)))
    )
    if c:
        return c

    # Par alias
    alias = session.scalar(
        select(ClubAliasDB).where(func.lower(ClubAliasDB.alias).like(func.lower(term)))
    )
    if alias:
        return alias.club
    return None


# ── Commande : equipe ──────────────────────────────────────────

@report_app.command("equipe")
def report_equipe(
    identifier: str = typer.Argument(help="ID ou nom de l'équipe"),
    include: Optional[List[str]] = typer.Option(None, "--include", "-i", help="Sections à inclure"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude", "-e", help="Sections à exclure"),
    show_empty: bool = typer.Option(False, "--show-empty", help="Afficher les sections vides"),
    sections: bool = typer.Option(False, "--sections", help="Lister les sections disponibles"),
):
    """📋 Rapport détaillé d'une équipe (profil, bilan, effectif, matchs…)."""
    from pyvolley.reports import EquipeReport
    from pyvolley.database.models import EquipeDB

    session = _get_session()
    try:
        equipe = _find_equipe(session, identifier)
        if not equipe:
            console.print(f"[red]Équipe introuvable : {identifier}[/red]")
            raise typer.Exit(1)

        if sections:
            _list_sections(EquipeReport, session, equipe)
            return

        rpt = EquipeReport(
            session, equipe,
            exclude=_parse_set(exclude) or set(),
            include=_parse_set(include),
            hide_empty=not show_empty,
        )
        rpt.render(console)
    finally:
        session.close()


def _find_equipe(session, identifier: str):
    from pyvolley.database.models import EquipeDB

    if identifier.isdigit():
        return session.get(EquipeDB, int(identifier))

    term = f"%{identifier}%"
    return session.scalar(
        select(EquipeDB).where(func.lower(EquipeDB.nom).like(func.lower(term)))
    )


# ── Commande : match ───────────────────────────────────────────

@report_app.command("match")
def report_match(
    identifier: str = typer.Argument(help="ID ou code_match du match"),
    include: Optional[List[str]] = typer.Option(None, "--include", "-i", help="Sections à inclure"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude", "-e", help="Sections à exclure"),
    show_empty: bool = typer.Option(False, "--show-empty", help="Afficher les sections vides"),
    sections: bool = typer.Option(False, "--sections", help="Lister les sections disponibles"),
):
    """📋 Rapport détaillé d'un match (score, sets, formations, arbitres…)."""
    from pyvolley.reports import MatchReport
    from pyvolley.database.models import MatchDB

    session = _get_session()
    try:
        match = _find_match(session, identifier)
        if not match:
            console.print(f"[red]Match introuvable : {identifier}[/red]")
            raise typer.Exit(1)

        if sections:
            _list_sections(MatchReport, session, match)
            return

        rpt = MatchReport(
            session, match,
            exclude=_parse_set(exclude) or set(),
            include=_parse_set(include),
            hide_empty=not show_empty,
        )
        rpt.render(console)
    finally:
        session.close()


def _find_match(session, identifier: str):
    from pyvolley.database.models import MatchDB

    if identifier.isdigit():
        return session.get(MatchDB, int(identifier))

    return session.scalar(
        select(MatchDB).where(MatchDB.code_match == identifier)
    )


# ── Commande : arbitre ─────────────────────────────────────────

@report_app.command("arbitre")
def report_arbitre(
    identifier: str = typer.Argument(help="ID, licence, ou nom de l'arbitre"),
    include: Optional[List[str]] = typer.Option(None, "--include", "-i", help="Sections à inclure"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude", "-e", help="Sections à exclure"),
    show_empty: bool = typer.Option(False, "--show-empty", help="Afficher les sections vides"),
    sections: bool = typer.Option(False, "--sections", help="Lister les sections disponibles"),
    max_matchs: int = typer.Option(50, "--max-matchs", help="Nombre max de matchs affichés"),
):
    """📋 Rapport détaillé d'un arbitre (profil, bilan, matchs…)."""
    from pyvolley.reports import ArbitreReport
    from pyvolley.database.models import ArbitreDB

    session = _get_session()
    try:
        arbitre = _find_arbitre(session, identifier)
        if not arbitre:
            console.print(f"[red]Arbitre introuvable : {identifier}[/red]")
            raise typer.Exit(1)

        if sections:
            _list_sections(ArbitreReport, session, arbitre, max_matchs=max_matchs)
            return

        rpt = ArbitreReport(
            session, arbitre,
            max_matchs=max_matchs,
            exclude=_parse_set(exclude) or set(),
            include=_parse_set(include),
            hide_empty=not show_empty,
        )
        rpt.render(console)
    finally:
        session.close()


def _find_arbitre(session, identifier: str):
    from pyvolley.database.models import ArbitreDB

    if identifier.isdigit():
        return session.get(ArbitreDB, int(identifier))

    a = session.scalar(select(ArbitreDB).where(ArbitreDB.licence == identifier))
    if a:
        return a

    term = f"%{identifier}%"
    return session.scalar(
        select(ArbitreDB).where(
            or_(
                func.lower(ArbitreDB.nom).like(func.lower(term)),
                func.lower(ArbitreDB.prenom).like(func.lower(term)),
                func.lower(ArbitreDB.nom + " " + ArbitreDB.prenom).like(func.lower(term)),
            )
        )
    )


# ── Commande : competition ─────────────────────────────────────

@report_app.command("competition")
def report_competition(
    identifier: str = typer.Argument(help="ID, code, ou nom de la compétition"),
    include: Optional[List[str]] = typer.Option(None, "--include", "-i", help="Sections à inclure"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude", "-e", help="Sections à exclure"),
    show_empty: bool = typer.Option(False, "--show-empty", help="Afficher les sections vides"),
    sections: bool = typer.Option(False, "--sections", help="Lister les sections disponibles"),
    max_matchs: int = typer.Option(50, "--max-matchs", help="Nombre max de matchs affichés"),
):
    """📋 Rapport détaillé d'une compétition (poules, classement, matchs…)."""
    from pyvolley.reports import CompetitionReport
    from pyvolley.database.models import CompetitionDB

    session = _get_session()
    try:
        competition = _find_competition(session, identifier)
        if not competition:
            console.print(f"[red]Compétition introuvable : {identifier}[/red]")
            raise typer.Exit(1)

        if sections:
            _list_sections(CompetitionReport, session, competition, max_matchs=max_matchs)
            return

        rpt = CompetitionReport(
            session, competition,
            max_matchs=max_matchs,
            exclude=_parse_set(exclude) or set(),
            include=_parse_set(include),
            hide_empty=not show_empty,
        )
        rpt.render(console)
    finally:
        session.close()


def _find_competition(session, identifier: str):
    from pyvolley.database.models import CompetitionDB

    if identifier.isdigit():
        return session.get(CompetitionDB, int(identifier))

    c = session.scalar(select(CompetitionDB).where(CompetitionDB.code_competition == identifier))
    if c:
        return c

    term = f"%{identifier}%"
    return session.scalar(
        select(CompetitionDB).where(func.lower(CompetitionDB.nom).like(func.lower(term)))
    )


# ── Commande : saison ──────────────────────────────────────────

@report_app.command("saison")
def report_saison(
    identifier: str = typer.Argument(help="ID ou code de la saison (ex: 2025-2026)"),
    include: Optional[List[str]] = typer.Option(None, "--include", "-i", help="Sections à inclure"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude", "-e", help="Sections à exclure"),
    show_empty: bool = typer.Option(False, "--show-empty", help="Afficher les sections vides"),
    sections: bool = typer.Option(False, "--sections", help="Lister les sections disponibles"),
):
    """📋 Rapport détaillé d'une saison (compétitions, bilan, clubs, joueurs…)."""
    from pyvolley.reports import SaisonReport
    from pyvolley.database.models import SaisonDB

    session = _get_session()
    try:
        saison = _find_saison(session, identifier)
        if not saison:
            console.print(f"[red]Saison introuvable : {identifier}[/red]")
            raise typer.Exit(1)

        if sections:
            _list_sections(SaisonReport, session, saison)
            return

        rpt = SaisonReport(
            session, saison,
            exclude=_parse_set(exclude) or set(),
            include=_parse_set(include),
            hide_empty=not show_empty,
        )
        rpt.render(console)
    finally:
        session.close()


def _find_saison(session, identifier: str):
    from pyvolley.database.models import SaisonDB

    if identifier.isdigit():
        return session.get(SaisonDB, int(identifier))

    return session.scalar(select(SaisonDB).where(SaisonDB.code == identifier))
