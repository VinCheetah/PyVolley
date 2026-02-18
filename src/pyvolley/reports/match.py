"""Rapport détaillé d'un match."""

from __future__ import annotations

from sqlalchemy import select
from rich.panel import Panel
from rich.table import Table
from rich import box

from .base import Report, ReportSection
from ..database.models import (
    MatchDB, SetDB, FormationDB, ChangementDB, TimeoutDB,
    ParticipationMatchDB, ArbitreMatchDB, SanctionDB,
    OfficielMatchDB,
)


class MatchReport(Report):
    """Rapport complet pour un match.

    Sections :
        infos       – Informations générales
        score       – Score et sets détaillés
        equipe_a    – Composition équipe A
        equipe_b    – Composition équipe B
        formations  – Formations de départ
        changements – Changements par set
        timeouts    – Temps morts
        arbitres    – Arbitres
        sanctions   – Sanctions
        officiels   – Officiels d'équipe
        metadata    – Métadonnées (source PDF, etc.)
    """

    def __init__(self, session, match: MatchDB, **kwargs):
        super().__init__(session, **kwargs)
        self.match = match

    def _build_sections(self) -> None:
        m = self.match
        self._section_infos(m)
        self._section_score(m)
        self._section_equipe(m, "A")
        self._section_equipe(m, "B")
        self._section_formations(m)
        self._section_changements(m)
        self._section_timeouts(m)
        self._section_arbitres(m)
        self._section_sanctions(m)
        self._section_officiels(m)
        self._section_metadata(m)

    def _section_infos(self, m: MatchDB) -> None:
        eq_a = m.equipe_a.nom if m.equipe_a else "?"
        eq_b = m.equipe_b.nom if m.equipe_b else "?"
        content = (
            f"[bold cyan]{self._safe(m.code_match)}[/bold cyan]\n\n"
            f"[bold]{eq_a}[/bold]  [bold green]{self._safe(m.score_sets, '?')}[/bold green]  [bold]{eq_b}[/bold]\n\n"
            f"📅 Date: {self._safe(m.date_match, '?')}  🕐 Heure: {self._safe(m.heure_match, '?')}\n"
            f"📍 Lieu: {self._safe(m.lieu, '?')}  |  Salle: {self._safe(m.salle, '?')}\n"
            f"🏆 Compétition: {m.competition.nom if m.competition else '?'}\n"
            f"📅 Saison: {m.saison.code if m.saison else '?'}\n"
            f"📆 Journée: {self._safe(m.journee, '?')}\n"
            f"🏆 Vainqueur: {self._safe(m.vainqueur, '?')}\n"
            f"⏱️ Durée: {self._safe(m.duree_totale, '?')}"
        )
        self._add(ReportSection(
            key="infos", title="Informations",
            content=Panel(content, title="🏐 Match", border_style="blue"),
            order=0,
        ))

    def _section_score(self, m: MatchDB) -> None:
        if not m.sets:
            self._add(ReportSection(key="score", title="Score", content="", order=10, empty=True))
            return

        eq_a = m.equipe_a.nom[:20] if m.equipe_a else "Éq. A"
        eq_b = m.equipe_b.nom[:20] if m.equipe_b else "Éq. B"

        tbl = Table(title="📊 Sets", box=box.SIMPLE)
        tbl.add_column("Set", justify="center", style="cyan", width=5)
        tbl.add_column(eq_a, justify="center", style="white", width=10)
        tbl.add_column(eq_b, justify="center", style="white", width=10)
        tbl.add_column("Durée", justify="center", style="dim", width=8)
        tbl.add_column("Service", justify="center", style="dim", width=8)

        for s in m.sets:
            dur = f"{s.duree_minutes}min" if s.duree_minutes else "-"
            tbl.add_row(
                str(s.numero),
                str(s.score_a) if s.score_a is not None else "-",
                str(s.score_b) if s.score_b is not None else "-",
                dur,
                s.service_initial or "-",
            )
        self._add(ReportSection(key="score", title="Score", content=tbl, order=10))

    def _section_equipe(self, m: MatchDB, side: str) -> None:
        equipe_id = m.equipe_a_id if side == "A" else m.equipe_b_id
        equipe_nom = (m.equipe_a.nom if m.equipe_a else "?") if side == "A" else (m.equipe_b.nom if m.equipe_b else "?")

        participants = [p for p in m.participations if p.equipe_id == equipe_id]
        if not participants:
            self._add(ReportSection(
                key=f"equipe_{side.lower()}", title=f"Équipe {side}",
                content="", order=20 if side == "A" else 25, empty=True,
            ))
            return

        tbl = Table(title=f"👥 {equipe_nom}", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("N°", justify="center", width=4)
        tbl.add_column("Nom", style="white", min_width=15)
        tbl.add_column("Prénom", style="white", min_width=10)
        tbl.add_column("Licence", style="dim", width=12)
        tbl.add_column("Rôle", style="cyan", width=8)

        for p in sorted(participants, key=lambda x: x.numero_maillot or "99"):
            roles = []
            if p.est_capitaine:
                roles.append("C")
            if p.est_libero:
                roles.append("L")
            tbl.add_row(
                p.numero_maillot or "-",
                p.joueur.nom if p.joueur else "-",
                p.joueur.prenom if p.joueur else "-",
                p.joueur.licence if p.joueur else "-",
                " ".join(roles) or "-",
            )
        self._add(ReportSection(
            key=f"equipe_{side.lower()}", title=f"Équipe {side}",
            content=tbl, order=20 if side == "A" else 25,
        ))

    def _section_formations(self, m: MatchDB) -> None:
        formations = []
        for s in m.sets:
            for f in s.formations:
                formations.append((s.numero, f))
        if not formations:
            self._add(ReportSection(key="formations", title="Formations", content="", order=30, empty=True))
            return

        tbl = Table(title="📋 Formations de départ", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Set", justify="center", width=4)
        tbl.add_column("Éq.", justify="center", width=4)
        for i in range(1, 7):
            tbl.add_column(f"P{i}", justify="center", width=4)

        for set_num, f in sorted(formations, key=lambda x: (x[0], x[1].equipe)):
            tbl.add_row(
                str(set_num), f.equipe,
                f.position_1 or "-", f.position_2 or "-", f.position_3 or "-",
                f.position_4 or "-", f.position_5 or "-", f.position_6 or "-",
            )
        self._add(ReportSection(key="formations", title="Formations", content=tbl, order=30))

    def _section_changements(self, m: MatchDB) -> None:
        changements = []
        for s in m.sets:
            for c in s.changements:
                changements.append((s.numero, c))
        if not changements:
            self._add(ReportSection(key="changements", title="Changements", content="", order=35, empty=True))
            return

        tbl = Table(title="🔄 Changements", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Set", justify="center", width=4)
        tbl.add_column("Éq.", justify="center", width=4)
        tbl.add_column("Entrant", style="green", width=8)
        tbl.add_column("Sortant", style="red", width=8)
        tbl.add_column("Score", justify="center", width=8)

        for set_num, c in sorted(changements, key=lambda x: (x[0], x[1].equipe)):
            score = f"{c.score_a}-{c.score_b}" if c.score_a is not None else "-"
            tbl.add_row(str(set_num), c.equipe, c.joueur_entrant, c.joueur_sortant or "-", score)

        self._add(ReportSection(key="changements", title="Changements", content=tbl, order=35))

    def _section_timeouts(self, m: MatchDB) -> None:
        timeouts = []
        for s in m.sets:
            for t in s.timeouts:
                timeouts.append((s.numero, t))
        if not timeouts:
            self._add(ReportSection(key="timeouts", title="Timeouts", content="", order=37, empty=True))
            return

        tbl = Table(title="⏸️ Temps morts", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Set", justify="center", width=4)
        tbl.add_column("Éq.", justify="center", width=4)
        tbl.add_column("Score", justify="center", width=8)

        for set_num, t in sorted(timeouts, key=lambda x: (x[0], x[1].equipe)):
            tbl.add_row(str(set_num), t.equipe, f"{t.score_a}-{t.score_b}")

        self._add(ReportSection(key="timeouts", title="Timeouts", content=tbl, order=37))

    def _section_arbitres(self, m: MatchDB) -> None:
        if not m.arbitrages:
            self._add(ReportSection(key="arbitres", title="Arbitres", content="", order=40, empty=True))
            return

        tbl = Table(title="🧑‍⚖️ Arbitres", box=box.SIMPLE)
        tbl.add_column("Rôle", style="cyan", width=20)
        tbl.add_column("Nom", style="white")
        tbl.add_column("Licence", style="dim", width=12)
        tbl.add_column("Ligue", style="dim", width=8)

        for a in m.arbitrages:
            tbl.add_row(
                a.role,
                a.arbitre.nom_complet if a.arbitre else "-",
                a.arbitre.licence if a.arbitre else "-",
                a.arbitre.ligue if a.arbitre else "-",
            )
        self._add(ReportSection(key="arbitres", title="Arbitres", content=tbl, order=40))

    def _section_sanctions(self, m: MatchDB) -> None:
        if not m.sanctions:
            self._add(ReportSection(key="sanctions", title="Sanctions", content="", order=45, empty=True))
            return

        tbl = Table(title="🟨 Sanctions", box=box.SIMPLE)
        tbl.add_column("Type", justify="center", width=6)
        tbl.add_column("Set", justify="center", width=5)
        tbl.add_column("Équipe", justify="center", width=8)
        tbl.add_column("N° Joueur", justify="center", width=10)
        tbl.add_column("Score", justify="center", width=8)

        for s in m.sanctions:
            score = f"{s.score_a}-{s.score_b}" if s.score_a is not None else "-"
            tbl.add_row(s.type_sanction, str(s.set_numero), s.equipe, s.joueur_numero or "-", score)

        self._add(ReportSection(key="sanctions", title="Sanctions", content=tbl, order=45))

    def _section_officiels(self, m: MatchDB) -> None:
        if not m.officiels:
            self._add(ReportSection(key="officiels", title="Officiels", content="", order=50, empty=True))
            return

        tbl = Table(title="👔 Officiels d'équipe", box=box.SIMPLE)
        tbl.add_column("Éq.", justify="center", width=4)
        tbl.add_column("Rôle", style="cyan", width=10)
        tbl.add_column("Nom", style="white")
        tbl.add_column("Prénom", style="white")
        tbl.add_column("Licence", style="dim", width=12)

        for o in sorted(m.officiels, key=lambda x: (x.equipe, x.role)):
            tbl.add_row(o.equipe, o.role, o.nom, o.prenom or "-", o.licence or "-")

        self._add(ReportSection(key="officiels", title="Officiels", content=tbl, order=50))

    def _section_metadata(self, m: MatchDB) -> None:
        content = (
            f"📄 Source PDF: {self._safe(m.source_pdf)}\n"
            f"🕐 Parsé le: {self._safe(m.parsed_at)}\n"
            f"📅 Créé le: {self._safe(m.created_at)}\n"
            f"📅 MàJ le: {self._safe(m.updated_at)}\n"
            f"📝 Remarques: {self._safe(m.remarques)}"
        )
        self._add(ReportSection(
            key="metadata", title="Métadonnées",
            content=Panel(content, title="ℹ️ Métadonnées", border_style="dim"),
            order=90,
        ))
