"""Rapport détaillé d'une équipe."""

from __future__ import annotations

from sqlalchemy import select, func, or_
from rich.panel import Panel
from rich.table import Table
from rich import box

from .base import Report, ReportSection
from ..database.models import (
    EquipeDB, ClubDB, MatchDB, ParticipationMatchDB,
    JoueurDB, SaisonDB, CompetitionDB, SetDB,
)


class EquipeReport(Report):
    """Rapport complet pour une équipe.

    Sections :
        profil      – Nom, club, saison, catégorie
        effectif    – Liste des joueurs
        bilan       – V/D et statistiques
        matchs      – Liste des matchs joués
        classement  – Joueurs par nombre de matchs
    """

    def __init__(self, session, equipe: EquipeDB, *, max_matchs: int = 30, **kwargs):
        super().__init__(session, **kwargs)
        self.equipe = equipe
        self.max_matchs = max_matchs

    def _build_sections(self) -> None:
        e = self.equipe
        self._section_profil(e)
        self._section_bilan(e)
        self._section_effectif(e)
        self._section_matchs(e)

    def _section_profil(self, e: EquipeDB) -> None:
        club_nom = e.club.nom if e.club else "-"
        saison = e.saison.code if e.saison else "-"
        content = (
            f"[bold cyan]{e.nom}[/bold cyan]\n\n"
            f"🆔 ID: {e.id}\n"
            f"🏠 Club: {club_nom}\n"
            f"📅 Saison: {saison}\n"
            f"👤 Genre: {e.genre or '-'}\n"
            f"📋 Catégorie: {e.categorie or '-'}\n"
            f"#️⃣ N° équipe: {e.numero_equipe or '-'}"
        )
        self._add(ReportSection(
            key="profil", title="Profil",
            content=Panel(content, title="👥 Équipe", border_style="blue"),
            order=0,
        ))

    def _section_bilan(self, e: EquipeDB) -> None:
        matchs = list(self.session.scalars(
            select(MatchDB).where(
                or_(MatchDB.equipe_a_id == e.id, MatchDB.equipe_b_id == e.id)
            )
        ))
        total = len(matchs)
        victoires = 0
        defaites = 0
        sets_gagnes = 0
        sets_perdus = 0

        for m in matchs:
            if not m.vainqueur:
                continue
            is_a = m.equipe_a_id == e.id
            if is_a:
                sets_gagnes += m.sets_equipe_a
                sets_perdus += m.sets_equipe_b
                if m.equipe_a and m.vainqueur == m.equipe_a.nom:
                    victoires += 1
                else:
                    defaites += 1
            else:
                sets_gagnes += m.sets_equipe_b
                sets_perdus += m.sets_equipe_a
                if m.equipe_b and m.vainqueur == m.equipe_b.nom:
                    victoires += 1
                else:
                    defaites += 1

        taux = f"{victoires / total * 100:.0f}%" if total > 0 else "-"
        content = (
            f"🏐 Total matchs: {total}\n"
            f"✅ Victoires: {victoires}\n"
            f"❌ Défaites: {defaites}\n"
            f"📈 Taux de victoire: {taux}\n"
            f"📊 Sets: {sets_gagnes} gagnés / {sets_perdus} perdus\n"
            f"📉 Ratio sets: {sets_gagnes / sets_perdus:.2f}" if sets_perdus > 0 else
            f"🏐 Total matchs: {total}\n"
            f"✅ Victoires: {victoires}\n"
            f"❌ Défaites: {defaites}\n"
            f"📈 Taux de victoire: {taux}\n"
            f"📊 Sets: {sets_gagnes} gagnés / {sets_perdus} perdus"
        )
        self._add(ReportSection(
            key="bilan", title="Bilan",
            content=Panel(content, title="📊 Bilan", border_style="green"),
            order=10, empty=total == 0,
        ))

    def _section_effectif(self, e: EquipeDB) -> None:
        rows = list(self.session.execute(
            select(
                JoueurDB.nom,
                JoueurDB.prenom,
                JoueurDB.licence,
                func.count(ParticipationMatchDB.id).label("nb"),
                func.max(ParticipationMatchDB.numero_maillot).label("maillot"),
                func.sum(func.cast(ParticipationMatchDB.est_capitaine, type_=func.count().type)).label("caps"),
                func.sum(func.cast(ParticipationMatchDB.est_libero, type_=func.count().type)).label("libs"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .where(ParticipationMatchDB.equipe_id == e.id)
            .group_by(JoueurDB.id)
            .order_by(func.count(ParticipationMatchDB.id).desc())
        ).all())

        if not rows:
            self._add(ReportSection(key="effectif", title="Effectif", content="", order=20, empty=True))
            return

        tbl = Table(title=f"👤 Effectif ({len(rows)} joueurs)", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Nom", style="white", min_width=15)
        tbl.add_column("Prénom", style="white", min_width=10)
        tbl.add_column("Licence", style="dim", width=10)
        tbl.add_column("N°", justify="center", width=4)
        tbl.add_column("Matchs", style="green", justify="right", width=7)
        tbl.add_column("Rôle", style="cyan", width=8)

        for nom, prenom, licence, nb, maillot, caps, libs in rows:
            role = []
            if caps and int(caps) > 0:
                role.append("C")
            if libs and int(libs) > 0:
                role.append("L")
            tbl.add_row(nom, prenom, licence, maillot or "-", str(nb), " ".join(role) or "-")

        self._add(ReportSection(key="effectif", title="Effectif", content=tbl, order=20))

    def _section_matchs(self, e: EquipeDB) -> None:
        matchs = list(self.session.scalars(
            select(MatchDB).where(
                or_(MatchDB.equipe_a_id == e.id, MatchDB.equipe_b_id == e.id)
            )
            .order_by(MatchDB.date_match.desc().nullslast())
            .limit(self.max_matchs)
        ))

        if not matchs:
            self._add(ReportSection(key="matchs", title="Matchs", content="", order=30, empty=True))
            return

        tbl = Table(title=f"🏐 Matchs ({len(matchs)})", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Date", style="yellow", width=12)
        tbl.add_column("Code", style="cyan", width=12)
        tbl.add_column("Adversaire", style="white", max_width=25, overflow="ellipsis")
        tbl.add_column("Score", style="green", justify="center", width=7)
        tbl.add_column("Résultat", style="bold", justify="center", width=8)
        tbl.add_column("Lieu", style="dim", max_width=15, overflow="ellipsis")

        for m in matchs:
            is_a = m.equipe_a_id == e.id
            adversaire = (m.equipe_b.nom if m.equipe_b else "?") if is_a else (m.equipe_a.nom if m.equipe_a else "?")

            resultat = "-"
            if m.vainqueur:
                own_nom = (m.equipe_a.nom if m.equipe_a else "") if is_a else (m.equipe_b.nom if m.equipe_b else "")
                if m.vainqueur == own_nom:
                    resultat = "[green]V[/green]"
                else:
                    resultat = "[red]D[/red]"

            domicile = "D" if is_a else "E"
            tbl.add_row(
                str(m.date_match) if m.date_match else "-",
                m.code_match,
                adversaire,
                m.score_sets or "-",
                resultat,
                f"{m.lieu or '-'} ({domicile})",
            )
        self._add(ReportSection(key="matchs", title="Matchs", content=tbl, order=30))
