"""Rapport détaillé d'une saison."""

from __future__ import annotations

from collections import Counter
from sqlalchemy import select, func

from rich.table import Table
from rich import box

from .base import Report, ReportSection
from ..database.models import (
    SaisonDB, CompetitionDB, MatchDB, EquipeDB, ClubDB,
    ParticipationMatchDB, JoueurDB, ArbitreMatchDB, ArbitreDB,
)


class SaisonReport(Report):
    """Rapport complet pour une saison.

    Sections :
        profil       – Info de la saison
        competitions – Compétitions de la saison
        bilan        – Statistiques globales
        clubs        – Clubs actifs
        joueurs      – Top joueurs
        arbitres     – Top arbitres
    """

    def __init__(self, session, saison: SaisonDB, **kwargs):
        super().__init__(session, **kwargs)
        self.saison = saison

    def _build_sections(self) -> None:
        s = self.saison
        self._section_profil(s)
        self._section_competitions(s)
        self._section_bilan(s)
        self._section_clubs(s)
        self._section_joueurs(s)
        self._section_arbitres(s)

    def _section_profil(self, s: SaisonDB) -> None:
        entries = [
            ("Code", s.code),
            ("Nom", s.nom or "-"),
            ("Début", str(s.date_debut) if s.date_debut else "-"),
            ("Fin", str(s.date_fin) if s.date_fin else "-"),
            ("Compétitions", str(len(s.competitions))),
            ("Matchs", str(len(s.matchs))),
            ("Équipes", str(len(s.equipes))),
        ]
        self._add(ReportSection(
            key="profil", title="Profil",
            content=self._kv_panel(entries, title=f"📅 Saison {s.code}"),
            order=0,
        ))

    def _section_competitions(self, s: SaisonDB) -> None:
        if not s.competitions:
            self._add(ReportSection(key="competitions", title="Compétitions", content="", order=10, empty=True))
            return

        tbl = Table(title="🏆 Compétitions", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Code", style="cyan", width=12)
        tbl.add_column("Nom", min_width=20)
        tbl.add_column("Genre", width=8)
        tbl.add_column("Catégorie", width=10)
        tbl.add_column("Entité", width=12)
        tbl.add_column("Matchs", justify="right", width=7)
        tbl.add_column("Poules", justify="right", width=7)

        for c in sorted(s.competitions, key=lambda x: x.nom):
            tbl.add_row(
                c.code_competition or "-",
                c.nom[:40],
                c.genre or "-",
                c.categorie or "-",
                c.entite.code if c.entite else "-",
                str(len(c.matchs)),
                str(len(c.poules)),
            )

        self._add(ReportSection(key="competitions", title="Compétitions", content=tbl, order=10))

    def _section_bilan(self, s: SaisonDB) -> None:
        matchs = s.matchs
        nb_matchs = len(matchs)
        nb_joues = sum(1 for m in matchs if m.is_played)
        nb_competitions = len(s.competitions)
        nb_equipes = len(s.equipes)

        # Nombre de joueurs uniques
        match_ids = [m.id for m in matchs]
        if match_ids:
            nb_joueurs_stmt = (
                select(func.count(func.distinct(ParticipationMatchDB.joueur_id)))
                .where(ParticipationMatchDB.match_id.in_(match_ids))
            )
            nb_joueurs = self.session.execute(nb_joueurs_stmt).scalar() or 0

            nb_arbitres_stmt = (
                select(func.count(func.distinct(ArbitreMatchDB.arbitre_id)))
                .where(ArbitreMatchDB.match_id.in_(match_ids))
            )
            nb_arbitres = self.session.execute(nb_arbitres_stmt).scalar() or 0
        else:
            nb_joueurs = 0
            nb_arbitres = 0

        entries = [
            ("Matchs total", str(nb_matchs)),
            ("Matchs joués", str(nb_joues)),
            ("Compétitions", str(nb_competitions)),
            ("Équipes", str(nb_equipes)),
            ("Joueurs uniques", str(nb_joueurs)),
            ("Arbitres", str(nb_arbitres)),
        ]
        self._add(ReportSection(
            key="bilan", title="Bilan",
            content=self._kv_panel(entries, title="📊 Bilan global"),
            order=20,
        ))

    def _section_clubs(self, s: SaisonDB) -> None:
        """Clubs actifs dans la saison (via leurs équipes)."""
        equipes = s.equipes
        if not equipes:
            self._add(ReportSection(key="clubs", title="Clubs", content="", order=30, empty=True))
            return

        club_equipes: dict[int, dict] = {}
        for e in equipes:
            if e.club_id:
                if e.club_id not in club_equipes:
                    club_equipes[e.club_id] = {
                        "nom": e.club.nom if e.club else "?",
                        "code": e.club.code_ffvb if e.club else "-",
                        "equipes": [],
                    }
                club_equipes[e.club_id]["equipes"].append(e.nom)
            else:
                key = hash(e.nom)
                if key not in club_equipes:
                    club_equipes[key] = {"nom": e.nom, "code": "-", "equipes": []}
                club_equipes[key]["equipes"].append(e.nom)

        tbl = Table(title=f"🏟️ Clubs ({len(club_equipes)})", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("Club", style="white", min_width=20)
        tbl.add_column("Code", style="dim", width=10)
        tbl.add_column("Éq.", justify="right", width=5)

        for data in sorted(club_equipes.values(), key=lambda x: x["nom"]):
            tbl.add_row(data["nom"], data["code"], str(len(data["equipes"])))

        self._add(ReportSection(key="clubs", title="Clubs", content=tbl, order=30))

    def _section_joueurs(self, s: SaisonDB) -> None:
        """Top 20 joueurs par nombre de matchs dans la saison."""
        match_ids = [m.id for m in s.matchs]
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
            .limit(20)
        )
        rows = self.session.execute(stmt).all()
        if not rows:
            self._add(ReportSection(key="joueurs", title="Joueurs", content="", order=40, empty=True))
            return

        tbl = Table(title="👥 Top 20 joueurs", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("#", justify="center", width=4)
        tbl.add_column("Nom", style="white", min_width=12)
        tbl.add_column("Prénom", style="white", min_width=10)
        tbl.add_column("Licence", style="dim", width=12)
        tbl.add_column("Matchs", justify="right", width=7)

        for i, (nom, prenom, licence, nb) in enumerate(rows, 1):
            tbl.add_row(str(i), nom, prenom, licence, str(nb))

        self._add(ReportSection(key="joueurs", title="Joueurs", content=tbl, order=40))

    def _section_arbitres(self, s: SaisonDB) -> None:
        """Top 20 arbitres par nombre de matchs dans la saison."""
        match_ids = [m.id for m in s.matchs]
        if not match_ids:
            self._add(ReportSection(key="arbitres", title="Arbitres", content="", order=50, empty=True))
            return

        stmt = (
            select(
                ArbitreDB.nom_complet,
                ArbitreDB.licence,
                ArbitreDB.ligue,
                func.count(ArbitreMatchDB.id).label("nb_matchs"),
            )
            .join(ArbitreMatchDB, ArbitreMatchDB.arbitre_id == ArbitreDB.id)
            .where(ArbitreMatchDB.match_id.in_(match_ids))
            .group_by(ArbitreDB.id)
            .order_by(func.count(ArbitreMatchDB.id).desc())
            .limit(20)
        )
        rows = self.session.execute(stmt).all()
        if not rows:
            self._add(ReportSection(key="arbitres", title="Arbitres", content="", order=50, empty=True))
            return

        tbl = Table(title="🧑‍⚖️ Top 20 arbitres", box=box.SIMPLE, row_styles=["", "dim"])
        tbl.add_column("#", justify="center", width=4)
        tbl.add_column("Nom", style="white", min_width=15)
        tbl.add_column("Licence", style="dim", width=12)
        tbl.add_column("Ligue", style="dim", width=10)
        tbl.add_column("Matchs", justify="right", width=7)

        for i, (nom, licence, ligue, nb) in enumerate(rows, 1):
            tbl.add_row(str(i), nom, licence or "-", ligue or "-", str(nb))

        self._add(ReportSection(key="arbitres", title="Arbitres", content=tbl, order=50))
