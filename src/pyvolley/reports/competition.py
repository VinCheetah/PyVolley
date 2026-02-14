"""Rapport détaillé d'une compétition."""

from __future__ import annotations

from collections import Counter
from sqlalchemy import select, func

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
        profil    – Identité de la compétition
        poules    – Liste des poules
        classement – Classement des équipes (V/D)
        matchs    – Liste des matchs
        joueurs   – Statistiques joueurs
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
        self._section_matchs(c)
        self._section_joueurs(c)

    def _section_profil(self, c: CompetitionDB) -> None:
        entries = [
            ("Nom", c.nom),
            ("Code", c.code_competition or "-"),
            ("Saison", c.saison.code if c.saison else "-"),
            ("Entité", f"{c.entite.nom} ({c.entite.code})" if c.entite else "-"),
            ("Genre", c.genre or "-"),
            ("Catégorie", c.categorie or "-"),
            ("Division", c.division or "-"),
            ("Niveau", c.niveau or "-"),
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
                m.date_match or "-",
                m.journee or "-",
                eq_a,
                m.score_sets or "-",
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
