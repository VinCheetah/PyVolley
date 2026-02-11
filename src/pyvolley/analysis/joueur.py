"""
Analyse d'un joueur sur plusieurs matchs.

Fournit des statistiques agrégées pour un joueur :
temps de jeu, services, présence, performances sur la saison.
"""

from typing import Optional

from ..core.models import Match
from .models import JoueurSeasonRecord, JoueurMatchAnalysis
from .match import _analyze_joueur


def analyze_joueur_over_matches(
    matches: list[Match],
    licence: str,
) -> Optional[JoueurSeasonRecord]:
    """
    Analyse un joueur sur une liste de matchs.

    Args:
        matches: Liste de matchs auxquels le joueur a participé.
        licence: Numéro de licence du joueur.

    Returns:
        JoueurSeasonRecord ou None si le joueur n'est trouvé dans aucun match.
    """
    analyses: list[JoueurMatchAnalysis] = []
    equipe_nom = ""
    nom = ""
    prenom = ""

    for match in matches:
        joueur, side = _find_joueur_in_match(match, licence)
        if joueur is None or side is None:
            continue

        equipe = match.equipe(side)
        if equipe is None:
            continue

        equipe_nom = equipe.nom
        nom = joueur.nom
        prenom = joueur.prenom

        analysis = _analyze_joueur(match, equipe, joueur, side)
        analyses.append(analysis)

    if not analyses:
        return None

    # Agrégation
    total_sets = sum(a.sets_joues for a in analyses)
    total_titu = sum(a.sets_titulaire for a in analyses)
    total_tours = sum(a.services.nb_tours for a in analyses)
    total_pts = sum(a.services.points_marques for a in analyses)
    total_temps = sum(a.temps_jeu_estime or 0 for a in analyses)

    return JoueurSeasonRecord(
        nom=nom,
        prenom=prenom,
        licence=licence,
        equipe=equipe_nom,
        matchs_joues=len(analyses),
        sets_joues=total_sets,
        sets_titulaire=total_titu,
        temps_jeu_estime=round(total_temps, 1),
        total_tours_service=total_tours,
        total_points_service=total_pts,
        moyenne_points_par_tour=round(total_pts / total_tours, 2) if total_tours else 0.0,
    )


def _find_joueur_in_match(match: Match, licence: str):
    """Trouve un joueur dans un match par sa licence. Retourne (Joueur, side)."""
    for side_label in ("A", "B"):
        equipe = match.equipe(side_label)
        if equipe is None:
            continue
        for j in equipe.joueurs:
            if j.licence == licence:
                return j, side_label
    return None, None
