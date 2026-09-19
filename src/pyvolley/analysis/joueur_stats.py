"""
Statistiques détaillées d'un joueur sur un match.

Reconstruction EXACTE du déroulement du set à partir des données
de la feuille de match FFVB :

- ``services: dict[int, list[int]]`` = score cumulé de l'équipe à la
  fin de chaque tour de service par position (I-VI).  La dernière valeur
  enregistrée pour l'équipe qui gagne le set correspond au score de
  victoire (ex. 25) et **n'est pas** une perte de service.
- ``formation`` = composition de départ (position 1 = serveur).
- ``changements`` = remplacements avec scores exacts (score_a, score_b).
- ``timeouts`` = temps morts avec scores exacts.
- ``service_initial`` = équipe qui sert en premier (``"A"`` ou ``"B"``).

L'ordre de service suit la rotation standard : 1, 2, 3, 4, 5, 6, 1, …
L'équipe qui reçoit en premier sert d'abord en position 2 (rotation
avant le premier service après un side-out).

Le calcul des points au service tient compte du fait que chaque
valeur dans ``services`` est le score **cumulé** de l'équipe : la
différence entre deux valeurs consécutives pour la même équipe
comprend à la fois les points marqués au service **et** le point de
side-out gagné entre temps.  Les points réellement marqués au
service lors d'un tour i sont :

- Équipe servante en premier, tour 0 : ``entry[0]``
- Tours suivants : ``entry[i] − entry[i−1] − 1``
"""

from dataclasses import dataclass
from typing import Optional

from ..core.models import Match, Set, SetTeamData, Joueur
from .models import (
    JoueurMatchDetailedStats,
    JoueurStatsAggregated,
    PresenceSet,
    ServiceSetDetail,
    PositionRotationStats,
    RotationStats,
    ClutchStats,
)
from .role_inference import infer_team_roles
def _norm(numero: Optional[str]) -> str:
    """Normalise un numéro de maillot pour comparaison robuste."""
    if numero is None:
        return ""
    return numero.lstrip("0") or "0"


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


# ══════════════════════════════════════════════════════════════════
#  Data-classes internes pour la timeline
# ══════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class ServiceTurn:
    """Un tour de service reconstruit."""
    team: str            # "A" ou "B"
    position: int        # Position de la formation (1-6) qui sert
    score_a_start: int   # Score A au début du tour
    score_b_start: int   # Score B au début du tour
    score_a_end: int     # Score A à la fin du tour
    score_b_end: int     # Score B à la fin du tour
    points_scored: int   # Points marqués par le serveur pendant ce tour
    is_set_winner: bool = False  # Dernier tour du set (victoire, pas de side-out)


@dataclass(slots=True)
class PresenceInterval:
    """Intervalle de présence d'un joueur sur le terrain."""
    score_a_in: int
    score_b_in: int
    score_a_out: int
    score_b_out: int

    @property
    def points_total(self) -> int:
        return (self.score_a_out + self.score_b_out) - (self.score_a_in + self.score_b_in)

    def team_points(self, side: str) -> int:
        if side == "A":
            return self.score_a_out - self.score_a_in
        return self.score_b_out - self.score_b_in

    def opp_points(self, side: str) -> int:
        if side == "A":
            return self.score_b_out - self.score_b_in
        return self.score_a_out - self.score_a_in


# ══════════════════════════════════════════════════════════════════
#  Reconstruction de la timeline d'un set
# ══════════════════════════════════════════════════════════════════

def _team_service_flat(
    services: dict[int, list[int]],
    starts_serving: bool,
) -> list[tuple[int, int]]:
    """Liste ordonnée ``(position, score_cumulé)`` des tours de service.

    L'ordre de rotation est 1→2→3→4→5→6→1… pour l'équipe au service
    en premier, et 2→3→4→5→6→1→2… pour l'équipe en réception.
    """
    rotation = [1, 2, 3, 4, 5, 6] if starts_serving else [2, 3, 4, 5, 6, 1]

    consumed: dict[int, int] = {p: 0 for p in range(1, 7)}
    result: list[tuple[int, int]] = []

    while True:
        found = False
        for pos in rotation:
            if pos in services and consumed[pos] < len(services[pos]):
                result.append((pos, services[pos][consumed[pos]]))
                consumed[pos] += 1
                found = True
        if not found:
            break

    return result


def build_set_timeline(s: Set) -> list[ServiceTurn]:
    """Reconstruit la timeline complète d'un set.

    Chaque ``ServiceTurn`` contient les scores exacts de début / fin,
    le nombre de points marqués par le serveur et un indicateur de
    tour gagnant du set.

    La dernière entrée de l'équipe gagnante est traitée comme un
    score de victoire (pas de side-out après) ; le dernier tour
    n'est ajouté que si le score final ne correspond pas encore
    au score réel (victoire au service plutôt que par side-out).
    """
    if not s.service_initial or not s.equipe_a or not s.equipe_b:
        return []

    a_starts = s.service_initial == "A"
    srv_a = s.equipe_a.services or {}
    srv_b = s.equipe_b.services or {}

    if not srv_a and not srv_b:
        return []

    a_flat = _team_service_flat(srv_a, starts_serving=a_starts)
    b_flat = _team_service_flat(srv_b, starts_serving=not a_starts)

    if not a_flat and not b_flat:
        return []

    score_a_final = s.score_a or 0
    score_b_final = s.score_b or 0

    winner: Optional[str] = None
    if score_a_final > score_b_final:
        winner = "A"
    elif score_b_final > score_a_final:
        winner = "B"

    # Retirer la dernière entrée du vainqueur (score de victoire).
    winning_entry: Optional[tuple[int, int]] = None
    if winner == "A" and a_flat:
        winning_entry = a_flat.pop()
    elif winner == "B" and b_flat:
        winning_entry = b_flat.pop()

    # ── Intercaler les tours ─────────────────────────────
    timeline: list[ServiceTurn] = []
    score_a = 0
    score_b = 0
    serving = s.service_initial
    a_idx = 0
    b_idx = 0

    while a_idx < len(a_flat) or b_idx < len(b_flat):
        if serving == "A" and a_idx < len(a_flat):
            pos, loss = a_flat[a_idx]
            # Points marqués au service = score_cumulé − sore_cumulé_précédent − 1
            # sauf premier tour de la team au service initial : − 0
            pts = loss - score_a
            # La différence entry[i] - entry[i-1] inclut le side-out (+1)
            # gagné entre les deux tours de cette équipe; on le soustrait.
            # Pour le tout premier tour de la starting-serving team: pas de
            # side-out précédent, donc pts = loss - 0 = loss.
            # Pour tous les autres: pts = loss - (prev_loss + 1).
            # Mais prev_loss+1 = score_a actuel (car side-out déjà ajouté),
            # donc pts = loss - score_a est déjà correct.
            timeline.append(ServiceTurn(
                team="A", position=pos,
                score_a_start=score_a, score_b_start=score_b,
                score_a_end=loss, score_b_end=score_b + 1,
                points_scored=pts,
            ))
            score_a = loss
            score_b += 1
            a_idx += 1
            serving = "B"
        elif serving == "B" and b_idx < len(b_flat):
            pos, loss = b_flat[b_idx]
            pts = loss - score_b
            timeline.append(ServiceTurn(
                team="B", position=pos,
                score_a_start=score_a, score_b_start=score_b,
                score_a_end=score_a + 1, score_b_end=loss,
                points_scored=pts,
            ))
            score_b = loss
            score_a += 1
            b_idx += 1
            serving = "A"
        else:
            break

    # ── Tour gagnant (si victoire au service, pas par side-out) ──
    if winning_entry is not None:
        pos, win_score = winning_entry
        if winner == "A" and score_a < score_a_final:
            pts = win_score - score_a
            timeline.append(ServiceTurn(
                team="A", position=pos,
                score_a_start=score_a, score_b_start=score_b,
                score_a_end=win_score, score_b_end=score_b,
                points_scored=pts, is_set_winner=True,
            ))
        elif winner == "B" and score_b < score_b_final:
            pts = win_score - score_b
            timeline.append(ServiceTurn(
                team="B", position=pos,
                score_a_start=score_a, score_b_start=score_b,
                score_a_end=score_a, score_b_end=win_score,
                points_scored=pts, is_set_winner=True,
            ))

    return timeline


# ══════════════════════════════════════════════════════════════════
#  Intervalles de présence exacts
# ══════════════════════════════════════════════════════════════════

def _compute_presence_intervals(
    td: SetTeamData,
    joueur_numero: str,
    score_a_final: int,
    score_b_final: int,
) -> list[PresenceInterval]:
    """Intervalles exacts de présence d'un joueur sur un set.

    Utilise la formation (titulaire → début à 0-0) et les
    ``changements`` avec leurs scores exacts.
    """
    n = _norm(joueur_numero)
    is_titulaire = _is_in_formation(td, joueur_numero)

    # Événements triés par score total puis type (out avant in).
    events: list[tuple[str, int, int]] = []
    for ch in td.changements:
        sa = ch.score_a if ch.score_a is not None else 0
        sb = ch.score_b if ch.score_b is not None else 0
        if _norm(ch.joueur_entrant) == n:
            events.append(("in", sa, sb))
        if _norm(ch.joueur_sortant) == n:
            events.append(("out", sa, sb))

    events.sort(key=lambda e: (e[1] + e[2], 0 if e[0] == "out" else 1))

    intervals: list[PresenceInterval] = []
    on_court = is_titulaire
    current_in: Optional[tuple[int, int]] = (0, 0) if is_titulaire else None

    for ev_type, sa, sb in events:
        if ev_type == "out" and on_court and current_in is not None:
            intervals.append(PresenceInterval(
                score_a_in=current_in[0], score_b_in=current_in[1],
                score_a_out=sa, score_b_out=sb,
            ))
            on_court = False
            current_in = None
        elif ev_type == "in" and not on_court:
            on_court = True
            current_in = (sa, sb)

    if on_court and current_in is not None:
        intervals.append(PresenceInterval(
            score_a_in=current_in[0], score_b_in=current_in[1],
            score_a_out=score_a_final, score_b_out=score_b_final,
        ))

    return intervals


# ══════════════════════════════════════════════════════════════════
#  Détermination du serveur à un instant donné
# ══════════════════════════════════════════════════════════════════

def _get_player_at_position(
    td: SetTeamData,
    position: int,
    at_score_sum: int,
) -> Optional[str]:
    """Numéro de maillot du joueur à ``position`` au score total donné.

    Les changements effectués à un score ≤ ``at_score_sum`` sont appliqués.
    """
    if not td.formation:
        return None

    current = td.formation.as_list()[position - 1]

    for ch in sorted(td.changements, key=lambda c: (c.score_a or 0) + (c.score_b or 0)):
        ch_score = (ch.score_a or 0) + (ch.score_b or 0)
        if ch.position == position and ch_score <= at_score_sum:
            current = ch.joueur_entrant

    return current


def _get_player_position_in_formation(
    td: SetTeamData,
    numero: str,
    at_score_sum: int,
) -> Optional[int]:
    """Retourne la position dans la formation (1-6) occupée par le joueur au score donné."""
    if not td.formation:
        return None
    n = _norm(numero)
    for pos in range(1, 7):
        p = _get_player_at_position(td, pos, at_score_sum)
        if p and _norm(p) == n:
            return pos
    return None


def _parse_duree_minutes(duree_val: Optional[str | int | float]) -> Optional[float]:
    """Parse une durée (ex: 85, '1h25', '85 min', '01:25') en minutes."""
    if duree_val is None:
        return None
    s = str(duree_val).strip().lower()
    if not s:
        return None
    s = s.replace("min", "").strip()
    if "h" in s:
        parts = s.split("h", 1)
        h = float(parts[0].strip() or 0)
        m = float(parts[1].strip() or 0)
        return round(h * 60.0 + m, 1)
    if ":" in s:
        parts = s.split(":", 1)
        h = float(parts[0].strip() or 0)
        m = float(parts[1].strip() or 0)
        return round(h * 60.0 + m, 1)
    try:
        val = float(s)
        return round(val, 1) if val > 0 else None
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════
#  Analyse détaillée d'un joueur sur un match
# ══════════════════════════════════════════════════════════════════

def analyze_joueur_match(
    match: Match,
    licence: str,
    *,
    remplace_par_libero: bool = False,
    est_mode_libero: bool = False,
    joueurs_remplaces_numeros: Optional[list[str]] = None,
    precomputed_roles: Optional[dict[str, RoleInference]] = None,
    precomputed_timelines: Optional[dict[int, list[ServiceTurn]]] = None,
) -> Optional[JoueurMatchDetailedStats]:
    """Analyse détaillée d'un joueur sur un match.

    Reconstruit les statistiques individuelles exactes :
    * Volume de jeu : sets joués, gagnés, perdus, commencés, terminés, match complet / non joué
    * Dynamique de banc : entrées, sorties, entrées-sorties (rôle d'appoint), sorties-entrées
    * Points & Impact On/Off : points joués/gagnés/perdus, +/-, différentiel de ratio avec/sans le joueur
    * Service : nb services, séries, moyenne, max série, max services dans un seul set, break rate
    * Efficacité par rotation : P1 à P6 (points joués, gagnés, win rate)
    * Situations de score & Clutch : égalité, en tête, menée, money time, balles de set/match sauvées/converties
    * Temps de jeu estimé : somme exacte des (ratio présence x durée du set)
    """
    joueur, side = _find_joueur(match, licence)
    if joueur is None or side is None:
        return None

    equipe = match.equipe(side)
    if equipe is None:
        return None

    opp_side = "B" if side == "A" else "A"
    numero = joueur.numero or ""
    if precomputed_roles is not None:
        inferred_role = precomputed_roles.get(_norm(numero))
    else:
        inferred_roles_by_num = infer_team_roles(match, side)
        inferred_role = inferred_roles_by_num.get(_norm(numero))

    # ── Totaux du match pour On/Off et présence relative ─
    match_total_pts = 0
    match_total_team_pts = 0
    for s_item in match.sets:
        sa = s_item.score_a or 0
        sb = s_item.score_b or 0
        match_total_pts += (sa + sb)
        match_total_team_pts += (sa if side == "A" else sb)

    # Format de match (sets nécessaires pour gagner)
    raw_max_sets = max(match.sets_a, match.sets_b, 0)
    if raw_max_sets in {2, 3}:
        sets_to_win = raw_max_sets
    else:
        sets_to_win = 3

    sets_won_side = 0
    sets_won_opp = 0

    # ── Accumulateurs globaux ────────────────────────────
    presence_par_set: list[PresenceSet] = []
    detail_services: list[ServiceSetDetail] = []
    total_points_joues = 0
    total_points_gagnes = 0
    total_points_perdus = 0
    total_nb_services = 0
    total_nb_series = 0
    max_serie_match = 0
    temps_total = 0.0
    temps_par_set: dict[int, float] = {}
    any_duration = False
    nb_entrees = 0
    nb_sorties = 0
    nb_entrees_sorties = 0
    nb_sorties_entrees = 0
    sets_gagnes = 0
    sets_perdus = 0
    sets_termines = 0
    titulaire_set_1 = False
    temps_morts_provoques = 0

    total_reception_pts_joues = 0
    total_reception_pts_gagnes = 0

    # Rotations (P1 à P6)
    rot_played = {z: 0 for z in range(1, 7)}
    rot_won = {z: 0 for z in range(1, 7)}
    rot_lost = {z: 0 for z in range(1, 7)}

    # Clutch
    clutch_pts_egalite = 0
    clutch_won_egalite = 0
    clutch_pts_en_tete = 0
    clutch_won_en_tete = 0
    clutch_pts_menee = 0
    clutch_won_menee = 0
    clutch_pts_money_time = 0
    clutch_won_money_time = 0

    balles_set_adv_total = 0
    balles_set_adv_sauvees = 0
    balles_match_adv_total = 0
    balles_match_adv_sauvees = 0

    balles_set_eq_total = 0
    balles_set_eq_conv = 0
    balles_match_eq_total = 0
    balles_match_eq_conv = 0

    max_streak_sauve_set = 0
    max_streak_sauve_match = 0

    match_duree_fallback = _parse_duree_minutes(match.duree_totale)

    for s in match.sets:
        td = s.team_data(side)
        td_opp = s.team_data(opp_side)
        if td is None:
            presence_par_set.append(PresenceSet(set_numero=s.numero))
            continue

        # ── Présence (métadonnées) ─────────────────────
        titulaire = _is_in_formation(td, numero)
        entre = False
        sorti = False
        pos_depart: Optional[int] = None
        score_entree: Optional[str] = None
        score_sortie: Optional[str] = None

        if titulaire and td.formation:
            pos_depart = _position_in_formation(td, numero)
        if titulaire and s.numero == 1:
            titulaire_set_1 = True

        # Événements de changement pour ce joueur
        raw_events: list[tuple[str, int, int]] = []
        for ch in td.changements:
            sa = ch.score_a if ch.score_a is not None else 0
            sb = ch.score_b if ch.score_b is not None else 0
            if _norm(ch.joueur_entrant) == _norm(numero):
                entre = True
                nb_entrees += 1
                raw_events.append(("in", sa, sb))
                if ch.score_a is not None and ch.score_b is not None:
                    score_entree = f"{ch.score_a}-{ch.score_b}"
            if _norm(ch.joueur_sortant) == _norm(numero):
                sorti = True
                nb_sorties += 1
                raw_events.append(("out", sa, sb))
                if ch.score_a is not None and ch.score_b is not None:
                    score_sortie = f"{ch.score_a}-{ch.score_b}"

        raw_events.sort(key=lambda e: (e[1] + e[2], 0 if e[0] == "out" else 1))
        for idx in range(len(raw_events) - 1):
            ev1 = raw_events[idx][0]
            ev2 = raw_events[idx + 1][0]
            if ev1 == "in" and ev2 == "out":
                nb_entrees_sorties += 1
            elif ev1 == "out" and ev2 == "in":
                nb_sorties_entrees += 1

        presence_par_set.append(PresenceSet(
            set_numero=s.numero,
            titulaire=titulaire,
            entre_en_jeu=entre,
            sorti=sorti,
            position_depart=pos_depart,
            score_entree=score_entree,
            score_sortie=score_sortie,
        ))

        played_set = (titulaire or entre)
        if played_set:
            if s.vainqueur == side:
                sets_gagnes += 1
            elif s.vainqueur == opp_side:
                sets_perdus += 1

        if not played_set:
            if s.vainqueur == side:
                sets_won_side += 1
            elif s.vainqueur == opp_side:
                sets_won_opp += 1
            continue

        # ── Intervalles exacts de présence ─────────────
        score_a_final = s.score_a or 0
        score_b_final = s.score_b or 0
        intervals = _compute_presence_intervals(
            td, numero, score_a_final, score_b_final,
        )

        # Set terminé sur le terrain ?
        if intervals:
            last_iv = intervals[-1]
            if last_iv.score_a_out == score_a_final and last_iv.score_b_out == score_b_final:
                sets_termines += 1

        # ── Points joués / perdus (exacts) ─────────────
        set_pts_joues = 0
        set_pts_gagnes = 0
        set_pts_perdus = 0
        for iv in intervals:
            set_pts_joues += iv.points_total
            set_pts_gagnes += iv.team_points(side)
            set_pts_perdus += iv.opp_points(side)

        # Ajustement libéro
        if remplace_par_libero:
            set_pts_joues = round(set_pts_joues * 4.0 / 6.0)
            set_pts_gagnes = round(set_pts_gagnes * 4.0 / 6.0)
            set_pts_perdus = round(set_pts_perdus * 4.0 / 6.0)
        elif est_mode_libero:
            nb_j = len(joueurs_remplaces_numeros) if joueurs_remplaces_numeros else 1
            ratio = min(1.0, nb_j * 2.0 / 6.0)
            set_pts_joues = round(set_pts_joues * ratio)
            set_pts_gagnes = round(set_pts_gagnes * ratio)
            set_pts_perdus = round(set_pts_perdus * ratio)

        total_points_joues += set_pts_joues
        total_points_gagnes += set_pts_gagnes
        total_points_perdus += set_pts_perdus

        # ── Timeline exacte ───────────────────────────
        if precomputed_timelines is not None:
            timeline = precomputed_timelines.get(s.numero, [])
        else:
            timeline = build_set_timeline(s)

        # ── Services du joueur (exacts) ────────────────
        set_nb_tours = 0
        set_nb_services = 0
        set_nb_series = 0
        set_service_pts = 0
        set_max_serie = 0
        set_scores_perte: list[int] = []

        if timeline:
            for turn in timeline:
                if turn.team != side:
                    continue

                score_sum_start = turn.score_a_start + turn.score_b_start
                server_numero = _get_player_at_position(
                    td, turn.position, score_sum_start,
                )
                if server_numero is None or _norm(server_numero) != _norm(numero):
                    continue

                set_nb_tours += 1
                set_nb_series += 1
                services_turn = turn.points_scored + (0 if turn.is_set_winner else 1)
                set_nb_services += services_turn
                set_service_pts += turn.points_scored
                set_max_serie = max(set_max_serie, services_turn)

                end_score = turn.score_a_end if side == "A" else turn.score_b_end
                set_scores_perte.append(end_score)

        if set_nb_tours > 0:
            detail_services.append(ServiceSetDetail(
                set_numero=s.numero,
                nb_services=set_nb_services,
                nb_series=set_nb_series,
                max_serie=set_max_serie,
                nb_tours=set_nb_tours,
                points_marques=set_service_pts,
                meilleure_serie=set_max_serie,
                scores_perte=set_scores_perte,
            ))

        total_nb_services += set_nb_services
        total_nb_series += set_nb_series
        max_serie_match = max(max_serie_match, set_max_serie)

        # ── Point par point : Rotations P1-P6 & Clutch ──
        if timeline:
            last_serving_pos = {"A": 1, "B": 1}
            target_pts = 15 if s.numero == 5 else 25
            money_thresh = 12 if s.numero == 5 else 20
            is_opp_match_pt = (sets_won_opp + 1 >= sets_to_win)
            is_team_match_pt = (sets_won_side + 1 >= sets_to_win)
            current_streak_set = 0
            current_streak_match = 0

            for turn in timeline:
                srv_team = turn.team
                rec_team = "B" if srv_team == "A" else "A"
                last_serving_pos[srv_team] = turn.position

                cur_sa = turn.score_a_start
                cur_sb = turn.score_b_start

                is_player_serving = False
                if srv_team == side:
                    srv_num = _get_player_at_position(td, turn.position, cur_sa + cur_sb)
                    if srv_num and _norm(srv_num) == _norm(numero):
                        is_player_serving = True

                # 1. Points marqués au service pendant ce tour
                for _ in range(turn.points_scored):
                    pre_sa = cur_sa
                    pre_sb = cur_sb
                    score_sum = pre_sa + pre_sb

                    if srv_team == "A":
                        cur_sa += 1
                    else:
                        cur_sb += 1

                    on_court = any(
                        (iv.score_a_in + iv.score_b_in) <= score_sum < (iv.score_a_out + iv.score_b_out)
                        for iv in intervals
                    )
                    if not on_court:
                        continue

                    team_score_pre = pre_sa if side == "A" else pre_sb
                    opp_score_pre = pre_sb if side == "A" else pre_sa
                    team_won_point = (srv_team == side)

                    # Rotation P1-P6
                    player_form_pos = _get_player_position_in_formation(td, numero, score_sum)
                    if player_form_pos is not None:
                        srv_form_pos = last_serving_pos[side]
                        zone = ((player_form_pos - srv_form_pos) % 6) + 1
                        rot_played[zone] += 1
                        if team_won_point:
                            rot_won[zone] += 1
                        else:
                            rot_lost[zone] += 1

                    # Side-out vs Service
                    if srv_team != side:
                        total_reception_pts_joues += 1

                    # Dynamique de score
                    if team_score_pre == opp_score_pre:
                        clutch_pts_egalite += 1
                        if team_won_point:
                            clutch_won_egalite += 1
                    elif team_score_pre > opp_score_pre:
                        clutch_pts_en_tete += 1
                        if team_won_point:
                            clutch_won_en_tete += 1
                    else:
                        clutch_pts_menee += 1
                        if team_won_point:
                            clutch_won_menee += 1

                    # Money time
                    if max(team_score_pre, opp_score_pre) >= money_thresh:
                        clutch_pts_money_time += 1
                        if team_won_point:
                            clutch_won_money_time += 1

                    # Balle de set / match adverse
                    if opp_score_pre >= target_pts - 1 and opp_score_pre > team_score_pre:
                        balles_set_adv_total += 1
                        if team_won_point:
                            balles_set_adv_sauvees += 1
                        if is_opp_match_pt:
                            balles_match_adv_total += 1
                            if team_won_point:
                                balles_match_adv_sauvees += 1

                        if is_player_serving and team_won_point:
                            current_streak_set += 1
                            max_streak_sauve_set = max(max_streak_sauve_set, current_streak_set)
                            if is_opp_match_pt:
                                current_streak_match += 1
                                max_streak_sauve_match = max(max_streak_sauve_match, current_streak_match)
                        else:
                            current_streak_set = 0
                            current_streak_match = 0
                    else:
                        current_streak_set = 0
                        current_streak_match = 0

                    # Balle de set / match équipe
                    if team_score_pre >= target_pts - 1 and team_score_pre > opp_score_pre:
                        balles_set_eq_total += 1
                        if team_won_point:
                            balles_set_eq_conv += 1
                        if is_team_match_pt:
                            balles_match_eq_total += 1
                            if team_won_point:
                                balles_match_eq_conv += 1

                # 2. Point de side-out en fin de tour
                if not turn.is_set_winner:
                    pre_sa = cur_sa
                    pre_sb = cur_sb
                    score_sum = pre_sa + pre_sb

                    if rec_team == "A":
                        cur_sa += 1
                    else:
                        cur_sb += 1

                    on_court = any(
                        (iv.score_a_in + iv.score_b_in) <= score_sum < (iv.score_a_out + iv.score_b_out)
                        for iv in intervals
                    )
                    if on_court:
                        team_score_pre = pre_sa if side == "A" else pre_sb
                        opp_score_pre = pre_sb if side == "A" else pre_sa
                        team_won_point = (rec_team == side)

                        player_form_pos = _get_player_position_in_formation(td, numero, score_sum)
                        if player_form_pos is not None:
                            srv_form_pos = last_serving_pos[side]
                            zone = ((player_form_pos - srv_form_pos) % 6) + 1
                            rot_played[zone] += 1
                            if team_won_point:
                                rot_won[zone] += 1
                            else:
                                rot_lost[zone] += 1

                        if srv_team != side:
                            total_reception_pts_joues += 1
                            total_reception_pts_gagnes += 1

                        if team_score_pre == opp_score_pre:
                            clutch_pts_egalite += 1
                            if team_won_point:
                                clutch_won_egalite += 1
                        elif team_score_pre > opp_score_pre:
                            clutch_pts_en_tete += 1
                            if team_won_point:
                                clutch_won_en_tete += 1
                        else:
                            clutch_pts_menee += 1
                            if team_won_point:
                                clutch_won_menee += 1

                        if max(team_score_pre, opp_score_pre) >= money_thresh:
                            clutch_pts_money_time += 1
                            if team_won_point:
                                clutch_won_money_time += 1

                        if opp_score_pre >= target_pts - 1 and opp_score_pre > team_score_pre:
                            balles_set_adv_total += 1
                            if team_won_point:
                                balles_set_adv_sauvees += 1
                            if is_opp_match_pt:
                                balles_match_adv_total += 1
                                if team_won_point:
                                    balles_match_adv_sauvees += 1

                        if team_score_pre >= target_pts - 1 and team_score_pre > opp_score_pre:
                            balles_set_eq_total += 1
                            if team_won_point:
                                balles_set_eq_conv += 1
                            if is_team_match_pt:
                                balles_match_eq_total += 1
                                if team_won_point:
                                    balles_match_eq_conv += 1

        # ── Temps morts provoqués (exacts) ─────────────
        if timeline and td_opp:
            for to in td_opp.timeouts:
                to_sa = to.score_a if to.score_a is not None else 0
                to_sb = to.score_b if to.score_b is not None else 0
                for turn in timeline:
                    if turn.team != side:
                        continue
                    if (turn.score_a_start <= to_sa <= turn.score_a_end
                            and turn.score_b_start <= to_sb <= turn.score_b_end):
                        score_sum = turn.score_a_start + turn.score_b_start
                        srv = _get_player_at_position(td, turn.position, score_sum)
                        if srv and _norm(srv) == _norm(numero):
                            temps_morts_provoques += 1
                        break

        # ── Temps de jeu estimé (somme des ratios x durée) ─
        set_dur = float(s.duree_minutes) if s.duree_minutes is not None else None
        if set_dur is None and match_duree_fallback is not None and match_total_pts > 0:
            set_dur = match_duree_fallback * ((score_a_final + score_b_final) / match_total_pts)

        if set_dur is not None:
            any_duration = True
            total_pts_set = score_a_final + score_b_final
            if total_pts_set > 0:
                ratio = set_pts_joues / total_pts_set
            else:
                ratio = 1.0 if played_set else 0.0
            minutes = set_dur * ratio
            temps_par_set[s.numero] = round(minutes, 1)
            temps_total += minutes

        if s.vainqueur == side:
            sets_won_side += 1
        elif s.vainqueur == opp_side:
            sets_won_opp += 1

    # ── Résultat & Synthèse ──────────────────────────────
    sets_joues = sum(1 for p in presence_par_set if p.titulaire or p.entre_en_jeu)
    sets_titulaire = sum(1 for p in presence_par_set if p.titulaire)
    sets_commences = sets_titulaire
    victoire = match.vainqueur == side

    pts_service_total = sum(d.points_marques for d in detail_services)
    pts_sideout_total = max(0, total_points_gagnes - pts_service_total)
    ratio_points_gagnes = round(total_points_gagnes / total_points_joues, 3) if total_points_joues > 0 else 0.0
    break_point_ratio = round(pts_service_total / total_nb_services, 3) if total_nb_services > 0 else 0.0
    sideout_contribution_ratio = round(pts_sideout_total / total_points_gagnes, 3) if total_points_gagnes > 0 else 0.0
    moyenne_services_par_serie = round(total_nb_services / total_nb_series, 2) if total_nb_series > 0 else 0.0
    sanctions = _collect_sanctions(match, joueur, side)

    # Métriques On / Off & Présence relative
    plus_minus = total_points_gagnes - total_points_perdus
    points_joues_off = max(0, match_total_pts - total_points_joues)
    points_gagnes_off = max(0, match_total_team_pts - total_points_gagnes)
    ratio_points_gagnes_off = round(points_gagnes_off / points_joues_off, 3) if points_joues_off > 0 else None
    differentiel_points_gagnes = (
        round(ratio_points_gagnes - ratio_points_gagnes_off, 3)
        if ratio_points_gagnes_off is not None else None
    )
    presence_relative = round(total_points_joues / match_total_pts, 3) if match_total_pts > 0 else 0.0
    sideout_win_rate = (
        round(total_reception_pts_gagnes / total_reception_pts_joues, 3)
        if total_reception_pts_joues > 0 else 0.0
    )
    max_services_set = max((d.nb_services for d in detail_services), default=0)

    total_sets_match = len(match.sets)
    match_complet = (total_sets_match > 0 and sets_commences == total_sets_match and nb_sorties == 0)
    match_non_joue = (sets_joues == 0)

    # Construction RotationStats
    rotations = RotationStats(
        p1=PositionRotationStats(
            points_joues=rot_played[1],
            points_gagnes=rot_won[1],
            points_perdus=rot_lost[1],
            win_rate=round(rot_won[1] / rot_played[1], 3) if rot_played[1] > 0 else 0.0,
        ),
        p2=PositionRotationStats(
            points_joues=rot_played[2],
            points_gagnes=rot_won[2],
            points_perdus=rot_lost[2],
            win_rate=round(rot_won[2] / rot_played[2], 3) if rot_played[2] > 0 else 0.0,
        ),
        p3=PositionRotationStats(
            points_joues=rot_played[3],
            points_gagnes=rot_won[3],
            points_perdus=rot_lost[3],
            win_rate=round(rot_won[3] / rot_played[3], 3) if rot_played[3] > 0 else 0.0,
        ),
        p4=PositionRotationStats(
            points_joues=rot_played[4],
            points_gagnes=rot_won[4],
            points_perdus=rot_lost[4],
            win_rate=round(rot_won[4] / rot_played[4], 3) if rot_played[4] > 0 else 0.0,
        ),
        p5=PositionRotationStats(
            points_joues=rot_played[5],
            points_gagnes=rot_won[5],
            points_perdus=rot_lost[5],
            win_rate=round(rot_won[5] / rot_played[5], 3) if rot_played[5] > 0 else 0.0,
        ),
        p6=PositionRotationStats(
            points_joues=rot_played[6],
            points_gagnes=rot_won[6],
            points_perdus=rot_lost[6],
            win_rate=round(rot_won[6] / rot_played[6], 3) if rot_played[6] > 0 else 0.0,
        ),
    )

    # Construction ClutchStats
    clutch = ClutchStats(
        points_egalite=clutch_pts_egalite,
        points_gagnes_egalite=clutch_won_egalite,
        win_rate_egalite=round(clutch_won_egalite / clutch_pts_egalite, 3) if clutch_pts_egalite > 0 else 0.0,
        points_en_tete=clutch_pts_en_tete,
        points_gagnes_en_tete=clutch_won_en_tete,
        win_rate_en_tete=round(clutch_won_en_tete / clutch_pts_en_tete, 3) if clutch_pts_en_tete > 0 else 0.0,
        points_menee=clutch_pts_menee,
        points_gagnes_menee=clutch_won_menee,
        win_rate_menee=round(clutch_won_menee / clutch_pts_menee, 3) if clutch_pts_menee > 0 else 0.0,
        points_money_time=clutch_pts_money_time,
        points_gagnes_money_time=clutch_won_money_time,
        win_rate_money_time=round(clutch_won_money_time / clutch_pts_money_time, 3) if clutch_pts_money_time > 0 else 0.0,
        balles_de_set_adverse_total=balles_set_adv_total,
        balles_de_set_adverse_sauvees=balles_set_adv_sauvees,
        win_rate_sauve_balle_set=round(balles_set_adv_sauvees / balles_set_adv_total, 3) if balles_set_adv_total > 0 else 0.0,
        balles_de_match_adverse_total=balles_match_adv_total,
        balles_de_match_adverse_sauvees=balles_match_adv_sauvees,
        win_rate_sauve_balle_match=round(balles_match_adv_sauvees / balles_match_adv_total, 3) if balles_match_adv_total > 0 else 0.0,
        balles_de_set_equipe_total=balles_set_eq_total,
        balles_de_set_equipe_converties=balles_set_eq_conv,
        win_rate_balle_set_equipe=round(balles_set_eq_conv / balles_set_eq_total, 3) if balles_set_eq_total > 0 else 0.0,
        balles_de_match_equipe_total=balles_match_eq_total,
        balles_de_match_equipe_converties=balles_match_eq_conv,
        win_rate_balle_match_equipe=round(balles_match_eq_conv / balles_match_eq_total, 3) if balles_match_eq_total > 0 else 0.0,
        max_serie_sauve_balle_set=max_streak_sauve_set,
        max_serie_sauve_balle_match=max_streak_sauve_match,
    )

    return JoueurMatchDetailedStats(
        numero=numero,
        nom=joueur.nom,
        prenom=joueur.prenom,
        licence=joueur.licence,
        equipe=equipe.nom,
        side=side,
        est_libero=joueur.est_libero,
        est_capitaine=joueur.est_capitaine,
        role_principal=inferred_role.role_principal if inferred_role else None,
        roles_possibles=inferred_role.roles_possibles if inferred_role else [],
        role_scores=inferred_role.role_scores if inferred_role else {},
        role_confiance=inferred_role.role_confiance if inferred_role else 0.0,
        indices_roles=inferred_role.indices if inferred_role else [],
        victoire=victoire,
        score_match=match.score_sets,
        points_gagnes=total_points_gagnes,
        points_gagnes_service=pts_service_total,
        points_gagnes_sideout=pts_sideout_total,
        points_perdus=total_points_perdus,
        points_joues=total_points_joues,
        ratio_points_gagnes=ratio_points_gagnes,
        break_point_ratio=break_point_ratio,
        sideout_contribution_ratio=sideout_contribution_ratio,
        sideout_win_rate=sideout_win_rate,
        plus_minus=plus_minus,
        points_joues_off=points_joues_off,
        points_gagnes_off=points_gagnes_off,
        ratio_points_gagnes_off=ratio_points_gagnes_off,
        differentiel_points_gagnes=differentiel_points_gagnes,
        services=total_nb_services,
        serie=total_nb_series,
        max_serie=max_serie_match,
        moyenne_services_par_serie=moyenne_services_par_serie,
        nb_services=total_nb_services,
        meilleure_serie=max_serie_match,
        max_services_set=max_services_set,
        detail_services_par_set=detail_services,
        sets_joues=sets_joues,
        sets_gagnes=sets_gagnes,
        sets_perdus=sets_perdus,
        sets_commences=sets_commences,
        sets_titulaire=sets_titulaire,
        sets_termines=sets_termines,
        titulaire_set_1=titulaire_set_1,
        match_complet=match_complet,
        match_non_joue=match_non_joue,
        presence_relative=presence_relative,
        presence_par_set=presence_par_set,
        temps_jeu_estime=round(temps_total, 1) if any_duration else None,
        temps_jeu_par_set=temps_par_set,
        nb_entrees=nb_entrees,
        nb_sorties=nb_sorties,
        nb_changements_total=nb_entrees + nb_sorties,
        nb_entrees_sorties=nb_entrees_sorties,
        nb_sorties_entrees=nb_sorties_entrees,
        rotations=rotations,
        clutch=clutch,
        temps_morts_provoques=temps_morts_provoques,
        sanctions=sanctions,
        est_calcul_libero=est_mode_libero,
        joueurs_remplaces=joueurs_remplaces_numeros or [],
        remplace_par_libero=remplace_par_libero,
    )


# ══════════════════════════════════════════════════════════════════
#  Agrégation sur plusieurs matchs
# ══════════════════════════════════════════════════════════════════

def aggregate_joueur_stats(
    stats_list: list[JoueurMatchDetailedStats],
) -> Optional[JoueurStatsAggregated]:
    """Agrège les statistiques détaillées sur plusieurs matchs."""
    if not stats_list:
        return None

    first = stats_list[0]
    total_tours_service = sum(
        detail.nb_tours
        for stats in stats_list
        for detail in stats.detail_services_par_set
    )
    role_distribution_matchs: dict[str, int] = {}
    role_scores_totaux: dict[str, float] = {}

    for stats in stats_list:
        if stats.role_principal:
            role_distribution_matchs[stats.role_principal] = (
                role_distribution_matchs.get(stats.role_principal, 0) + 1
            )
        for role_name, score in (stats.role_scores or {}).items():
            role_scores_totaux[role_name] = role_scores_totaux.get(role_name, 0.0) + float(score)

    role_scores_moyens = {
        role_name: round(total_score / len(stats_list), 3)
        for role_name, total_score in sorted(
            role_scores_totaux.items(), key=lambda item: (-item[1], item[0])
        )
    }

    # Agrégation Rotations
    rot_p1_joues = sum(s.rotations.p1.points_joues for s in stats_list)
    rot_p1_gagnes = sum(s.rotations.p1.points_gagnes for s in stats_list)
    rot_p1_perdus = sum(s.rotations.p1.points_perdus for s in stats_list)

    rot_p2_joues = sum(s.rotations.p2.points_joues for s in stats_list)
    rot_p2_gagnes = sum(s.rotations.p2.points_gagnes for s in stats_list)
    rot_p2_perdus = sum(s.rotations.p2.points_perdus for s in stats_list)

    rot_p3_joues = sum(s.rotations.p3.points_joues for s in stats_list)
    rot_p3_gagnes = sum(s.rotations.p3.points_gagnes for s in stats_list)
    rot_p3_perdus = sum(s.rotations.p3.points_perdus for s in stats_list)

    rot_p4_joues = sum(s.rotations.p4.points_joues for s in stats_list)
    rot_p4_gagnes = sum(s.rotations.p4.points_gagnes for s in stats_list)
    rot_p4_perdus = sum(s.rotations.p4.points_perdus for s in stats_list)

    rot_p5_joues = sum(s.rotations.p5.points_joues for s in stats_list)
    rot_p5_gagnes = sum(s.rotations.p5.points_gagnes for s in stats_list)
    rot_p5_perdus = sum(s.rotations.p5.points_perdus for s in stats_list)

    rot_p6_joues = sum(s.rotations.p6.points_joues for s in stats_list)
    rot_p6_gagnes = sum(s.rotations.p6.points_gagnes for s in stats_list)
    rot_p6_perdus = sum(s.rotations.p6.points_perdus for s in stats_list)

    rotations_globales = RotationStats(
        p1=PositionRotationStats(
            points_joues=rot_p1_joues, points_gagnes=rot_p1_gagnes, points_perdus=rot_p1_perdus,
            win_rate=round(rot_p1_gagnes / rot_p1_joues, 3) if rot_p1_joues > 0 else 0.0,
        ),
        p2=PositionRotationStats(
            points_joues=rot_p2_joues, points_gagnes=rot_p2_gagnes, points_perdus=rot_p2_perdus,
            win_rate=round(rot_p2_gagnes / rot_p2_joues, 3) if rot_p2_joues > 0 else 0.0,
        ),
        p3=PositionRotationStats(
            points_joues=rot_p3_joues, points_gagnes=rot_p3_gagnes, points_perdus=rot_p3_perdus,
            win_rate=round(rot_p3_gagnes / rot_p3_joues, 3) if rot_p3_joues > 0 else 0.0,
        ),
        p4=PositionRotationStats(
            points_joues=rot_p4_joues, points_gagnes=rot_p4_gagnes, points_perdus=rot_p4_perdus,
            win_rate=round(rot_p4_gagnes / rot_p4_joues, 3) if rot_p4_joues > 0 else 0.0,
        ),
        p5=PositionRotationStats(
            points_joues=rot_p5_joues, points_gagnes=rot_p5_gagnes, points_perdus=rot_p5_perdus,
            win_rate=round(rot_p5_gagnes / rot_p5_joues, 3) if rot_p5_joues > 0 else 0.0,
        ),
        p6=PositionRotationStats(
            points_joues=rot_p6_joues, points_gagnes=rot_p6_gagnes, points_perdus=rot_p6_perdus,
            win_rate=round(rot_p6_gagnes / rot_p6_joues, 3) if rot_p6_joues > 0 else 0.0,
        ),
    )

    # Agrégation Clutch
    c_pts_eg = sum(s.clutch.points_egalite for s in stats_list)
    c_won_eg = sum(s.clutch.points_gagnes_egalite for s in stats_list)

    c_pts_et = sum(s.clutch.points_en_tete for s in stats_list)
    c_won_et = sum(s.clutch.points_gagnes_en_tete for s in stats_list)

    c_pts_mn = sum(s.clutch.points_menee for s in stats_list)
    c_won_mn = sum(s.clutch.points_gagnes_menee for s in stats_list)

    c_pts_mt = sum(s.clutch.points_money_time for s in stats_list)
    c_won_mt = sum(s.clutch.points_gagnes_money_time for s in stats_list)

    c_b_set_adv_tot = sum(s.clutch.balles_de_set_adverse_total for s in stats_list)
    c_b_set_adv_sauv = sum(s.clutch.balles_de_set_adverse_sauvees for s in stats_list)

    c_b_mat_adv_tot = sum(s.clutch.balles_de_match_adverse_total for s in stats_list)
    c_b_mat_adv_sauv = sum(s.clutch.balles_de_match_adverse_sauvees for s in stats_list)

    c_b_set_eq_tot = sum(s.clutch.balles_de_set_equipe_total for s in stats_list)
    c_b_set_eq_conv = sum(s.clutch.balles_de_set_equipe_converties for s in stats_list)

    c_b_mat_eq_tot = sum(s.clutch.balles_de_match_equipe_total for s in stats_list)
    c_b_mat_eq_conv = sum(s.clutch.balles_de_match_equipe_converties for s in stats_list)

    clutch_global = ClutchStats(
        points_egalite=c_pts_eg,
        points_gagnes_egalite=c_won_eg,
        win_rate_egalite=round(c_won_eg / c_pts_eg, 3) if c_pts_eg > 0 else 0.0,
        points_en_tete=c_pts_et,
        points_gagnes_en_tete=c_won_et,
        win_rate_en_tete=round(c_won_et / c_pts_et, 3) if c_pts_et > 0 else 0.0,
        points_menee=c_pts_mn,
        points_gagnes_menee=c_won_mn,
        win_rate_menee=round(c_won_mn / c_pts_mn, 3) if c_pts_mn > 0 else 0.0,
        points_money_time=c_pts_mt,
        points_gagnes_money_time=c_won_mt,
        win_rate_money_time=round(c_won_mt / c_pts_mt, 3) if c_pts_mt > 0 else 0.0,
        balles_de_set_adverse_total=c_b_set_adv_tot,
        balles_de_set_adverse_sauvees=c_b_set_adv_sauv,
        win_rate_sauve_balle_set=round(c_b_set_adv_sauv / c_b_set_adv_tot, 3) if c_b_set_adv_tot > 0 else 0.0,
        balles_de_match_adverse_total=c_b_mat_adv_tot,
        balles_de_match_adverse_sauvees=c_b_mat_adv_sauv,
        win_rate_sauve_balle_match=round(c_b_mat_adv_sauv / c_b_mat_adv_tot, 3) if c_b_mat_adv_tot > 0 else 0.0,
        balles_de_set_equipe_total=c_b_set_eq_tot,
        balles_de_set_equipe_converties=c_b_set_eq_conv,
        win_rate_balle_set_equipe=round(c_b_set_eq_conv / c_b_set_eq_tot, 3) if c_b_set_eq_tot > 0 else 0.0,
        balles_de_match_equipe_total=c_b_mat_eq_tot,
        balles_de_match_equipe_converties=c_b_mat_eq_conv,
        win_rate_balle_match_equipe=round(c_b_mat_eq_conv / c_b_mat_eq_tot, 3) if c_b_mat_eq_tot > 0 else 0.0,
        max_serie_sauve_balle_set=max((s.clutch.max_serie_sauve_balle_set for s in stats_list), default=0),
        max_serie_sauve_balle_match=max((s.clutch.max_serie_sauve_balle_match for s in stats_list), default=0),
    )

    tot_pts_gagnes = sum(s.points_gagnes for s in stats_list)
    tot_pts_joues = sum(s.points_joues for s in stats_list)
    ratio_pts_gagnes_glob = round(tot_pts_gagnes / tot_pts_joues, 3) if tot_pts_joues > 0 else 0.0

    # On / Off global
    tot_off_joues = sum(s.points_joues_off for s in stats_list)
    tot_off_gagnes = sum(s.points_gagnes_off for s in stats_list)
    if tot_off_joues > 0:
        off_ratio_glob = tot_off_gagnes / tot_off_joues
        diff_pts_gagnes_glob = round(ratio_pts_gagnes_glob - off_ratio_glob, 3)
    else:
        diff_pts_gagnes_glob = None

    tot_sideout_gagnes = sum(s.points_gagnes_sideout for s in stats_list)
    # Estimation side-out win rate global depuis rot P2..P6 ou réception
    pts_reception_tot = sum(
        s.rotations.p2.points_joues + s.rotations.p3.points_joues +
        s.rotations.p4.points_joues + s.rotations.p5.points_joues + s.rotations.p6.points_joues
        for s in stats_list
    )
    sideout_wr_glob = round(tot_sideout_gagnes / pts_reception_tot, 3) if pts_reception_tot > 0 else 0.0

    result = JoueurStatsAggregated(
        nom=first.nom,
        prenom=first.prenom,
        licence=first.licence,
        matchs_joues=len(stats_list),
        matchs_victoires=sum(1 for s in stats_list if s.victoire),
        matchs_defaites=sum(1 for s in stats_list if not s.victoire),
        total_matchs_complets=sum(1 for s in stats_list if s.match_complet),
        total_matchs_non_joues=sum(1 for s in stats_list if s.match_non_joue),
        total_titularisations_set_1=sum(1 for s in stats_list if s.titulaire_set_1),
        total_sets_joues=sum(s.sets_joues for s in stats_list),
        total_sets_gagnes=sum(s.sets_gagnes for s in stats_list),
        total_sets_perdus=sum(s.sets_perdus for s in stats_list),
        total_sets_commences=sum(s.sets_commences for s in stats_list),
        total_sets_titulaire=sum(s.sets_titulaire for s in stats_list),
        total_sets_termines=sum(s.sets_termines for s in stats_list),
        presence_relative_moyenne=round(
            sum(s.presence_relative for s in stats_list) / len(stats_list), 3
        ) if stats_list else 0.0,
        total_points_gagnes=tot_pts_gagnes,
        total_points_gagnes_service=sum(s.points_gagnes_service for s in stats_list),
        total_points_gagnes_sideout=tot_sideout_gagnes,
        total_points_perdus=sum(s.points_perdus for s in stats_list),
        total_points_joues=tot_pts_joues,
        total_plus_minus=sum(s.plus_minus for s in stats_list),
        ratio_points_gagnes_global=ratio_pts_gagnes_glob,
        break_point_ratio_global=0.0,
        ratio_points_gagnes_sideout_global=0.0,
        sideout_win_rate_global=sideout_wr_glob,
        differentiel_points_gagnes_global=diff_pts_gagnes_glob,
        total_services=sum(s.services for s in stats_list),
        total_series_service=sum(s.serie for s in stats_list),
        max_serie_service=max((s.max_serie for s in stats_list), default=0),
        max_services_set_record=max((s.max_services_set for s in stats_list), default=0),
        total_tours_service=total_tours_service,
        meilleure_serie_service=max(
            (s.meilleure_serie for s in stats_list), default=0
        ),
        total_temps_jeu=round(
            sum(s.temps_jeu_estime or 0 for s in stats_list), 1,
        ),
        total_entrees=sum(s.nb_entrees for s in stats_list),
        total_sorties=sum(s.nb_sorties for s in stats_list),
        total_entrees_sorties=sum(s.nb_entrees_sorties for s in stats_list),
        total_sorties_entrees=sum(s.nb_sorties_entrees for s in stats_list),
        rotations_globales=rotations_globales,
        clutch_global=clutch_global,
        total_temps_morts_provoques=sum(
            s.temps_morts_provoques for s in stats_list
        ),
        total_sanctions=sum(len(s.sanctions) for s in stats_list),
    )

    if result.total_tours_service > 0:
        result.moyenne_points_par_tour = round(
            result.total_points_gagnes_service / result.total_tours_service, 2,
        )
    if result.total_series_service > 0:
        result.moyenne_services_par_serie = round(
            result.total_services / result.total_series_service, 2,
        )
    if result.total_services > 0:
        result.break_point_ratio_global = round(
            result.total_points_gagnes_service / result.total_services, 3,
        )
    if result.total_points_gagnes > 0:
        result.ratio_points_gagnes_sideout_global = round(
            result.total_points_gagnes_sideout / result.total_points_gagnes, 3,
        )
    if result.matchs_joues > 0:
        result.moyenne_temps_par_match = round(
            result.total_temps_jeu / result.matchs_joues, 1,
        )
        result.moyenne_temps_morts_par_match = round(
            result.total_temps_morts_provoques / result.matchs_joues, 2,
        )
    if result.total_sets_joues > 0:
        result.moyenne_temps_par_set = round(
            result.total_temps_jeu / result.total_sets_joues, 1,
        )

    result.role_distribution_matchs = role_distribution_matchs
    role_scores_totaux_dict: dict[str, float] = {}
    for stats in stats_list:
        for role_name, score in (stats.role_scores or {}).items():
            role_scores_totaux_dict[role_name] = role_scores_totaux_dict.get(role_name, 0.0) + float(score)

    role_scores_moyens = {
        role_name: round(total_score / len(stats_list), 3)
        for role_name, total_score in sorted(
            role_scores_totaux_dict.items(), key=lambda item: (-item[1], item[0])
        )
    }
    result.role_scores_moyens = role_scores_moyens

    if role_scores_moyens:
        principal = max(
            role_scores_moyens.items(), key=lambda item: (item[1], item[0])
        )[0]
        result.role_principal_global = principal
        roles_possibles = [
            role_name
            for role_name, score in role_scores_moyens.items()
            if score >= 0.18
        ]
        if not roles_possibles:
            roles_possibles = [principal]
        elif principal not in roles_possibles:
            roles_possibles.insert(0, principal)
        result.roles_possibles_global = roles_possibles[:3]
    elif role_distribution_matchs:
        result.role_principal_global = max(
            role_distribution_matchs.items(), key=lambda item: (item[1], item[0])
        )[0]
        result.roles_possibles_global = [result.role_principal_global]

    return result


# ══════════════════════════════════════════════════════════════════
#  Fonctions utilitaires internes
# ══════════════════════════════════════════════════════════════════

def _find_joueur(match: Match, licence: str):
    """Trouve un joueur dans un match par sa licence."""
    for side_label in ("A", "B"):
        equipe = match.equipe(side_label)
        if equipe is None:
            continue
        for j in equipe.joueurs:
            if j.licence == licence:
                return j, side_label
    return None, None


def _collect_sanctions(
    match: Match, joueur: Joueur, side: str,
) -> list[str]:
    """Collecte les sanctions reçues par un joueur."""
    result: list[str] = []
    for sanction in match.sanctions:
        if sanction.equipe == side and sanction.joueur_numero == joueur.numero:
            score_str = ""
            if sanction.score_a is not None and sanction.score_b is not None:
                score_str = f", {sanction.score_a}-{sanction.score_b}"
            result.append(
                f"{sanction.type.value} (set {sanction.set_numero}{score_str})"
            )
    return result
