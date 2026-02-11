"""
Analyse d'une équipe / club sur une série de matchs.

Fournit le bilan wins/losses, ratio de sets, joueurs utilisés, etc.
"""

from typing import Optional

from ..core.models import Match
from .models import EquipeSeasonRecord


def analyze_equipe(
    matches: list[Match],
    equipe_nom: str,
    saison: Optional[str] = None,
    competition: Optional[str] = None,
) -> EquipeSeasonRecord:
    """
    Analyse les résultats d'une équipe sur une liste de matchs.

    Args:
        matches: Tous les matchs à considérer.
        equipe_nom: Nom de l'équipe (recherche partielle insensible à la casse).
        saison: Filtre optionnel sur la saison.
        competition: Filtre optionnel sur la compétition.

    Returns:
        EquipeSeasonRecord avec le bilan complet.
    """
    # Filtrage
    relevant: list[tuple[Match, str]] = []
    for m in matches:
        side = m.side_of(equipe_nom)
        if side is None:
            continue
        if saison and m.saison != saison:
            continue
        if competition and m.competition and competition.upper() not in m.competition.upper():
            continue
        relevant.append((m, side))

    victoires = 0
    defaites = 0
    sets_g = 0
    sets_p = 0
    pts_marques = 0
    pts_encaisses = 0
    plus_large_v: Optional[str] = None
    plus_large_d: Optional[str] = None
    max_v_diff = -1
    max_d_diff = -1
    joueurs_set: set[str] = set()

    for m, side in relevant:
        opp = "B" if side == "A" else "A"
        sa = m.sets_a if side == "A" else m.sets_b
        sb = m.sets_b if side == "A" else m.sets_a

        if sa > sb:
            victoires += 1
            diff = sa - sb
            if diff > max_v_diff:
                max_v_diff = diff
                opp_equipe = m.equipe(opp)
                opp_nom = opp_equipe.nom if opp_equipe else "?"
                plus_large_v = f"{sa}-{sb} vs {opp_nom}"
        elif sb > sa:
            defaites += 1
            diff = sb - sa
            if diff > max_d_diff:
                max_d_diff = diff
                opp_equipe = m.equipe(opp)
                opp_nom = opp_equipe.nom if opp_equipe else "?"
                plus_large_d = f"{sa}-{sb} vs {opp_nom}"

        sets_g += sa
        sets_p += sb

        # Points par set
        for s in m.sets:
            sc_us = s.score_a if side == "A" else s.score_b
            sc_them = s.score_b if side == "A" else s.score_a
            if sc_us is not None:
                pts_marques += sc_us
            if sc_them is not None:
                pts_encaisses += sc_them

        # Joueurs utilisés
        equipe_obj = m.equipe(side)
        if equipe_obj:
            for j in equipe_obj.joueurs:
                joueurs_set.add(j.licence)

    matchs_joues = len(relevant)
    ratio_v = round(victoires / matchs_joues, 3) if matchs_joues else 0.0
    ratio_s = round(sets_g / sets_p, 3) if sets_p else 0.0
    ratio_p = round(pts_marques / pts_encaisses, 3) if pts_encaisses else 0.0

    # Joueur le plus présent (par nombre de matchs)
    joueur_presence: dict[str, int] = {}
    joueur_noms: dict[str, str] = {}
    for m, side in relevant:
        equipe_obj = m.equipe(side)
        if equipe_obj:
            for j in equipe_obj.joueurs:
                joueur_presence[j.licence] = joueur_presence.get(j.licence, 0) + 1
                joueur_noms[j.licence] = j.nom_complet

    plus_present = None
    if joueur_presence:
        best_lic = max(joueur_presence, key=joueur_presence.get)  # type: ignore
        plus_present = f"{joueur_noms[best_lic]} ({joueur_presence[best_lic]} matchs)"

    return EquipeSeasonRecord(
        equipe=equipe_nom,
        saison=saison,
        competition=competition,
        matchs_joues=matchs_joues,
        victoires=victoires,
        defaites=defaites,
        ratio_victoires=ratio_v,
        sets_gagnes=sets_g,
        sets_perdus=sets_p,
        ratio_sets=ratio_s,
        points_marques=pts_marques,
        points_encaisses=pts_encaisses,
        ratio_points=ratio_p,
        plus_large_victoire=plus_large_v,
        plus_large_defaite=plus_large_d,
        joueurs_utilises=len(joueurs_set),
        joueur_plus_present=plus_present,
    )
