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

    Les statistiques sont calculées de manière **exacte** lorsque les
    données de services et de changements sont disponibles :

    * **Points joués / perdus** : calculés à partir des intervalles
      de présence exacts (scores aux changements).
    * **Points gagnés au service** : reconstruits depuis la timeline
      du set (tours de service intercalés).
    * **Meilleure série** : max de points au service par tour.
    * **Temps morts provoqués** : croisement exact tour de service ×
      temps morts adverses.
    * **Temps de jeu** : proportionnel aux points joués (si durée connue).

    Quand les données ``services`` sont absentes (match issu de la BDD
    sans PDF), les stats de service restent à zéro mais les points
    joués/perdus sont tout de même exacts grâce aux changements.
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

    # ── Accumulateurs ────────────────────────────────────
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
    temps_morts_provoques = 0

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

        for ch in td.changements:
            if _norm(ch.joueur_entrant) == _norm(numero):
                entre = True
                nb_entrees += 1
                if ch.score_a is not None and ch.score_b is not None:
                    score_entree = f"{ch.score_a}-{ch.score_b}"
            if _norm(ch.joueur_sortant) == _norm(numero):
                sorti = True
                nb_sorties += 1
                if ch.score_a is not None and ch.score_b is not None:
                    score_sortie = f"{ch.score_a}-{ch.score_b}"

        presence_par_set.append(PresenceSet(
            set_numero=s.numero,
            titulaire=titulaire,
            entre_en_jeu=entre,
            sorti=sorti,
            position_depart=pos_depart,
            score_entree=score_entree,
            score_sortie=score_sortie,
        ))

        if not (titulaire or entre):
            continue

        # ── Intervalles exacts de présence ─────────────
        score_a_final = s.score_a or 0
        score_b_final = s.score_b or 0
        intervals = _compute_presence_intervals(
            td, numero, score_a_final, score_b_final,
        )

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
                        break  # un TM n'est compté qu'une fois

        # ── Temps de jeu ──────────────────────────────
        if s.duree_minutes is not None:
            any_duration = True
            total_pts_set = score_a_final + score_b_final
            if total_pts_set > 0:
                ratio = set_pts_joues / total_pts_set
            else:
                ratio = 1.0 if (titulaire or entre) else 0.0
            minutes = float(s.duree_minutes) * ratio
            temps_par_set[s.numero] = round(minutes, 1)
            temps_total += minutes

    # ── Résultat ──────────────────────────────────────────
    sets_joues = sum(1 for p in presence_par_set if p.titulaire or p.entre_en_jeu)
    sets_titulaire = sum(1 for p in presence_par_set if p.titulaire)
    victoire = match.vainqueur == side

    pts_service_total = sum(d.points_marques for d in detail_services)
    pts_sideout_total = max(0, total_points_gagnes - pts_service_total)
    ratio_points_gagnes = round(total_points_gagnes / total_points_joues, 3) if total_points_joues > 0 else 0.0
    break_point_ratio = round(pts_service_total / total_nb_services, 3) if total_nb_services > 0 else 0.0
    sideout_contribution_ratio = round(pts_sideout_total / total_points_gagnes, 3) if total_points_gagnes > 0 else 0.0
    moyenne_services_par_serie = round(total_nb_services / total_nb_series, 2) if total_nb_series > 0 else 0.0
    sanctions = _collect_sanctions(match, joueur, side)

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
        services=total_nb_services,
        serie=total_nb_series,
        max_serie=max_serie_match,
        moyenne_services_par_serie=moyenne_services_par_serie,
        nb_services=total_nb_services,
        meilleure_serie=max_serie_match,
        detail_services_par_set=detail_services,
        sets_joues=sets_joues,
        sets_titulaire=sets_titulaire,
        presence_par_set=presence_par_set,
        temps_jeu_estime=round(temps_total, 1) if any_duration else None,
        temps_jeu_par_set=temps_par_set,
        nb_entrees=nb_entrees,
        nb_sorties=nb_sorties,
        nb_changements_total=nb_entrees + nb_sorties,
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

    result = JoueurStatsAggregated(
        nom=first.nom,
        prenom=first.prenom,
        licence=first.licence,
        matchs_joues=len(stats_list),
        matchs_victoires=sum(1 for s in stats_list if s.victoire),
        matchs_defaites=sum(1 for s in stats_list if not s.victoire),
        total_sets_joues=sum(s.sets_joues for s in stats_list),
        total_sets_titulaire=sum(s.sets_titulaire for s in stats_list),
        total_points_gagnes=sum(s.points_gagnes for s in stats_list),
        total_points_gagnes_service=sum(s.points_gagnes_service for s in stats_list),
        total_points_gagnes_sideout=sum(s.points_gagnes_sideout for s in stats_list),
        total_points_perdus=sum(s.points_perdus for s in stats_list),
        total_points_joues=sum(s.points_joues for s in stats_list),
        total_services=sum(s.services for s in stats_list),
        total_series_service=sum(s.serie for s in stats_list),
        max_serie_service=max((s.max_serie for s in stats_list), default=0),
        total_tours_service=total_tours_service,
        meilleure_serie_service=max(
            (s.meilleure_serie for s in stats_list), default=0
        ),
        total_temps_jeu=round(
            sum(s.temps_jeu_estime or 0 for s in stats_list), 1,
        ),
        total_entrees=sum(s.nb_entrees for s in stats_list),
        total_sorties=sum(s.nb_sorties for s in stats_list),
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
    if result.total_points_joues > 0:
        result.ratio_points_gagnes_global = round(
            result.total_points_gagnes / result.total_points_joues, 3,
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

    result.role_distribution_matchs = role_distribution_matchs
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
