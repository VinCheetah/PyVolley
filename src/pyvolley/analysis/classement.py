"""
Service de calcul de classement pour les compétitions de volleyball.

Calcule le classement selon les règles FFVB :
  - Victoire 3-0 ou 3-1 : 3 points pour le vainqueur, 0 pour le perdant
  - Victoire 3-2 : 2 points pour le vainqueur, 1 pour le perdant
  - Forfait : 3-0 pour le vainqueur, 0 pour le perdant

Le classement est ordonné par : points > ratio de sets > ratio de points.

Fournit aussi l'évolution du classement par journée/date pour visualiser
la progression des équipes au fil de la saison.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as dt_date
from typing import Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
# Modèles de sortie
# ═══════════════════════════════════════════════════════════════════

class LigneClassement(BaseModel):
    """Ligne du classement pour une équipe."""
    rang: int = 0
    equipe_id: int
    equipe_nom: str
    points: int = 0
    matchs_joues: int = 0
    victoires: int = 0
    victoires_3_0: int = 0
    victoires_3_1: int = 0
    victoires_3_2: int = 0
    defaites: int = 0
    defaites_0_3: int = 0
    defaites_1_3: int = 0
    defaites_2_3: int = 0
    sets_gagnes: int = 0
    sets_perdus: int = 0
    points_marques: int = 0
    points_encaisses: int = 0
    serie: list[str] = Field(default_factory=list)  # ["V", "V", "D", "V", ...]

    @property
    def ratio_sets(self) -> float:
        """Ratio de sets gagnés/perdus."""
        if self.sets_perdus == 0:
            return float(self.sets_gagnes) if self.sets_gagnes > 0 else 0.0
        return self.sets_gagnes / self.sets_perdus

    @property
    def ratio_points(self) -> float:
        """Ratio de points marqués/encaissés."""
        if self.points_encaisses == 0:
            return float(self.points_marques) if self.points_marques > 0 else 0.0
        return self.points_marques / self.points_encaisses

    @property
    def diff_sets(self) -> int:
        return self.sets_gagnes - self.sets_perdus

    @property
    def diff_points(self) -> int:
        return self.points_marques - self.points_encaisses

    @property
    def taux_victoire(self) -> float:
        if self.matchs_joues == 0:
            return 0.0
        return self.victoires / self.matchs_joues * 100


class EvolutionJournee(BaseModel):
    """Évolution du classement pour une journée donnée."""
    journee: str
    date: Optional[str] = None
    classement: list[LigneClassement] = Field(default_factory=list)


class ClassementComplet(BaseModel):
    """Classement complet avec évolution pour une compétition."""
    competition_id: int
    competition_nom: str
    saison: Optional[str] = None
    genre: Optional[str] = None
    categorie: Optional[str] = None
    niveau: Optional[str] = None
    division: Optional[str] = None
    organisateur: Optional[str] = None
    nb_equipes: int = 0
    nb_matchs_joues: int = 0
    nb_matchs_total: int = 0
    classement_actuel: list[LigneClassement] = Field(default_factory=list)
    evolution: list[EvolutionJournee] = Field(default_factory=list)
    journees: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# Structures internes de calcul
# ═══════════════════════════════════════════════════════════════════

@dataclass
class _EquipeStats:
    """Accumulateur interne pour les stats d'une équipe."""
    equipe_id: int
    equipe_nom: str
    points: int = 0
    matchs_joues: int = 0
    victoires: int = 0
    victoires_3_0: int = 0
    victoires_3_1: int = 0
    victoires_3_2: int = 0
    defaites: int = 0
    defaites_0_3: int = 0
    defaites_1_3: int = 0
    defaites_2_3: int = 0
    sets_gagnes: int = 0
    sets_perdus: int = 0
    points_marques: int = 0
    points_encaisses: int = 0
    serie: list[str] = field(default_factory=list)

    def to_ligne(self, rang: int = 0) -> LigneClassement:
        return LigneClassement(
            rang=rang,
            equipe_id=self.equipe_id,
            equipe_nom=self.equipe_nom,
            points=self.points,
            matchs_joues=self.matchs_joues,
            victoires=self.victoires,
            victoires_3_0=self.victoires_3_0,
            victoires_3_1=self.victoires_3_1,
            victoires_3_2=self.victoires_3_2,
            defaites=self.defaites,
            defaites_0_3=self.defaites_0_3,
            defaites_1_3=self.defaites_1_3,
            defaites_2_3=self.defaites_2_3,
            sets_gagnes=self.sets_gagnes,
            sets_perdus=self.sets_perdus,
            points_marques=self.points_marques,
            points_encaisses=self.points_encaisses,
            serie=list(self.serie),
        )

    def copy(self) -> _EquipeStats:
        return _EquipeStats(
            equipe_id=self.equipe_id,
            equipe_nom=self.equipe_nom,
            points=self.points,
            matchs_joues=self.matchs_joues,
            victoires=self.victoires,
            victoires_3_0=self.victoires_3_0,
            victoires_3_1=self.victoires_3_1,
            victoires_3_2=self.victoires_3_2,
            defaites=self.defaites,
            defaites_0_3=self.defaites_0_3,
            defaites_1_3=self.defaites_1_3,
            defaites_2_3=self.defaites_2_3,
            sets_gagnes=self.sets_gagnes,
            sets_perdus=self.sets_perdus,
            points_marques=self.points_marques,
            points_encaisses=self.points_encaisses,
            serie=list(self.serie),
        )


# ═══════════════════════════════════════════════════════════════════
# Service de calcul
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MatchData:
    """Représentation légère d'un match pour le calcul de classement.

    Peut être construit à partir d'un MatchDB ou de données brutes.
    """
    match_id: int
    equipe_a_id: int
    equipe_a_nom: str
    equipe_b_id: int
    equipe_b_nom: str
    sets_a: int
    sets_b: int
    points_a: int = 0  # Total des points marqués par A (somme des scores de sets)
    points_b: int = 0  # Total des points marqués par B
    journee: Optional[str] = None
    date_match: Optional[dt_date] = None
    match_joue: bool = True


def calculer_classement(
    matchs: list[MatchData],
) -> list[LigneClassement]:
    """
    Calcule le classement à partir d'une liste de matchs.

    Args:
        matchs: Liste de MatchData (matchs joués).

    Returns:
        Liste de LigneClassement triée par rang.
    """
    stats = _accumuler_stats(matchs)
    return _classer(stats)


def calculer_classement_complet(
    matchs: list[MatchData],
    competition_id: int,
    competition_nom: str,
    saison: Optional[str] = None,
    genre: Optional[str] = None,
    categorie: Optional[str] = None,
    niveau: Optional[str] = None,
    division: Optional[str] = None,
    organisateur: Optional[str] = None,
) -> ClassementComplet:
    """
    Calcule le classement avec l'évolution par journée.

    Les matchs sont regroupés par journée (ou par date si pas de journée).
    Le classement est recalculé après chaque journée pour tracer l'évolution.

    Args:
        matchs: Tous les matchs de la compétition.
        competition_id: ID de la compétition.
        competition_nom: Nom de la compétition.
        saison, genre, categorie, niveau, division, organisateur:
            Métadonnées d'identification de la compétition.

    Returns:
        ClassementComplet avec classement actuel et évolution.
    """
    matchs_joues = [m for m in matchs if m.match_joue and (m.sets_a > 0 or m.sets_b > 0)]
    matchs_non_joues = [m for m in matchs if not m.match_joue or (m.sets_a == 0 and m.sets_b == 0)]

    # Classement actuel
    classement_actuel = calculer_classement(matchs_joues)

    # Grouper par journée pour l'évolution
    journees_matchs = _grouper_par_journee(matchs_joues)
    journees = list(journees_matchs.keys())
    evolution: list[EvolutionJournee] = []

    # Calculer l'évolution cumulative
    matchs_cumules: list[MatchData] = []
    for journee in journees:
        matchs_cumules.extend(journees_matchs[journee])
        classement_journee = calculer_classement(matchs_cumules)
        # Date de la journée = dernière date des matchs de cette journée
        dates = [m.date_match for m in journees_matchs[journee] if m.date_match]
        date_str = max(dates).isoformat() if dates else None
        evolution.append(EvolutionJournee(
            journee=journee,
            date=date_str,
            classement=classement_journee,
        ))

    # Collecter toutes les équipes (y compris celles sans matchs joués)
    equipe_ids = set()
    for m in matchs:
        equipe_ids.add(m.equipe_a_id)
        equipe_ids.add(m.equipe_b_id)

    return ClassementComplet(
        competition_id=competition_id,
        competition_nom=competition_nom,
        saison=saison,
        genre=genre,
        categorie=categorie,
        niveau=niveau,
        division=division,
        organisateur=organisateur,
        nb_equipes=len(equipe_ids) if equipe_ids else len(classement_actuel),
        nb_matchs_joues=len(matchs_joues),
        nb_matchs_total=len(matchs),
        classement_actuel=classement_actuel,
        evolution=evolution,
        journees=journees,
    )


# ═══════════════════════════════════════════════════════════════════
# Fonctions internes
# ═══════════════════════════════════════════════════════════════════

def _accumuler_stats(matchs: list[MatchData]) -> dict[int, _EquipeStats]:
    """Accumule les statistiques pour chaque équipe."""
    stats: dict[int, _EquipeStats] = {}

    for m in matchs:
        if not m.match_joue:
            continue

        # Initialiser si nécessaire
        if m.equipe_a_id not in stats:
            stats[m.equipe_a_id] = _EquipeStats(
                equipe_id=m.equipe_a_id, equipe_nom=m.equipe_a_nom
            )
        if m.equipe_b_id not in stats:
            stats[m.equipe_b_id] = _EquipeStats(
                equipe_id=m.equipe_b_id, equipe_nom=m.equipe_b_nom
            )

        sa = stats[m.equipe_a_id]
        sb = stats[m.equipe_b_id]

        sa.matchs_joues += 1
        sb.matchs_joues += 1

        sa.sets_gagnes += m.sets_a
        sa.sets_perdus += m.sets_b
        sb.sets_gagnes += m.sets_b
        sb.sets_perdus += m.sets_a

        sa.points_marques += m.points_a
        sa.points_encaisses += m.points_b
        sb.points_marques += m.points_b
        sb.points_encaisses += m.points_a

        # Déterminer le vainqueur et attribuer les points
        if m.sets_a > m.sets_b:
            # A gagne
            _attribuer_victoire(sa, sb, m.sets_a, m.sets_b)
        elif m.sets_b > m.sets_a:
            # B gagne
            _attribuer_victoire(sb, sa, m.sets_b, m.sets_a)

    return stats


def _attribuer_victoire(
    vainqueur: _EquipeStats,
    perdant: _EquipeStats,
    sets_v: int,
    sets_p: int,
) -> None:
    """Attribue les points FFVB selon le score en sets."""
    vainqueur.victoires += 1
    perdant.defaites += 1
    vainqueur.serie.append("V")
    perdant.serie.append("D")

    if sets_v == 3 and sets_p == 0:
        vainqueur.points += 3
        perdant.points += 0
        vainqueur.victoires_3_0 += 1
        perdant.defaites_0_3 += 1
    elif sets_v == 3 and sets_p == 1:
        vainqueur.points += 3
        perdant.points += 0
        vainqueur.victoires_3_1 += 1
        perdant.defaites_1_3 += 1
    elif sets_v == 3 and sets_p == 2:
        vainqueur.points += 2
        perdant.points += 1
        vainqueur.victoires_3_2 += 1
        perdant.defaites_2_3 += 1
    else:
        # Score non standard (ex: forfait 2-0, etc.)
        vainqueur.points += 3
        perdant.points += 0


def _classer(stats: dict[int, _EquipeStats]) -> list[LigneClassement]:
    """Trie et attribue les rangs."""
    # Tri : points desc, ratio sets desc, ratio points desc
    sorted_stats = sorted(
        stats.values(),
        key=lambda s: (
            s.points,
            s.sets_gagnes / s.sets_perdus if s.sets_perdus > 0 else float('inf') if s.sets_gagnes > 0 else 0,
            s.points_marques / s.points_encaisses if s.points_encaisses > 0 else float('inf') if s.points_marques > 0 else 0,
        ),
        reverse=True,
    )

    result = []
    for i, s in enumerate(sorted_stats, start=1):
        result.append(s.to_ligne(rang=i))
    return result


def _grouper_par_journee(matchs: list[MatchData]) -> dict[str, list[MatchData]]:
    """Groupe les matchs par journée, triées chronologiquement.

    Si les matchs n'ont pas de journée, on groupe par date.
    """
    groups: dict[str, list[MatchData]] = defaultdict(list)

    for m in matchs:
        key = m.journee or (m.date_match.isoformat() if m.date_match else "Inconnue")
        groups[key].append(m)

    # Trier les journées
    def sort_key(j: str) -> tuple:
        """Trie les journées numériquement si possible, sinon par date/alpha."""
        # Essayer d'extraire un numéro de journée (ex: "J1", "Journée 2", "1")
        import re
        num_match = re.search(r"(\d+)", j)
        if num_match:
            return (0, int(num_match.group(1)), j)
        # Sinon tri alphabétique (les dates ISO trient naturellement)
        return (1, 0, j)

    sorted_keys = sorted(groups.keys(), key=sort_key)
    return {k: groups[k] for k in sorted_keys}
