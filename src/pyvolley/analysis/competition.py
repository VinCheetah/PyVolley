"""
Analyse d'une compétition ou d'une ligue.

Produit un classement des équipes, identifie les meilleurs serveurs, etc.
"""

from typing import Optional
from collections import defaultdict

from ..core.models import Match
from .models import CompetitionAnalysis, EquipeSeasonRecord, JoueurSeasonRecord
from .equipe import analyze_equipe
from .joueur import analyze_joueur_over_matches


def analyze_competition(
    matches: list[Match],
    competition_nom: Optional[str] = None,
    ligue: Optional[str] = None,
    saison: Optional[str] = None,
    top_serveurs: int = 10,
) -> CompetitionAnalysis:
    """
    Analyse une compétition ou une ligue.

    Filtre les matchs correspondants, puis produit un classement
    et les statistiques des meilleurs serveurs.

    Args:
        matches: Tous les matchs disponibles.
        competition_nom: Nom de la compétition (filtre partiel).
        ligue: Nom de la ligue (filtre partiel).
        saison: Filtre optionnel sur la saison.
        top_serveurs: Nombre de meilleurs serveurs à retourner.

    Returns:
        CompetitionAnalysis avec classement et top serveurs.
    """
    # Filtrer les matchs
    filtered = _filter_matches(matches, competition_nom, ligue, saison)

    # Identifier toutes les équipes participantes
    equipes_noms: set[str] = set()
    joueurs_licences: dict[str, tuple[str, str, str]] = {}  # licence -> (nom, prenom, equipe)

    for m in filtered:
        for side_label in ("A", "B"):
            eq = m.equipe(side_label)
            if eq:
                equipes_noms.add(eq.nom)
                for j in eq.joueurs:
                    if j.licence not in joueurs_licences:
                        joueurs_licences[j.licence] = (j.nom, j.prenom, eq.nom)

    # Classement des équipes
    classement: list[EquipeSeasonRecord] = []
    for eq_nom in sorted(equipes_noms):
        record = analyze_equipe(filtered, eq_nom, saison=saison, competition=competition_nom)
        classement.append(record)

    # Tri par victoires desc, puis ratio sets, puis ratio points
    classement.sort(
        key=lambda r: (r.victoires, r.ratio_sets, r.ratio_points),
        reverse=True,
    )

    # Top serveurs
    meilleurs: list[JoueurSeasonRecord] = []
    for lic in joueurs_licences:
        record = analyze_joueur_over_matches(filtered, lic)
        if record and record.total_tours_service > 0:
            meilleurs.append(record)

    meilleurs.sort(key=lambda r: r.total_points_service, reverse=True)
    meilleurs = meilleurs[:top_serveurs]

    comp_nom = competition_nom or ligue or "Tous les matchs"

    return CompetitionAnalysis(
        nom=comp_nom,
        saison=saison,
        ligue=ligue,
        nb_matchs=len(filtered),
        nb_equipes=len(equipes_noms),
        nb_joueurs=len(joueurs_licences),
        classement=classement,
        meilleurs_serveurs=meilleurs,
    )


def _filter_matches(
    matches: list[Match],
    competition_nom: Optional[str],
    ligue: Optional[str],
    saison: Optional[str],
) -> list[Match]:
    """Filtre les matchs selon les critères."""
    result: list[Match] = []
    for m in matches:
        if saison and m.saison != saison:
            continue
        if competition_nom and (
            not m.competition
            or competition_nom.upper() not in m.competition.upper()
        ):
            continue
        if ligue and (not m.ligue or ligue.upper() not in m.ligue.upper()):
            continue
        result.append(m)
    return result
