"""Rapport détaillé d'un club."""

from __future__ import annotations

from sqlalchemy import select, func
from rich.panel import Panel
from rich.table import Table
from rich import box

from .base import Report, ReportSection
from ..database.models import (
    ClubDB, ClubAliasDB, EquipeDB, MatchDB, ParticipationMatchDB,
    JoueurDB, SaisonDB,
)


class ClubReport(Report):
    """Rapport complet pour un club.

    Sections :
        profil      – Nom, code, ville, aliases
        equipes     – Équipes du club par saison
        joueurs     – Joueurs ayant joué pour ce club
        bilan       – Victoires / défaites globales
        saisons     – Résumé par saison
    """

    def __init__(self, session, club: ClubDB, **kwargs):
        super().__init__(session, **kwargs)
        self.club = club

    def _build_sections(self) -> None:
        c = self.club
        self._section_profil(c)
        self._section_equipes(c)
        self._section_bilan(c)
        self._section_joueurs(c)
        self._section_saisons(c)

    def _section_profil(self, c: ClubDB) -> None:
        aliases = list(self.session.scalars(
            select(ClubAliasDB.alias).where(ClubAliasDB.club_id == c.id)
        ))
        alias_str = ", ".join(aliases) if aliases else "-"

        content = (
            f"[bold cyan]{c.nom}[/bold cyan]\n\n"
            f"🆔 ID: {c.id}\n"
            f"📋 Code FFVB: {c.code_ffvb or '-'}\n"
            f"🏙️ Ville: {c.ville or '-'}\n"
            f"📮 Département: {c.departement or '-'}\n"
            f"📝 Nom court: {c.nom_court or '-'}\n"
            f"🔗 Aliases: {alias_str}"
        )
        self._add(ReportSection(
            key="profil", title="Profil",
            content=Panel(content, title="🏠 Club", border_style="blue"),
            order=0,
        ))

    def _section_equipes(self, c: ClubDB) -> None:
        rows = list(self.session.execute(
            select(
                EquipeDB.nom,
                EquipeDB.genre,
                EquipeDB.categorie,
                SaisonDB.code,
                func.count(func.distinct(ParticipationMatchDB.joueur_id)).label("nb_joueurs"),
            )
            .outerjoin(SaisonDB, EquipeDB.saison_id == SaisonDB.id)
            .outerjoin(ParticipationMatchDB, ParticipationMatchDB.equipe_id == EquipeDB.id)
            .where(EquipeDB.club_id == c.id)
            .group_by(EquipeDB.id, SaisonDB.code)
            .order_by(SaisonDB.code.desc().nullslast(), EquipeDB.nom)
        ).all())

        if not rows:
            self._add(ReportSection(key="equipes", title="Équipes", content="", order=10, empty=True))
            return

        tbl = Table(title="👥 Équipes du club", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Équipe", style="white", min_width=20)
        tbl.add_column("Genre", style="dim", width=10)
        tbl.add_column("Catégorie", style="dim", width=10)
        tbl.add_column("Saison", style="yellow", width=12)
        tbl.add_column("Joueurs", style="green", justify="right", width=8)

        for nom, genre, cat, saison, nb_j in rows:
            tbl.add_row(nom or "-", genre or "-", cat or "-", saison or "-", str(nb_j))

        self._add(ReportSection(key="equipes", title="Équipes", content=tbl, order=10))

    def _section_bilan(self, c: ClubDB) -> None:
        """Bilan victoires/défaites de toutes les équipes du club."""
        equipe_ids = list(self.session.scalars(
            select(EquipeDB.id).where(EquipeDB.club_id == c.id)
        ))
        if not equipe_ids:
            self._add(ReportSection(key="bilan", title="Bilan", content="", order=20, empty=True))
            return

        from sqlalchemy import or_
        matchs = list(self.session.scalars(
            select(MatchDB).where(
                or_(
                    MatchDB.equipe_a_id.in_(equipe_ids),
                    MatchDB.equipe_b_id.in_(equipe_ids),
                )
            )
        ))

        total = len(matchs)
        victoires = 0
        defaites = 0
        nuls = 0
        equipe_id_set = set(equipe_ids)

        for m in matchs:
            if not m.vainqueur:
                nuls += 1
                continue
            # Déterminer si c'est une victoire
            is_a = m.equipe_a_id in equipe_id_set
            is_b = m.equipe_b_id in equipe_id_set
            vainq_nom = m.vainqueur
            eq_a_nom = m.equipe_a.nom if m.equipe_a else None
            eq_b_nom = m.equipe_b.nom if m.equipe_b else None

            if is_a and vainq_nom == eq_a_nom:
                victoires += 1
            elif is_b and vainq_nom == eq_b_nom:
                victoires += 1
            else:
                defaites += 1

        taux = f"{victoires / total * 100:.0f}%" if total > 0 else "-"
        content = (
            f"🏐 Total matchs: {total}\n"
            f"✅ Victoires: {victoires}\n"
            f"❌ Défaites: {defaites}\n"
            f"➖ Non décidés: {nuls}\n"
            f"📈 Taux de victoire: {taux}"
        )
        self._add(ReportSection(
            key="bilan", title="Bilan",
            content=Panel(content, title="📊 Bilan global", border_style="green"),
            order=20, empty=total == 0,
        ))

    def _section_joueurs(self, c: ClubDB) -> None:
        """Joueurs ayant joué pour le club (top 20 par matchs)."""
        equipe_ids = list(self.session.scalars(
            select(EquipeDB.id).where(EquipeDB.club_id == c.id)
        ))
        if not equipe_ids:
            self._add(ReportSection(key="joueurs", title="Joueurs", content="", order=30, empty=True))
            return

        rows = list(self.session.execute(
            select(
                JoueurDB.nom,
                JoueurDB.prenom,
                JoueurDB.licence,
                func.count(ParticipationMatchDB.id).label("nb"),
            )
            .join(ParticipationMatchDB, ParticipationMatchDB.joueur_id == JoueurDB.id)
            .where(ParticipationMatchDB.equipe_id.in_(equipe_ids))
            .group_by(JoueurDB.id)
            .order_by(func.count(ParticipationMatchDB.id).desc())
            .limit(20)
        ).all())

        if not rows:
            self._add(ReportSection(key="joueurs", title="Joueurs", content="", order=30, empty=True))
            return

        tbl = Table(title="👤 Joueurs du club (top 20)", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Nom", style="white", min_width=15)
        tbl.add_column("Prénom", style="white", min_width=10)
        tbl.add_column("Licence", style="dim", width=10)
        tbl.add_column("Matchs", style="green", justify="right", width=7)

        for nom, prenom, licence, nb in rows:
            tbl.add_row(nom, prenom, licence, str(nb))

        self._add(ReportSection(key="joueurs", title="Joueurs", content=tbl, order=30))

    def _section_saisons(self, c: ClubDB) -> None:
        """Résumé par saison."""
        equipe_ids_by_saison = list(self.session.execute(
            select(
                SaisonDB.code,
                func.count(func.distinct(EquipeDB.id)),
            )
            .join(EquipeDB, EquipeDB.saison_id == SaisonDB.id)
            .where(EquipeDB.club_id == c.id)
            .group_by(SaisonDB.id)
            .order_by(SaisonDB.code.desc())
        ).all())

        if not equipe_ids_by_saison:
            self._add(ReportSection(key="saisons", title="Saisons", content="", order=40, empty=True))
            return

        tbl = Table(title="📅 Saisons", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Saison", style="yellow", width=12)
        tbl.add_column("Équipes", style="green", justify="right", width=8)

        for code, nb_eq in equipe_ids_by_saison:
            tbl.add_row(code or "-", str(nb_eq))

        self._add(ReportSection(key="saisons", title="Saisons", content=tbl, order=40))
