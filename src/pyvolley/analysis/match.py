"""
Analyse d'un match de volleyball.

Fournit une analyse complète d'un match à partir des données
extraites par le parser : sets, joueurs, services, changements, etc.
"""

from typing import Optional

from ..core.models import Match, Set, Equipe, SetTeamData, Joueur
from .models import (
    MatchAnalysis,
    SetAnalysis,
    JoueurMatchAnalysis,
    PresenceSet,
    ServiceStats,
)


def _norm(numero: Optional[str]) -> str:
    """Normalise un numéro de maillot pour la comparaison.

    Supprime les zéros en tête : '04' -> '4', '11' -> '11'.
    """
    if numero is None:
        return ""
    return numero.lstrip("0") or "0"


def analyze_match(match: Match) -> MatchAnalysis:
    """
    Produit une analyse complète d'un match.

    Args:
        match: Données du match (modèle Pydantic).

    Returns:
        MatchAnalysis contenant l'analyse de chaque set et de chaque joueur.
    """
    equipe_a_nom = match.equipe_a.nom if match.equipe_a else "Équipe A"
    equipe_b_nom = match.equipe_b.nom if match.equipe_b else "Équipe B"

    sets_analyses = [_analyze_set(s) for s in match.sets]

    joueurs_a = (
        _analyze_all_joueurs(match, match.equipe_a, "A") if match.equipe_a else []
    )
    joueurs_b = (
        _analyze_all_joueurs(match, match.equipe_b, "B") if match.equipe_b else []
    )

    total_ch_a = sum(s.nb_changements_a for s in sets_analyses)
    total_ch_b = sum(s.nb_changements_b for s in sets_analyses)
    total_to_a = sum(s.nb_timeouts_a for s in sets_analyses)
    total_to_b = sum(s.nb_timeouts_b for s in sets_analyses)

    return MatchAnalysis(
        code_match=match.code_match,
        date=match.date,
        lieu=match.lieu,
        competition=match.competition,
        equipe_a=equipe_a_nom,
        equipe_b=equipe_b_nom,
        vainqueur=match.vainqueur,
        score_sets=match.score_sets,
        sets_a=match.sets_a,
        sets_b=match.sets_b,
        duree_totale=match.duree_totale,
        sets=sets_analyses,
        joueurs_a=joueurs_a,
        joueurs_b=joueurs_b,
        total_changements_a=total_ch_a,
        total_changements_b=total_ch_b,
        total_timeouts_a=total_to_a,
        total_timeouts_b=total_to_b,
        total_sanctions=len(match.sanctions),
    )


# ── Analyse par set ────────────────────────────────────────────────

def _analyze_set(s: Set) -> SetAnalysis:
    """Analyse un set individuel."""
    td_a = s.equipe_a
    td_b = s.equipe_b

    formation_a = td_a.formation.as_list() if td_a.formation else None
    formation_b = td_b.formation.as_list() if td_b.formation else None

    return SetAnalysis(
        numero=s.numero,
        score=s.score_str,
        duree_minutes=s.duree_minutes,
        vainqueur=s.vainqueur,
        service_initial=s.service_initial,
        formation_a=formation_a,
        formation_b=formation_b,
        nb_changements_a=td_a.nb_changements,
        nb_changements_b=td_b.nb_changements,
        nb_timeouts_a=td_a.nb_timeouts,
        nb_timeouts_b=td_b.nb_timeouts,
        nb_tours_service_a=td_a.nb_services,
        nb_tours_service_b=td_b.nb_services,
    )


# ── Analyse joueurs ───────────────────────────────────────────────

def _analyze_all_joueurs(
    match: Match, equipe: Equipe, side: str
) -> list[JoueurMatchAnalysis]:
    """Analyse tous les joueurs d'une équipe."""
    return [_analyze_joueur(match, equipe, joueur, side) for joueur in equipe.joueurs]


def _analyze_joueur(
    match: Match, equipe: Equipe, joueur: Joueur, side: str
) -> JoueurMatchAnalysis:
    """Analyse un joueur lors du match."""
    presence_par_set = _compute_presence(match, joueur, side)
    services = _compute_service_stats(match, joueur, side)
    temps_estime = _estimate_play_time(match, joueur, presence_par_set)
    nb_entrees, nb_sorties = _count_changements(match, joueur, side)
    sanctions = _collect_sanctions(match, joueur, side)

    sets_joues = sum(1 for p in presence_par_set if p.titulaire or p.entre_en_jeu)
    sets_titulaire = sum(1 for p in presence_par_set if p.titulaire)

    return JoueurMatchAnalysis(
        numero=joueur.numero,
        nom=joueur.nom,
        prenom=joueur.prenom,
        licence=joueur.licence,
        equipe=equipe.nom,
        est_libero=joueur.est_libero,
        est_capitaine=joueur.est_capitaine,
        sets_joues=sets_joues,
        sets_titulaire=sets_titulaire,
        presence_par_set=presence_par_set,
        services=services,
        temps_jeu_estime=temps_estime,
        nb_entrees=nb_entrees,
        nb_sorties=nb_sorties,
        sanctions=sanctions,
    )


# ── Présence ───────────────────────────────────────────────────────

def _compute_presence(
    match: Match, joueur: Joueur, side: str
) -> list[PresenceSet]:
    """Calcule la présence d'un joueur sur chaque set."""
    result: list[PresenceSet] = []

    for s in match.sets:
        td = s.team_data(side)
        titulaire = _is_in_formation(td, joueur.numero)
        entre = False
        sorti = False
        pos_depart: Optional[int] = None
        score_entree: Optional[str] = None
        score_sortie: Optional[str] = None

        if titulaire and td.formation:
            pos_depart = _position_in_formation(td, joueur.numero)

        for ch in td.changements:
            if _norm(ch.joueur_entrant) == _norm(joueur.numero):
                entre = True
                if ch.score_a is not None and ch.score_b is not None:
                    score_entree = f"{ch.score_a}-{ch.score_b}"
            if _norm(ch.joueur_sortant) == _norm(joueur.numero):
                sorti = True
                if ch.score_a is not None and ch.score_b is not None:
                    score_sortie = f"{ch.score_a}-{ch.score_b}"

        result.append(
            PresenceSet(
                set_numero=s.numero,
                titulaire=titulaire,
                entre_en_jeu=entre,
                sorti=sorti,
                position_depart=pos_depart,
                score_entree=score_entree,
                score_sortie=score_sortie,
            )
        )

    return result


def _is_in_formation(td: SetTeamData, numero: str) -> bool:
    """Vérifie si un joueur est dans la formation de départ."""
    if not td.formation:
        return False
    n = _norm(numero)
    return any(_norm(p) == n for p in td.formation.as_list())


def _position_in_formation(td: SetTeamData, numero: str) -> Optional[int]:
    """Retourne la position (1-6) d'un joueur dans la formation."""
    if not td.formation:
        return None
    n = _norm(numero)
    for i, p in enumerate(td.formation.as_list()):
        if _norm(p) == n:
            return i + 1
    return None


# ── Services ──────────────────────────────────────────────────────

def _compute_service_stats(
    match: Match, joueur: Joueur, side: str
) -> ServiceStats:
    """Calcule les statistiques de service pour un joueur.

    Les services sont stockés par position. On doit donc trouver
    dans quelle position le joueur était au moment du service.

    Pour simplifier : on associe les services d'une position à un joueur
    s'il occupait cette position dans la formation de départ (ou via changement).
    """
    nb_tours = 0
    points_marques = 0
    detail: dict[int, list[int]] = {}

    for s in match.sets:
        td = s.team_data(side)
        positions_joueur = _get_joueur_positions(td, joueur.numero)

        set_scores: list[int] = []
        for pos in positions_joueur:
            if pos in td.services:
                scores = td.services[pos]
                nb_tours += len(scores)
                set_scores.extend(scores)
                # Calculer les points marqués au service
                # Le score représente le score de l'équipe quand le service est perdu.
                # On doit estimer combien de points ont été gagnés pendant ce passage.
                points_marques += _compute_service_points(
                    td, pos, scores, s, side
                )

        if set_scores:
            detail[s.numero] = set_scores

    return ServiceStats(
        nb_tours=nb_tours,
        points_marques=points_marques,
        detail_par_set=detail,
    )


def _get_joueur_positions(td: SetTeamData, numero: str) -> list[int]:
    """Retourne les positions occupées par un joueur pendant un set.

    Prend en compte la formation de départ et les changements.
    """
    positions: set[int] = set()

    # Position dans la formation de départ
    if td.formation:
        pos_list = td.formation.as_list()
        n = _norm(numero)
        for i, num in enumerate(pos_list):
            if _norm(num) == n:
                positions.add(i + 1)

    # Vérifier les changements (le joueur remplace quelqu'un à une position)
    for ch in td.changements:
        if _norm(ch.joueur_entrant) == _norm(numero) and ch.position:
            positions.add(ch.position)

    return sorted(positions)


def _compute_service_points(
    td: SetTeamData,
    position: int,
    scores: list[int],
    s: Set,
    side: str,
) -> int:
    """Estime les points marqués au service pour une position donnée.

    Le score dans services est le score de l'équipe au moment où
    le service est PERDU. Les points marqués pendant ce tour sont la
    différence entre ce score et le score au début du tour de service.

    Pour le premier tour de service d'une position, le score de départ
    dépend de l'ordre de passage au service (rotation).
    On utilise une heuristique : si on connaît les scores successifs,
    la différence entre le score de perte et le score de perte précédent
    de la position donne un intervalle.

    Approche simplifiée : on ordonne toutes les valeurs de service
    pour reconstituer la succession et calculer les écarts.
    """
    # Collecte de tous les passages au service de l'équipe (toutes positions)
    all_serves: list[tuple[int, int, int]] = []  # (score_perte, position, tour)
    for pos, sc_list in td.services.items():
        for tour_idx, score_val in enumerate(sc_list):
            all_serves.append((score_val, pos, tour_idx))

    if not all_serves:
        return 0

    # Tri par score croissant pour reconstituer l'ordre chronologique
    all_serves.sort(key=lambda x: (x[0], x[1]))

    total = 0
    prev_score = 0  # Le score de l'équipe au début du match est 0

    for score_perte, pos, tour_idx in all_serves:
        if pos == position and tour_idx < len(scores) and scores[tour_idx] == score_perte:
            # Points marqués = score à la perte - score au début du tour
            points = max(0, score_perte - prev_score)
            total += points
        prev_score = score_perte

    return total


# ── Changements ───────────────────────────────────────────────────

def _count_changements(
    match: Match, joueur: Joueur, side: str
) -> tuple[int, int]:
    """Compte le nombre de remplacements entrants/sortants."""
    entrees = 0
    sorties = 0
    for s in match.sets:
        td = s.team_data(side)
        for ch in td.changements:
            if _norm(ch.joueur_entrant) == _norm(joueur.numero):
                entrees += 1
            if _norm(ch.joueur_sortant) == _norm(joueur.numero):
                sorties += 1
    return entrees, sorties


# ── Sanctions ─────────────────────────────────────────────────────

def _collect_sanctions(
    match: Match, joueur: Joueur, side: str
) -> list[str]:
    """Collecte les sanctions reçues par un joueur."""
    result: list[str] = []
    side_letter = side  # "A" ou "B"
    for sanction in match.sanctions:
        if sanction.equipe == side_letter and sanction.joueur_numero == joueur.numero:
            score_str = ""
            if sanction.score_a is not None and sanction.score_b is not None:
                score_str = f", {sanction.score_a}-{sanction.score_b}"
            result.append(
                f"{sanction.type.value} (set {sanction.set_numero}{score_str})"
            )
    return result


# ── Temps de jeu estimé ──────────────────────────────────────────

def _estimate_play_time(
    match: Match,
    joueur: Joueur,
    presence: list[PresenceSet],
) -> Optional[float]:
    """Estime le temps de jeu d'un joueur en minutes.

    Heuristique :
    - Si le joueur est titulaire et n'est jamais sorti sur un set,
      il joue toute la durée du set.
    - Si le joueur entre en jeu ou sort, on estime proportionnellement
      via le score au moment du changement et le score final du set.
    - Si aucune durée de set n'est disponible, on ne peut pas estimer.
    """
    total_minutes = 0.0
    any_duration = False

    for p in presence:
        s = _get_set_by_numero(match, p.set_numero)
        if not s or s.duree_minutes is None:
            continue

        duree = float(s.duree_minutes)

        if not (p.titulaire or p.entre_en_jeu):
            # Le joueur n'a pas joué ce set
            continue

        any_duration = True
        score_final = (s.score_a or 0) + (s.score_b or 0)
        if score_final == 0:
            score_final = 1  # Éviter division par zéro

        if p.titulaire and not p.sorti:
            # Joue tout le set
            total_minutes += duree
        elif p.titulaire and p.sorti:
            # Sorti en cours de set
            score_sortie = _parse_score_sum(p.score_sortie)
            ratio = score_sortie / score_final if score_sortie else 0.5
            total_minutes += duree * ratio
        elif p.entre_en_jeu and not p.sorti:
            # Entré en cours de set et resté jusqu'à la fin
            score_entree = _parse_score_sum(p.score_entree)
            ratio = 1.0 - (score_entree / score_final if score_entree else 0.5)
            total_minutes += duree * ratio
        elif p.entre_en_jeu and p.sorti:
            # Entré puis sorti
            score_entree = _parse_score_sum(p.score_entree)
            score_sortie = _parse_score_sum(p.score_sortie)
            if score_entree is not None and score_sortie is not None:
                ratio = (score_sortie - score_entree) / score_final
            else:
                ratio = 0.25
            total_minutes += duree * max(0.0, ratio)

    return round(total_minutes, 1) if any_duration else None


def _parse_score_sum(score_str: Optional[str]) -> Optional[int]:
    """Parse '15-12' en 27 (somme des deux scores)."""
    if not score_str:
        return None
    parts = score_str.split("-")
    if len(parts) == 2:
        try:
            return int(parts[0]) + int(parts[1])
        except ValueError:
            return None
    return None


def _get_set_by_numero(match: Match, numero: int) -> Optional[Set]:
    """Retourne un set par son numéro."""
    for s in match.sets:
        if s.numero == numero:
            return s
    return None
