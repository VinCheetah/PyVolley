"""Rapport détaillé d'un arbitre."""

from __future__ import annotations

from collections import Counter
from sqlalchemy import select, func

from rich.panel import Panel
from rich.table import Table
from rich import box

from .base import Report, ReportSection
from ..database.models import ArbitreDB, ArbitreMatchDB, MatchDB, CompetitionDB


class ArbitreReport(Report):
    """Rapport complet pour un arbitre.

    Sections :
        profil       – Identité et ligue
        bilan        – Statistiques globales (nombre de matchs, rôles)
        competitions – Compétitions arbitrées
        matchs       – Liste des matchs arbitrés
        saisons      – Répartition par saison
    """

    def __init__(self, session, arbitre: ArbitreDB, *, max_matchs: int = 50, **kwargs):
        super().__init__(session, **kwargs)
        self.arbitre = arbitre
        self.max_matchs = max_matchs

    def _build_sections(self) -> None:
        a = self.arbitre
        self._section_profil(a)
        self._section_bilan(a)
        self._section_competitions(a)
        self._section_matchs(a)
        self._section_saisons(a)

    def _section_profil(self, a: ArbitreDB) -> None:
        entries = [
            ("Nom complet", a.nom_complet),
            ("Licence", self._safe(a.licence)),
            ("Ligue", self._safe(a.ligue)),
        ]
        self._add(ReportSection(
            key="profil", title="Profil",
            content=self._kv_panel(entries, title=f"🧑‍⚖️ {a.nom_complet}"),
            order=0,
        ))

    def _section_bilan(self, a: ArbitreDB) -> None:
        arbitrages = a.arbitrages  # list[ArbitreMatchDB]
        nb = len(arbitrages)
        if nb == 0:
            self._add(ReportSection(key="bilan", title="Bilan", content="", order=10, empty=True))
            return

        # Comptage des rôles
        roles_counter = Counter(am.role for am in arbitrages)
        roles_lines = [f"  • {role}: {count}" for role, count in roles_counter.most_common()]

        # Rôle principal
        role_principal = roles_counter.most_common(1)[0][0] if roles_counter else "-"

        entries = [
            ("Matchs total", str(nb)),
            ("Rôle principal", role_principal),
            ("Rôles", "\n" + "\n".join(roles_lines) if roles_lines else "-"),
        ]
        self._add(ReportSection(
            key="bilan", title="Bilan",
            content=self._kv_panel(entries, title="📊 Bilan"),
            order=10,
        ))

    def _section_competitions(self, a: ArbitreDB) -> None:
        """Compétitions dans lesquelles l'arbitre a officié."""
        arbitrages = a.arbitrages
        if not arbitrages:
            self._add(ReportSection(key="competitions", title="Compétitions", content="", order=15, empty=True))
            return

        comp_counter: Counter[str] = Counter()
        for am in arbitrages:
            m = am.match
            if m and m.competition:
                comp_counter[m.competition.nom] += 1

        if not comp_counter:
            self._add(ReportSection(key="competitions", title="Compétitions", content="", order=15, empty=True))
            return

        tbl = Table(title="🏆 Compétitions", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Compétition", style="white", min_width=20)
        tbl.add_column("Matchs", justify="right", width=7)

        for comp, count in comp_counter.most_common(15):
            tbl.add_row(comp, str(count))

        self._add(ReportSection(key="competitions", title="Compétitions", content=tbl, order=15))

    def _section_matchs(self, a: ArbitreDB) -> None:
        arbitrages = a.arbitrages
        if not arbitrages:
            self._add(ReportSection(key="matchs", title="Matchs", content="", order=20, empty=True))
            return

        # Récupérer les matchs liés et trier par date
        matchs_data = []
        for am in arbitrages:
            m = am.match
            if m:
                matchs_data.append((m, am.role))
        matchs_data.sort(key=lambda x: (x[0].date_match or "", x[0].heure_match or ""), reverse=True)

        tbl = Table(title=f"🏐 Matchs arbitrés ({len(matchs_data)} total)", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Date", style="cyan", width=12)
        tbl.add_column("Code", style="white", width=15)
        tbl.add_column("Match", min_width=30)
        tbl.add_column("Score", justify="center", width=10)
        tbl.add_column("Rôle", style="magenta", width=15)

        for m, role in matchs_data[:self.max_matchs]:
            eq_a = m.equipe_a.nom[:18] if m.equipe_a else "?"
            eq_b = m.equipe_b.nom[:18] if m.equipe_b else "?"
            tbl.add_row(
                self._safe(m.date_match),
                self._safe(m.code_match),
                f"{eq_a} vs {eq_b}",
                self._safe(m.score_sets),
                role,
            )
        if len(matchs_data) > self.max_matchs:
            tbl.add_row("...", "", f"et {len(matchs_data) - self.max_matchs} autres", "", "")

        self._add(ReportSection(key="matchs", title="Matchs", content=tbl, order=20))

    def _section_saisons(self, a: ArbitreDB) -> None:
        arbitrages = a.arbitrages
        if not arbitrages:
            self._add(ReportSection(key="saisons", title="Saisons", content="", order=30, empty=True))
            return

        saison_counter: Counter[str] = Counter()
        for am in arbitrages:
            m = am.match
            if m and m.saison:
                saison_counter[m.saison.code] += 1
            elif m:
                saison_counter["(inconnue)"] += 1

        if not saison_counter:
            self._add(ReportSection(key="saisons", title="Saisons", content="", order=30, empty=True))
            return

        tbl = Table(title="📅 Par saison", box=box.SIMPLE)
        tbl.add_column("Saison", style="cyan")
        tbl.add_column("Matchs", justify="right")

        for saison, count in sorted(saison_counter.items()):
            tbl.add_row(saison, str(count))

        self._add(ReportSection(key="saisons", title="Saisons", content=tbl, order=30))
