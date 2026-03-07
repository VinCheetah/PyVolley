"""Rapport détaillé d'une équipe."""

from __future__ import annotations

from collections import Counter
from sqlalchemy import select, func, or_, case
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
        tendance    – Forme récente et séries
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
        self._section_tendance(e)

    def _section_profil(self, e: EquipeDB) -> None:
        club_nom = e.club.nom if e.club else "-"
        saison = e.saison.code if e.saison else "-"
        content = (
            f"[bold cyan]{e.nom}[/bold cyan]\n\n"
            f"🆔 ID: {e.id}\n"
            f"🏠 Club: {club_nom}\n"
            f"📅 Saison: {saison}\n"
            f"👤 Genre: {self._safe(e.genre)}\n"
            f"📋 Catégorie: {self._safe(e.categorie)}\n"
            f"#️⃣ N° équipe: {self._safe(e.numero_equipe)}"
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
        nuls = 0
        sets_gagnes = 0
        sets_perdus = 0
        domicile_v = 0
        domicile_d = 0
        exterieur_v = 0
        exterieur_d = 0

        for m in matchs:
            is_a = m.equipe_a_id == e.id
            own_sets = m.sets_equipe_a if is_a else m.sets_equipe_b
            opp_sets = m.sets_equipe_b if is_a else m.sets_equipe_a
            sets_gagnes += own_sets or 0
            sets_perdus += opp_sets or 0

            if not m.vainqueur:
                nuls += 1
                continue
            own_nom = (m.equipe_a.nom if m.equipe_a else "") if is_a else (m.equipe_b.nom if m.equipe_b else "")
            if m.vainqueur == own_nom:
                victoires += 1
                if is_a:
                    domicile_v += 1
                else:
                    exterieur_v += 1
            else:
                defaites += 1
                if is_a:
                    domicile_d += 1
                else:
                    exterieur_d += 1

        items = [
            ("🏐 Total matchs", str(total)),
            ("✅ Victoires", str(victoires)),
            ("❌ Défaites", str(defaites)),
            ("➖ Non décidés", str(nuls)),
            ("📈 Taux de victoire", self._pct(victoires, total)),
            ("📊 Sets gagnés/perdus", f"{sets_gagnes}/{sets_perdus}"),
            ("📉 Ratio sets", self._ratio(sets_gagnes, sets_perdus)),
            ("🏠 Domicile", f"{domicile_v}V / {domicile_d}D ({self._pct(domicile_v, domicile_v + domicile_d)})"),
            ("✈️  Extérieur", f"{exterieur_v}V / {exterieur_d}D ({self._pct(exterieur_v, exterieur_v + exterieur_d)})"),
        ]
        content = "\n".join(f"{label}  {val}" for label, val in items)
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
                func.sum(case(
                    (ParticipationMatchDB.est_capitaine == True, 1),
                    else_=0,
                )).label("caps"),
                func.sum(case(
                    (ParticipationMatchDB.est_libero == True, 1),
                    else_=0,
                )).label("libs"),
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
        tbl.add_column("Salle", style="dim", max_width=15, overflow="ellipsis")

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
                f"{m.salle or '-'} ({domicile})",
            )
        self._add(ReportSection(key="matchs", title="Matchs", content=tbl, order=30))

    def _section_tendance(self, e: EquipeDB) -> None:
        """Forme récente et séries de l'équipe."""
        matchs = list(self.session.scalars(
            select(MatchDB).where(
                or_(MatchDB.equipe_a_id == e.id, MatchDB.equipe_b_id == e.id),
                MatchDB.vainqueur.isnot(None),
            )
            .order_by(MatchDB.date_match.desc().nullslast())
        ))
        if not matchs:
            self._add(ReportSection(key="tendance", title="Tendance", content="", order=35, empty=True))
            return

        # Compute results
        results = []
        for m in matchs:
            is_a = m.equipe_a_id == e.id
            own_nom = (m.equipe_a.nom if m.equipe_a else "") if is_a else (m.equipe_b.nom if m.equipe_b else "")
            won = m.vainqueur == own_nom
            results.append(won)

        # Current streak
        if results:
            streak_type = results[0]
            streak_count = 0
            for r in results:
                if r == streak_type:
                    streak_count += 1
                else:
                    break
            streak_str = f"{'🟢' * min(streak_count, 10)} {streak_count} {'victoire' if streak_type else 'défaite'}{'s' if streak_count > 1 else ''}"
        else:
            streak_str = "-"

        # Last 5 form
        last5 = results[:5]
        form_str = " ".join("🟢" if w else "🔴" for w in last5)
        last5_wins = sum(1 for w in last5 if w)

        # Best winning streak
        best_win_streak = 0
        current = 0
        for r in results:
            if r:
                current += 1
                best_win_streak = max(best_win_streak, current)
            else:
                current = 0

        items = [
            ("🔥 Série actuelle", streak_str),
            ("📊 Forme (5 derniers)", f"{form_str}  ({last5_wins}V / {len(last5) - last5_wins}D)"),
            ("🏆 Meilleure série V", f"{best_win_streak} victoire{'s' if best_win_streak > 1 else ''}"),
        ]
        content = "\n".join(f"{label}  {val}" for label, val in items)
        self._add(ReportSection(
            key="tendance", title="Tendance",
            content=Panel(content, title="📈 Forme & tendance", border_style="yellow"),
            order=35,
        ))
