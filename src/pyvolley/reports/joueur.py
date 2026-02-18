"""Rapport détaillé d'un joueur."""

from __future__ import annotations

from collections import Counter
from typing import Optional

from sqlalchemy import select, func, or_
from rich.panel import Panel
from rich.table import Table
from rich import box

from .base import Report, ReportSection
from ..database.models import (
    JoueurDB, ParticipationMatchDB, MatchDB, EquipeDB, SetDB,
    ClubDB, SaisonDB, CompetitionDB, ArbitreMatchDB, ArbitreDB,
)


class JoueurReport(Report):
    """Rapport complet pour un joueur.

    Sections disponibles :
        profil       – Informations d'identité
        statistiques – Nombre de matchs, sets, victoires…
        equipes      – Équipes dans lesquelles le joueur a joué
        matchs       – Liste des derniers matchs
        coequipiers  – Coéquipiers les plus fréquents
        adversaires  – Adversaires les plus fréquents
        capitainats  – Matchs en tant que capitaine
    """

    def __init__(self, session, joueur: JoueurDB, *, max_matchs: int = 20, **kwargs):
        super().__init__(session, **kwargs)
        self.joueur = joueur
        self.max_matchs = max_matchs

    def _build_sections(self) -> None:
        j = self.joueur
        self._section_profil(j)
        self._section_statistiques(j)
        self._section_equipes(j)
        self._section_matchs(j)
        self._section_coequipiers(j)
        self._section_adversaires(j)
        self._section_capitainats(j)

    # ── Sections ────────────────────────────────────────────────

    def _section_profil(self, j: JoueurDB) -> None:
        content = (
            f"[bold cyan]{j.nom} {j.prenom}[/bold cyan]\n\n"
            f"📋 Licence: {self._safe(j.licence)}\n"
            f"🆔 ID: {j.id}"
        )
        self._add(ReportSection(
            key="profil",
            title="Profil",
            content=Panel(content, title="👤 Profil joueur", border_style="blue"),
            order=0,
        ))

    def _section_statistiques(self, j: JoueurDB) -> None:
        nb_matchs = self.session.scalar(
            select(func.count()).select_from(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == j.id)
        ) or 0

        nb_capitaine = self.session.scalar(
            select(func.count()).select_from(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == j.id, ParticipationMatchDB.est_capitaine == True)
        ) or 0

        nb_libero = self.session.scalar(
            select(func.count()).select_from(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == j.id, ParticipationMatchDB.est_libero == True)
        ) or 0

        # Victoires / défaites via jointure (évite N+1)
        participations = list(self.session.execute(
            select(
                ParticipationMatchDB.equipe_id,
                MatchDB.equipe_a_id,
                MatchDB.equipe_b_id,
                MatchDB.vainqueur,
                MatchDB.equipe_a.has(),  # just need equipe names
            )
            .join(MatchDB, ParticipationMatchDB.match_id == MatchDB.id)
            .where(ParticipationMatchDB.joueur_id == j.id)
        ).all())

        # Fall back to ORM for winner resolution
        orm_participations = list(self.session.scalars(
            select(ParticipationMatchDB).where(ParticipationMatchDB.joueur_id == j.id)
        ))
        victoires = 0
        defaites = 0
        nuls = 0
        saisons_set: set[str] = set()
        for p in orm_participations:
            m = p.match
            if not m:
                continue
            if m.saison:
                saisons_set.add(m.saison.code)
            if not m.vainqueur:
                nuls += 1
                continue
            eq_nom = p.equipe.nom if p.equipe else None
            if eq_nom and m.vainqueur == eq_nom:
                victoires += 1
            else:
                defaites += 1

        items = [
            ("🏐 Matchs joués", str(nb_matchs)),
            ("✅ Victoires", str(victoires)),
            ("❌ Défaites", str(defaites)),
            ("➖ Non décidés", str(nuls)),
            ("📈 Taux de victoire", self._pct(victoires, nb_matchs)),
            ("©️ Capitainats", str(nb_capitaine)),
            ("🛡️ Matchs en libéro", str(nb_libero)),
            ("📅 Saisons", str(len(saisons_set))),
        ]
        content = "\n".join(f"{label}  {val}" for label, val in items)
        self._add(ReportSection(
            key="statistiques",
            title="Statistiques",
            content=Panel(content, title="📊 Statistiques", border_style="green"),
            order=10,
            empty=nb_matchs == 0,
        ))

    def _section_equipes(self, j: JoueurDB) -> None:
        rows_data = list(self.session.execute(
            select(
                EquipeDB.nom,
                ClubDB.nom,
                EquipeDB.categorie,
                EquipeDB.genre,
                SaisonDB.code,
                func.count(ParticipationMatchDB.id).label("nb"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.equipe_id == EquipeDB.id)
            .outerjoin(ClubDB, EquipeDB.club_id == ClubDB.id)
            .outerjoin(SaisonDB, EquipeDB.saison_id == SaisonDB.id)
            .where(ParticipationMatchDB.joueur_id == j.id)
            .group_by(EquipeDB.id, ClubDB.nom, SaisonDB.code)
            .order_by(SaisonDB.code.desc().nullslast())
        ).all())

        if not rows_data:
            self._add(ReportSection(key="equipes", title="Équipes", content="", order=20, empty=True))
            return

        tbl = Table(title="🏠 Équipes", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Équipe", style="white", min_width=20)
        tbl.add_column("Club", style="cyan", min_width=15)
        tbl.add_column("Catégorie", style="dim")
        tbl.add_column("Genre", style="dim")
        tbl.add_column("Saison", style="yellow")
        tbl.add_column("Matchs", style="green", justify="right")

        for eq_nom, club_nom, cat, genre, saison, nb in rows_data:
            tbl.add_row(
                eq_nom or "-", club_nom or "-", cat or "-",
                genre or "-", saison or "-", str(nb),
            )
        self._add(ReportSection(key="equipes", title="Équipes", content=tbl, order=20))

    def _section_matchs(self, j: JoueurDB) -> None:
        stmt = (
            select(ParticipationMatchDB)
            .where(ParticipationMatchDB.joueur_id == j.id)
            .join(MatchDB)
            .order_by(MatchDB.date_match.desc().nullslast())
            .limit(self.max_matchs)
        )
        participations = list(self.session.scalars(stmt))

        if not participations:
            self._add(ReportSection(key="matchs", title="Matchs", content="", order=30, empty=True))
            return

        tbl = Table(
            title=f"🏐 Derniers matchs ({len(participations)} max {self.max_matchs})",
            box=box.SIMPLE, row_styles=["", "dim"],
        )
        tbl.add_column("Date", style="yellow", width=12)
        tbl.add_column("Code", style="cyan", width=12)
        tbl.add_column("Équipe", style="white", max_width=22, overflow="ellipsis")
        tbl.add_column("Adversaire", style="white", max_width=22, overflow="ellipsis")
        tbl.add_column("Score", style="green", justify="center", width=7)
        tbl.add_column("N°", justify="center", width=4)
        tbl.add_column("Rôle", style="dim", width=8)

        for p in participations:
            m = p.match
            if p.equipe_id == m.equipe_a_id:
                equipe_nom = m.equipe_a.nom if m.equipe_a else "?"
                adversaire = m.equipe_b.nom if m.equipe_b else "?"
            else:
                equipe_nom = m.equipe_b.nom if m.equipe_b else "?"
                adversaire = m.equipe_a.nom if m.equipe_a else "?"

            roles = []
            if p.est_capitaine:
                roles.append("C")
            if p.est_libero:
                roles.append("L")

            tbl.add_row(
                str(m.date_match) if m.date_match else "-",
                self._safe(m.code_match),
                equipe_nom,
                adversaire,
                self._safe(m.score_sets),
                self._safe(p.numero_maillot),
                " ".join(roles) or "-",
            )
        self._add(ReportSection(key="matchs", title="Matchs", content=tbl, order=30))

    def _section_coequipiers(self, j: JoueurDB) -> None:
        """Coéquipiers les plus fréquents."""
        from sqlalchemy.orm import aliased
        p2 = aliased(ParticipationMatchDB)

        rows = list(self.session.execute(
            select(
                JoueurDB.nom,
                JoueurDB.prenom,
                JoueurDB.licence,
                func.count().label("nb"),
            )
            .join(p2, p2.joueur_id == JoueurDB.id)
            .join(ParticipationMatchDB,
                  (ParticipationMatchDB.match_id == p2.match_id) &
                  (ParticipationMatchDB.equipe_id == p2.equipe_id))
            .where(
                ParticipationMatchDB.joueur_id == j.id,
                JoueurDB.id != j.id,
            )
            .group_by(JoueurDB.id)
            .order_by(func.count().desc())
            .limit(10)
        ).all())

        if not rows:
            self._add(ReportSection(key="coequipiers", title="Coéquipiers", content="", order=40, empty=True))
            return

        tbl = Table(title="🤝 Coéquipiers les plus fréquents", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Nom", style="white", min_width=15)
        tbl.add_column("Prénom", style="white", min_width=10)
        tbl.add_column("Licence", style="dim", width=10)
        tbl.add_column("Matchs ensemble", style="green", justify="right")

        for nom, prenom, licence, nb in rows:
            tbl.add_row(nom, prenom, licence, str(nb))

        self._add(ReportSection(key="coequipiers", title="Coéquipiers", content=tbl, order=40))

    def _section_adversaires(self, j: JoueurDB) -> None:
        """Équipes adverses les plus rencontrées."""
        # Pour chaque participation, l'adversaire est l'autre équipe du match
        participations = list(self.session.scalars(
            select(ParticipationMatchDB).where(ParticipationMatchDB.joueur_id == j.id)
        ))

        adversaire_count: dict[str, int] = {}
        for p in participations:
            m = p.match
            if not m:
                continue
            if p.equipe_id == m.equipe_a_id and m.equipe_b:
                adv = m.equipe_b.nom
            elif m.equipe_a:
                adv = m.equipe_a.nom
            else:
                continue
            adversaire_count[adv] = adversaire_count.get(adv, 0) + 1

        if not adversaire_count:
            self._add(ReportSection(key="adversaires", title="Adversaires", content="", order=50, empty=True))
            return

        sorted_adv = sorted(adversaire_count.items(), key=lambda x: -x[1])[:10]

        tbl = Table(title="⚔️ Adversaires les plus fréquents", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Équipe adverse", style="white", min_width=20)
        tbl.add_column("Rencontres", style="green", justify="right")

        for nom, nb in sorted_adv:
            tbl.add_row(nom, str(nb))

        self._add(ReportSection(key="adversaires", title="Adversaires", content=tbl, order=50))

    def _section_capitainats(self, j: JoueurDB) -> None:
        """Matchs en capitaine."""
        stmt = (
            select(ParticipationMatchDB)
            .where(
                ParticipationMatchDB.joueur_id == j.id,
                ParticipationMatchDB.est_capitaine == True,
            )
            .join(MatchDB)
            .order_by(MatchDB.date_match.desc().nullslast())
            .limit(10)
        )
        caps = list(self.session.scalars(stmt))

        if not caps:
            self._add(ReportSection(key="capitainats", title="Capitainats", content="", order=60, empty=True))
            return

        tbl = Table(title="©️ Matchs en tant que capitaine", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Date", style="yellow", width=12)
        tbl.add_column("Code", style="cyan", width=12)
        tbl.add_column("Équipe", style="white")
        tbl.add_column("Score", style="green", justify="center", width=7)

        for p in caps:
            m = p.match
            eq = p.equipe.nom if p.equipe else "?"
            tbl.add_row(
                str(m.date_match) if m and m.date_match else "-",
                self._safe(m.code_match) if m else "-",
                eq,
                self._safe(m.score_sets) if m else "-",
            )
        self._add(ReportSection(key="capitainats", title="Capitainats", content=tbl, order=60))
