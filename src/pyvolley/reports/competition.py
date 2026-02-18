"""Rapport détaillé d'une compétition."""

from __future__ import annotations

from collections import Counter
from sqlalchemy import select, func

from rich.panel import Panel
from rich.table import Table
from rich import box

from .base import Report, ReportSection
from ..database.models import (
    CompetitionDB, PouleDB, MatchDB, EquipeDB,
    ParticipationMatchDB, JoueurDB,
)


class CompetitionReport(Report):
    """Rapport complet pour une compétition.

    Sections :
        profil       – Identité de la compétition
        poules       – Liste des poules
        classement   – Classement des équipes (V/D)
        statistiques – Statistiques globales
        matchs       – Liste des matchs
        joueurs      – Statistiques joueurs
    """

    def __init__(self, session, competition: CompetitionDB, *, max_matchs: int = 50, **kwargs):
        super().__init__(session, **kwargs)
        self.competition = competition
        self.max_matchs = max_matchs

    def _build_sections(self) -> None:
        c = self.competition
        self._section_profil(c)
        self._section_poules(c)
        self._section_classement(c)
        self._section_statistiques(c)
        self._section_matchs(c)
        self._section_joueurs(c)

    def _section_profil(self, c: CompetitionDB) -> None:
        entries = [
            ("Nom", c.nom),
            ("Code", self._safe(c.code_competition)),
            ("Saison", c.saison.code if c.saison else "-"),
            ("Entité", f"{c.entite.nom} ({c.entite.code})" if c.entite else "-"),
            ("Genre", self._safe(c.genre)),
            ("Catégorie", self._safe(c.categorie)),
            ("Division", self._safe(c.division)),
            ("Niveau", self._safe(c.niveau)),
            ("Nb poules", str(len(c.poules))),
            ("Nb matchs", str(len(c.matchs))),
        ]
        self._add(ReportSection(
            key="profil", title="Profil",
            content=self._kv_panel(entries, title=f"🏆 {c.nom}"),
            order=0,
        ))

    def _section_poules(self, c: CompetitionDB) -> None:
        if not c.poules:
            self._add(ReportSection(key="poules", title="Poules", content="", order=10, empty=True))
            return

        tbl = Table(title="📋 Poules", box=box.SIMPLE)
        tbl.add_column("Code", style="cyan", width=10)
        tbl.add_column("Nom", style="white")
        tbl.add_column("Matchs", justify="right", width=8)

        for p in sorted(c.poules, key=lambda x: x.code):
            tbl.add_row(p.code, p.nom or "-", str(len(p.matchs)))

        self._add(ReportSection(key="poules", title="Poules", content=tbl, order=10))

    def _section_classement(self, c: CompetitionDB) -> None:
        matchs = c.matchs
        if not matchs:
            self._add(ReportSection(key="classement", title="Classement", content="", order=20, empty=True))
            return

        # Calculer V/D par équipe
        stats: dict[int, dict] = {}
        for m in matchs:
            for side, eq_id in [("A", m.equipe_a_id), ("B", m.equipe_b_id)]:
                if eq_id is None:
                    continue
                if eq_id not in stats:
                    eq = m.equipe_a if side == "A" else m.equipe_b
                    stats[eq_id] = {"nom": eq.nom if eq else "?", "v": 0, "d": 0, "sets_g": 0, "sets_p": 0}
                if m.vainqueur:
                    eq = m.equipe_a if side == "A" else m.equipe_b
                    if eq and m.vainqueur == eq.nom:
                        stats[eq_id]["v"] += 1
                    else:
                        stats[eq_id]["d"] += 1
                    if side == "A":
                        stats[eq_id]["sets_g"] += m.sets_equipe_a
                        stats[eq_id]["sets_p"] += m.sets_equipe_b
                    else:
                        stats[eq_id]["sets_g"] += m.sets_equipe_b
                        stats[eq_id]["sets_p"] += m.sets_equipe_a

        tbl = Table(title="📊 Classement", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("#", justify="center", width=4)
        tbl.add_column("Équipe", min_width=20)
        tbl.add_column("V", justify="right", style="green", width=4)
        tbl.add_column("D", justify="right", style="red", width=4)
        tbl.add_column("Total", justify="right", width=6)
        tbl.add_column("Sets +/-", justify="right", width=8)
        tbl.add_column("Taux", justify="right", width=7)

        ranked = sorted(stats.values(), key=lambda x: (-x["v"], x["d"]))
        for i, s in enumerate(ranked, 1):
            total = s["v"] + s["d"]
            taux = f"{s['v'] / total * 100:.0f}%" if total else "-"
            tbl.add_row(
                str(i), s["nom"],
                str(s["v"]), str(s["d"]), str(total),
                f"{s['sets_g']}/{s['sets_p']}", taux,
            )

        self._add(ReportSection(key="classement", title="Classement", content=tbl, order=20))

    def _section_statistiques(self, c: CompetitionDB) -> None:
        """Statistiques globales de la compétition."""
        matchs = c.matchs
        if not matchs:
            self._add(ReportSection(key="statistiques", title="Statistiques", content="", order=25, empty=True))
            return

        joues = [m for m in matchs if m.is_played]
        nb_joues = len(joues)

        # Score 3-0, 3-1, 3-2 distribution
        score_distrib: Counter[str] = Counter()
        total_sets = 0
        for m in joues:
            if m.score_sets:
                score_distrib[m.score_sets] += 1
            total_sets += (m.sets_equipe_a or 0) + (m.sets_equipe_b or 0)

        avg_sets = total_sets / nb_joues if nb_joues else 0

        # Matchs les plus serrés (3/2)
        nb_5sets = score_distrib.get("3/2", 0) + score_distrib.get("2/3", 0)
        # Matchs expéditifs (3/0)
        nb_3_0 = score_distrib.get("3/0", 0) + score_distrib.get("0/3", 0)

        entries = [
            ("📊 Matchs programmés", str(len(matchs))),
            ("✅ Matchs joués", str(nb_joues)),
            ("📋 Sets joués", str(total_sets)),
            ("📐 Moyenne sets/match", f"{avg_sets:.1f}"),
            ("🔥 Matchs en 5 sets", f"{nb_5sets} ({self._pct(nb_5sets, nb_joues)})"),
            ("💨 Matchs en 3-0", f"{nb_3_0} ({self._pct(nb_3_0, nb_joues)})"),
        ]

        # Score distribution table
        if score_distrib:
            dist_lines = [f"  • {score}: {count}" for score, count in score_distrib.most_common()]
            entries.append(("🎯 Distribution scores", "\n" + "\n".join(dist_lines)))

        self._add(ReportSection(
            key="statistiques", title="Statistiques",
            content=self._kv_panel(entries, title="📈 Statistiques", border_style="green"),
            order=25,
        ))

    def _section_matchs(self, c: CompetitionDB) -> None:
        matchs = sorted(c.matchs, key=lambda m: (m.date_match or "", m.heure_match or ""), reverse=True)
        if not matchs:
            self._add(ReportSection(key="matchs", title="Matchs", content="", order=30, empty=True))
            return

        tbl = Table(title=f"🏐 Matchs ({len(matchs)} total)", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Date", style="cyan", width=12)
        tbl.add_column("J.", justify="center", width=4)
        tbl.add_column("Équipe A", min_width=15)
        tbl.add_column("Score", justify="center", width=8)
        tbl.add_column("Équipe B", min_width=15)

        for m in matchs[:self.max_matchs]:
            eq_a = m.equipe_a.nom[:20] if m.equipe_a else "?"
            eq_b = m.equipe_b.nom[:20] if m.equipe_b else "?"
            tbl.add_row(
                self._safe(m.date_match),
                self._safe(m.journee),
                eq_a,
                self._safe(m.score_sets),
                eq_b,
            )
        if len(matchs) > self.max_matchs:
            tbl.add_row("...", "", f"({len(matchs) - self.max_matchs} autres)", "", "")

        self._add(ReportSection(key="matchs", title="Matchs", content=tbl, order=30))

    def _section_joueurs(self, c: CompetitionDB) -> None:
        """Top joueurs par nombre de matchs dans cette compétition."""
        match_ids = [m.id for m in c.matchs]
        if not match_ids:
            self._add(ReportSection(key="joueurs", title="Joueurs", content="", order=40, empty=True))
            return

        stmt = (
            select(
                JoueurDB.nom,
                JoueurDB.prenom,
                JoueurDB.licence,
                func.count(ParticipationMatchDB.id).label("nb_matchs"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .where(ParticipationMatchDB.match_id.in_(match_ids))
            .group_by(JoueurDB.id)
            .order_by(func.count(ParticipationMatchDB.id).desc())
            .limit(30)
        )
        rows = self.session.execute(stmt).all()
        if not rows:
            self._add(ReportSection(key="joueurs", title="Joueurs", content="", order=40, empty=True))
            return

        tbl = Table(title="👥 Top joueurs (par matchs joués)", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("#", justify="center", width=4)
        tbl.add_column("Nom", style="white", min_width=12)
        tbl.add_column("Prénom", style="white", min_width=10)
        tbl.add_column("Licence", style="dim", width=12)
        tbl.add_column("Matchs", justify="right", width=7)

        for i, (nom, prenom, licence, nb) in enumerate(rows, 1):
            tbl.add_row(str(i), nom, prenom, licence, str(nb))

        self._add(ReportSection(key="joueurs", title="Joueurs", content=tbl, order=40))
