"""Solveur de rôles d'équipe basé sur les contraintes volley-ball et la diffusion réseau.

Ce module résout l'affectation optimale et probabiliste des rôles au sein d'une équipe
pour un match donné en exploitant :
1. Les signaux locaux de feuille de match (libéro déclaré, remplacements arrière/avant, double-changements).
2. Les binômes opposés en rotation (1-4, 2-5, 3-6) régis par les contraintes tactiques du volley-ball :
   - Centraux opposés entre eux (C <-> C)
   - Réceptionneurs-Attaquants opposés entre eux (RA <-> RA)
   - Passeur et Pointu opposés (P <-> O)
3. Le budget de composition de l'équipe (1 P, 1 O, 2 RA, 2 C, Libéro).
4. Les priors de carrière et de saison des joueurs pour stabiliser les feuilles incomplètes
   tout en permettant la détection de changements de rôle avérés.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .models import RoleInference

from pyvolley.core.constants import (
    ROLE_SETTER,
    ROLE_OPPOSITE,
    ROLE_MIDDLE,
    ROLE_OUTSIDE,
    ROLE_LIBERO,
    ALL_SPECIFIC_ROLES as ALL_ROLES,
    ROLE_LABELS,
)

_FRONT_POSITIONS = {2, 3, 4}
_BACK_POSITIONS = {1, 5, 6}


def _norm(numero: Optional[str]) -> str:
    if numero is None:
        return ""
    cleaned = str(numero).strip().lstrip("0")
    return cleaned or "0"


def _opposite_position(pos: int) -> int:
    """Retourne la position diamétralement opposée sur le terrain à 6 joueurs."""
    return ((pos + 2) % 6) + 1


def _is_opposite_pos(pos_a: int, pos_b: int) -> bool:
    return (pos_a - pos_b) % 6 == 3


@dataclass(slots=True)
class PlayerLocalEvidence:
    """Évidences factuelles récoltées sur la feuille de match pour un joueur."""

    numero: str
    is_explicit_libero: bool = False
    libero_back_replaces: int = 0
    libero_front_replaces: int = 0
    starter_positions: list[int] = field(default_factory=list)
    sets_played: int = 0
    sets_starter: int = 0
    passe_pointe_sub_as_setter: float = 0.0
    passe_pointe_sub_as_opp: float = 0.0
    other_sub_counts: int = 0
    hints: list[str] = field(default_factory=list)

    def add_hint(self, hint: str) -> None:
        if hint and len(self.hints) < 16 and hint not in self.hints:
            self.hints.append(hint)


@dataclass(slots=True)
class TeamMatchContext:
    """Contexte complet d'une équipe sur un match."""

    side: str
    players: dict[str, PlayerLocalEvidence] = field(default_factory=dict)
    rotation_pairs: Counter[tuple[str, str]] = field(default_factory=Counter)
    set_triplets: list[list[tuple[str, str]]] = field(default_factory=list)
    formation_count: int = 0


def extract_team_context(match, side: str) -> TeamMatchContext:
    """Extrait toutes les évidences structurelles et de rotation d'une équipe."""
    team = match.equipe(side)
    context = TeamMatchContext(side=side)
    if team is None:
        return context

    def get_or_create(numero: Optional[str], is_lib: bool = False) -> Optional[PlayerLocalEvidence]:
        n = _norm(numero)
        if not n:
            return None
        if n not in context.players:
            context.players[n] = PlayerLocalEvidence(numero=n, is_explicit_libero=is_lib)
        elif is_lib:
            context.players[n].is_explicit_libero = True
        return context.players[n]

    for j in (team.joueurs or []):
        get_or_create(j.numero, is_lib=bool(j.est_libero))
    # Déclaration explicite des libéros
    for lib in (team.liberos or []):
        get_or_create(lib.numero, is_lib=True)

    # Parcours des sets
    for s in (match.sets or []):
        td = s.team_data(side)
        if td is None:
            continue

        formation_map: dict[int, str] = {}
        if td.formation:
            context.formation_count += 1
            for pos, raw_num in enumerate(td.formation.as_list(), start=1):
                num = _norm(raw_num)
                if num:
                    formation_map[pos] = num
                    ev = get_or_create(num)
                    if ev:
                        ev.starter_positions.append(pos)
                        ev.sets_starter += 1
                        ev.sets_played = max(ev.sets_played, 1)

        # Paires opposées en rotation (pos, (pos+3)%6)
        triplet: list[tuple[str, str]] = []
        for p1 in (1, 2, 3):
            p2 = _opposite_position(p1)
            num1 = formation_map.get(p1)
            num2 = formation_map.get(p2)
            if num1 and num2 and num1 != num2:
                pair_key = (min(num1, num2), max(num1, num2))
                context.rotation_pairs[pair_key] += 1
                triplet.append(pair_key)
        if len(triplet) == 3:
            context.set_triplets.append(triplet)

        # Remplacements libéro et classiques
        for ch in td.changements:
            entrant = _norm(ch.joueur_entrant)
            sortant = _norm(ch.joueur_sortant)
            pos = ch.position

            ev_in = get_or_create(entrant)
            ev_out = get_or_create(sortant)
            if ev_in:
                ev_in.sets_played = max(ev_in.sets_played, 1)

            # Remplacement avec un libéro
            is_in_lib = ev_in.is_explicit_libero if ev_in else False
            is_out_lib = ev_out.is_explicit_libero if ev_out else False

            if is_in_lib and ev_out and not is_out_lib:
                if pos in _BACK_POSITIONS:
                    ev_out.libero_back_replaces += 1
                    ev_out.add_hint(f"remplacé par libéro en zone arrière (set {s.numero})")
                else:
                    ev_out.libero_front_replaces += 1
            elif is_out_lib and ev_in and not is_in_lib:
                if pos in _FRONT_POSITIONS:
                    ev_in.libero_back_replaces += 1
                    ev_in.add_hint(f"retour en jeu suite à libéro (set {s.numero})")

        # Détection synchronisée des inversions passe-pointe (double-sub)
        by_score: dict[tuple[int, int], list] = defaultdict(list)
        for ch in td.changements:
            if ch.score_a is not None and ch.score_b is not None:
                by_score[(ch.score_a, ch.score_b)].append(ch)

        for (sc_a, sc_b), changes in by_score.items():
            if len(changes) < 2:
                continue
            for i, c1 in enumerate(changes):
                for c2 in changes[i + 1 :]:
                    if _is_opposite_pos(c1.position, c2.position):
                        front_c, back_c = (c1, c2) if c1.position in _FRONT_POSITIONS else (c2, c1)

                        f_out = _norm(front_c.joueur_sortant)
                        f_in = _norm(front_c.joueur_entrant)
                        b_out = _norm(back_c.joueur_sortant)
                        b_in = _norm(back_c.joueur_entrant)

                        # En passe-pointe, deux paires couplées :
                        # front swap (f_out, f_in) et back swap (b_out, b_in).
                        # L'un des deux entrants est Passeur, l'autre est Pointu.
                        # Déterminer l'orientation via la position de départ ou anchors
                        # Hypothèse A : f_out / b_in sont Setters, f_in / b_out sont Opposites
                        # Hypothèse B : f_in / b_out sont Setters, f_out / b_in sont Opposites
                        candidates_setters_a = {f_out, b_in}
                        candidates_setters_b = {f_in, b_out}

                        # Score d'orientation selon P1 ou evidence existante
                        vote_a = 0.0
                        vote_b = 0.0
                        for num in candidates_setters_a:
                            ev = context.players.get(num)
                            if ev and 1 in ev.starter_positions:
                                vote_a += 2.0
                            if ev and ev.passe_pointe_sub_as_setter > ev.passe_pointe_sub_as_opp:
                                vote_a += 1.5
                            if ev and ev.passe_pointe_sub_as_opp > ev.passe_pointe_sub_as_setter:
                                vote_b += 1.5

                        for num in candidates_setters_b:
                            ev = context.players.get(num)
                            if ev and 1 in ev.starter_positions:
                                vote_b += 2.0
                            if ev and ev.passe_pointe_sub_as_setter > ev.passe_pointe_sub_as_opp:
                                vote_b += 1.5
                            if ev and ev.passe_pointe_sub_as_opp > ev.passe_pointe_sub_as_setter:
                                vote_a += 1.5

                        use_a = vote_a >= vote_b
                        chosen_setters = candidates_setters_a if use_a else candidates_setters_b
                        chosen_opps = candidates_setters_b if use_a else candidates_setters_a

                        for setter_num in chosen_setters:
                            ev = context.players.get(setter_num)
                            if ev and not ev.is_explicit_libero:
                                ev.passe_pointe_sub_as_setter += 14.0
                                ev.add_hint(f"inversion passe-pointe comme passeur ({sc_a}-{sc_b})")
                        for opp_num in chosen_opps:
                            ev = context.players.get(opp_num)
                            if ev and not ev.is_explicit_libero:
                                ev.passe_pointe_sub_as_opp += 14.0
                                ev.add_hint(f"inversion passe-pointe comme pointu ({sc_a}-{sc_b})")

    return context


class TeamRoleSolver:
    """Solveur compositionnel avec satisfaction de contraintes et priors joueurs."""

    def __init__(
        self,
        context: TeamMatchContext,
        player_priors: Optional[dict[str, dict[str, float]]] = None,
        prior_weight: float = 2.4,
    ) -> None:
        self.ctx = context
        self.priors = player_priors or {}
        self.prior_weight = prior_weight

    def solve(self) -> dict[str, RoleInference]:
        """Résout l'affectation et retourne les inférences de rôles pour chaque joueur."""
        if not self.ctx.players:
            return {}

        players = list(self.ctx.players.values())
        player_nums = [p.numero for p in players]

        # 1. Potentiels unaires locaux (log-scores bruts)
        unary_scores: dict[str, dict[str, float]] = {
            num: {r: 1.0 for r in ALL_ROLES} for num in player_nums
        }
        evidence_breakdown: dict[str, dict[str, float]] = {
            num: {"local": 0.0, "rotation": 0.0, "prior": 0.0, "teammates": 0.0}
            for num in player_nums
        }

        for p in players:
            num = p.numero
            u = unary_scores[num]

            if p.is_explicit_libero:
                u[ROLE_LIBERO] += 40.0
                p.add_hint("libéro désigné sur la feuille de match")
                for r in (ROLE_SETTER, ROLE_OPPOSITE, ROLE_MIDDLE, ROLE_OUTSIDE):
                    u[r] = 0.05
                evidence_breakdown[num]["local"] += 10.0
                continue

            # Remplacement avec libéro (fort signal Central)
            if p.libero_back_replaces > 0:
                boost = p.libero_back_replaces * 5.5
                u[ROLE_MIDDLE] += boost
                evidence_breakdown[num]["local"] += boost

            # Remplacement libéro avant (signal plutôt RA ou dépannage)
            if p.libero_front_replaces > 0:
                boost = p.libero_front_replaces * 2.0
                u[ROLE_OUTSIDE] += boost
                evidence_breakdown[num]["local"] += boost

            # Inversions passe-pointe
            if p.passe_pointe_sub_as_setter > 0:
                u[ROLE_SETTER] += p.passe_pointe_sub_as_setter
                evidence_breakdown[num]["local"] += p.passe_pointe_sub_as_setter
            if p.passe_pointe_sub_as_opp > 0:
                u[ROLE_OPPOSITE] += p.passe_pointe_sub_as_opp
                evidence_breakdown[num]["local"] += p.passe_pointe_sub_as_opp

            # Position 1 au départ (dans 60% des équipes le passeur commence P1 pour servir)
            p1_count = sum(1 for pos in p.starter_positions if pos == 1)
            if p1_count > 0 and u[ROLE_SETTER] > 0:
                u[ROLE_SETTER] += p1_count * 1.8
                evidence_breakdown[num]["local"] += p1_count * 1.8
                p.add_hint(f"départ au service en P1 ({p1_count} set(s))")

            # Prior externe du joueur (saison ou carrière)
            prior_dist = self.priors.get(num)
            if prior_dist:
                best_prior_role, best_prior_prob = max(
                    prior_dist.items(), key=lambda item: item[1]
                )
                for r, prob in prior_dist.items():
                    if r in u:
                        # Log-prior pondéré
                        p_boost = self.prior_weight * (prob * 4.0)
                        u[r] += p_boost
                        evidence_breakdown[num]["prior"] += p_boost

                if best_prior_prob >= 0.50:
                    p.add_hint(
                        f"profil habituel du joueur : {ROLE_LABELS.get(best_prior_role, best_prior_role)} "
                        f"({round(best_prior_prob * 100)}%)"
                    )

        # 2. Déduction globale par triplets de rotation opposés
        # En volley 6x6, les 3 paires sont {P, O}, {C, C} et {RA, RA}.
        for triplet in self.ctx.set_triplets:
            if len(triplet) != 3:
                continue

            # Identifier la paire Setter-Opposite (celle contenant la plus forte évidence de passeur)
            setter_pair_idx = -1
            best_setter_ev = -1.0
            best_setter_num = None
            for idx, (p_a, p_b) in enumerate(triplet):
                sc_a = unary_scores[p_a][ROLE_SETTER]
                sc_b = unary_scores[p_b][ROLE_SETTER]
                max_sc = max(sc_a, sc_b)
                if max_sc > best_setter_ev:
                    best_setter_ev = max_sc
                    setter_pair_idx = idx
                    best_setter_num = p_a if sc_a >= sc_b else p_b

            # Parmi les 2 autres paires, identifier la paire de Centraux (celle avec le plus de signal Central/Libéro)
            middle_pair_idx = -1
            best_middle_ev = -1.0
            for idx, (p_a, p_b) in enumerate(triplet):
                if idx == setter_pair_idx:
                    continue
                sc_a = unary_scores[p_a][ROLE_MIDDLE]
                sc_b = unary_scores[p_b][ROLE_MIDDLE]
                ev_sum = sc_a + sc_b
                if ev_sum > best_middle_ev:
                    best_middle_ev = ev_sum
                    middle_pair_idx = idx

            # La 3e paire restante est OBLIGATOIREMENT la paire de Réceptionneurs-Attaquants !
            outside_candidates = [i for i in (0, 1, 2) if i not in (setter_pair_idx, middle_pair_idx)]
            outside_pair_idx = outside_candidates[0] if outside_candidates else -1

            # Force du triplet selon le nombre de sets et la certitude de la paire passeur
            triplet_factor = min(1.2, 0.45 + 0.35 * len(self.ctx.set_triplets))
            if setter_pair_idx >= 0 and best_setter_num:
                p_a, p_b = triplet[setter_pair_idx]
                s_num = best_setter_num
                o_num = p_b if s_num == p_a else p_a
                unary_scores[s_num][ROLE_SETTER] += 3.2 * triplet_factor
                unary_scores[o_num][ROLE_OPPOSITE] += 3.2 * triplet_factor
                evidence_breakdown[o_num]["rotation"] += 2.0 * triplet_factor
                self.ctx.players[o_num].add_hint(f"opposé au passeur #{s_num} en rotation")

            if middle_pair_idx >= 0:
                p_a, p_b = triplet[middle_pair_idx]
                unary_scores[p_a][ROLE_MIDDLE] += 2.8 * triplet_factor
                unary_scores[p_b][ROLE_MIDDLE] += 2.8 * triplet_factor
                evidence_breakdown[p_a]["rotation"] += 2.0 * triplet_factor
                evidence_breakdown[p_b]["rotation"] += 2.0 * triplet_factor
                self.ctx.players[p_a].add_hint(f"paire de centraux en rotation")
                self.ctx.players[p_b].add_hint(f"paire de centraux en rotation")

            if outside_pair_idx >= 0:
                p_a, p_b = triplet[outside_pair_idx]
                unary_scores[p_a][ROLE_OUTSIDE] += 3.6 * triplet_factor
                unary_scores[p_b][ROLE_OUTSIDE] += 3.6 * triplet_factor
                evidence_breakdown[p_a]["rotation"] += 2.4 * triplet_factor
                evidence_breakdown[p_b]["rotation"] += 2.4 * triplet_factor
                self.ctx.players[p_a].add_hint(f"paire de réceptionneurs-attaquants en rotation")
                self.ctx.players[p_b].add_hint(f"paire de réceptionneurs-attaquants en rotation")

        # 3. Diffusion par binômes de rotation opposés (Belief Propagation locale)
        # Pairs: Central-Central, Outside-Outside, Setter-Opposite
        for _iteration in range(3):
            updated_unary = {num: dict(scores) for num, scores in unary_scores.items()}

            for (p_a, p_b), sets_together in self.ctx.rotation_pairs.items():
                if p_a not in unary_scores or p_b not in unary_scores:
                    continue

                ev_a = self.ctx.players.get(p_a)
                ev_b = self.ctx.players.get(p_b)
                if (ev_a and ev_a.is_explicit_libero) or (ev_b and ev_b.is_explicit_libero):
                    continue

                w = min(3.0, sets_together * 1.4)
                scores_a = unary_scores[p_a]
                scores_b = unary_scores[p_b]

                # Si A a une forte probabilité d'être Central -> B est renforcé Central
                if scores_a[ROLE_MIDDLE] > max(scores_a[ROLE_SETTER], scores_a[ROLE_OUTSIDE]) * 1.2:
                    updated_unary[p_b][ROLE_MIDDLE] += scores_a[ROLE_MIDDLE] * 0.35 * w
                    evidence_breakdown[p_b]["rotation"] += 1.5 * w
                    ev_b.add_hint(f"opposé au central #{p_a} en rotation")

                if scores_b[ROLE_MIDDLE] > max(scores_b[ROLE_SETTER], scores_b[ROLE_OUTSIDE]) * 1.2:
                    updated_unary[p_a][ROLE_MIDDLE] += scores_b[ROLE_MIDDLE] * 0.35 * w
                    evidence_breakdown[p_a]["rotation"] += 1.5 * w
                    ev_a.add_hint(f"opposé au central #{p_b} en rotation")

                # Si A est RA -> B est renforcé RA
                if scores_a[ROLE_OUTSIDE] > max(scores_a[ROLE_SETTER], scores_a[ROLE_MIDDLE]) * 1.2:
                    updated_unary[p_b][ROLE_OUTSIDE] += scores_a[ROLE_OUTSIDE] * 0.35 * w
                    evidence_breakdown[p_b]["rotation"] += 1.4 * w
                    ev_b.add_hint(f"opposé au réceptionneur #{p_a} en rotation")

                if scores_b[ROLE_OUTSIDE] > max(scores_b[ROLE_SETTER], scores_b[ROLE_MIDDLE]) * 1.2:
                    updated_unary[p_a][ROLE_OUTSIDE] += scores_b[ROLE_OUTSIDE] * 0.35 * w
                    evidence_breakdown[p_a]["rotation"] += 1.4 * w
                    ev_a.add_hint(f"opposé au réceptionneur #{p_b} en rotation")

                # Si A est Passeur -> B est renforcé Pointu (et inversement)
                if scores_a[ROLE_SETTER] > scores_a[ROLE_OPPOSITE] * 1.3:
                    updated_unary[p_b][ROLE_OPPOSITE] += scores_a[ROLE_SETTER] * 0.40 * w
                    evidence_breakdown[p_b]["rotation"] += 1.6 * w
                    ev_b.add_hint(f"opposé au passeur #{p_a} en rotation")

                if scores_b[ROLE_SETTER] > scores_b[ROLE_OPPOSITE] * 1.3:
                    updated_unary[p_a][ROLE_OPPOSITE] += scores_b[ROLE_SETTER] * 0.40 * w
                    evidence_breakdown[p_a]["rotation"] += 1.6 * w
                    ev_a.add_hint(f"opposé au passeur #{p_b} en rotation")

                if scores_a[ROLE_OPPOSITE] > scores_a[ROLE_SETTER] * 1.3:
                    updated_unary[p_b][ROLE_SETTER] += scores_a[ROLE_OPPOSITE] * 0.40 * w
                    evidence_breakdown[p_b]["rotation"] += 1.6 * w
                    ev_b.add_hint(f"opposé au pointu #{p_a} en rotation")

                if scores_b[ROLE_OPPOSITE] > scores_b[ROLE_SETTER] * 1.3:
                    updated_unary[p_a][ROLE_SETTER] += scores_b[ROLE_OPPOSITE] * 0.40 * w
                    evidence_breakdown[p_a]["rotation"] += 1.6 * w
                    ev_a.add_hint(f"opposé au pointu #{p_b} en rotation")

            unary_scores = updated_unary

        # 4. Contrainte de budget d'équipe (Roster Budget Constraint)
        # Idéal : 1 P, 1 O, 2 RA, 2 C (+ 1 Libéro)
        # Gestion des Passeurs excédentaires
        setters = [
            (num, unary_scores[num][ROLE_SETTER])
            for num in player_nums
            if not self.ctx.players[num].is_explicit_libero
        ]
        setters.sort(key=lambda x: -x[1])
        if len(setters) > 1 and setters[0][1] >= 8.0:
            for sec_num, sec_score in setters[1:]:
                ev_sec = self.ctx.players[sec_num]
                if ev_sec.passe_pointe_sub_as_setter <= 0:
                    unary_scores[sec_num][ROLE_SETTER] *= 0.45
                    evidence_breakdown[sec_num]["teammates"] -= 1.0

        # Gestion des Pointus excédentaires (les attaquants d'aile surnuméraires sont RA)
        opposites = [
            (num, unary_scores[num][ROLE_OPPOSITE])
            for num in player_nums
            if not self.ctx.players[num].is_explicit_libero
        ]
        opposites.sort(key=lambda x: -x[1])
        max_opps = 2 if any(p.passe_pointe_sub_as_opp > 0 for p in players) else 1
        if len(opposites) > max_opps and opposites[0][1] >= 5.0:
            for sec_num, sec_score in opposites[max_opps:]:
                ev_sec = self.ctx.players[sec_num]
                if ev_sec.passe_pointe_sub_as_opp <= 0:
                    # Déplacer l'excès vers Réceptionneur-Attaquant
                    unary_scores[sec_num][ROLE_OUTSIDE] += unary_scores[sec_num][ROLE_OPPOSITE] * 0.70
                    unary_scores[sec_num][ROLE_OPPOSITE] *= 0.40
                    evidence_breakdown[sec_num]["teammates"] += 1.0

        # 4. Normalisation et calcul de la confiance calibrée
        results: dict[str, RoleInference] = {}
        for num, scores in unary_scores.items():
            ev = self.ctx.players[num]
            pos_scores = {r: max(0.01, sc) for r, sc in scores.items()}
            total = sum(pos_scores.values())
            normalized = {r: round(sc / total, 4) for r, sc in pos_scores.items()}

            sorted_roles = sorted(normalized.items(), key=lambda it: (-it[1], it[0]))
            primary_role, primary_prob = sorted_roles[0]
            second_role, second_prob = sorted_roles[1] if len(sorted_roles) > 1 else (None, 0.0)

            # Plausibles (au-dessus de 16%)
            plausibles = [r for r, pr in sorted_roles if pr >= 0.16][:3]
            if primary_role not in plausibles:
                plausibles.insert(0, primary_role)

            # Calibrage confiance :
            # 1. Marge (p1 - p2) : plus le rôle se détache, plus la confiance est haute
            margin = max(0.0, primary_prob - second_prob)
            # 2. Volume d'évidence de match
            match_volume_factor = min(1.0, (ev.sets_played * 0.25) + (ev.sets_starter * 0.15))
            # 3. Évidences factuelles directes (libéro, changements, rotation)
            has_double_sub = (ev.passe_pointe_sub_as_setter + ev.passe_pointe_sub_as_opp) > 0
            factual_evidence = min(
                1.0,
                (
                    (1.0 if ev.is_explicit_libero else 0.0)
                    + (min(ev.libero_back_replaces, 3) * 0.25)
                    + (0.8 if has_double_sub else 0.0)
                    + (0.35 if len(ev.starter_positions) >= 2 else (0.15 if (has_double_sub or ev.libero_back_replaces > 0) else 0.0))
                ),
            )

            # Formule calibrée de confiance globale entre 0.10 et 0.98
            raw_confidence = (
                0.35 * primary_prob
                + 0.30 * margin
                + 0.15 * match_volume_factor
                + 0.20 * factual_evidence
            )
            if ev.is_explicit_libero:
                raw_confidence = max(raw_confidence, 0.95)
            elif ev.sets_starter <= 1 and factual_evidence <= 0.20 and not self.priors.get(num):
                # Sur un seul set sans événement factuel marquant ni prior, rester mesuré
                raw_confidence = min(0.58, raw_confidence)

            calibrated_confidence = round(min(0.98, max(0.12, raw_confidence)), 3)

            # Détection de rôle atypique (changement de poste ponctuel)
            prior_dist = self.priors.get(num)
            is_atypique = False
            if prior_dist:
                prior_dominant = max(prior_dist.items(), key=lambda it: it[1])
                # Si le joueur joue habituellement un autre rôle (>55% de ses matchs)
                # mais que sur ce match le solveur lui trouve un autre rôle
                if (
                    prior_dominant[0] != primary_role
                    and prior_dominant[1] >= 0.55
                    and primary_prob >= 0.40
                ):
                    is_atypique = True
                    ev.add_hint(
                        f"rôle inhabituel sur ce match (habituellement {ROLE_LABELS.get(prior_dominant[0])})"
                    )

            results[num] = RoleInference(
                role_principal=primary_role,
                roles_possibles=plausibles,
                role_scores={r: round(p, 3) for r, p in normalized.items()},
                role_confiance=calibrated_confidence,
                indices=list(dict.fromkeys(ev.hints))[:6],
                role_atypique=is_atypique,
                composition_valid=True,
                evidence_breakdown={
                    k: round(v, 2) for k, v in evidence_breakdown[num].items()
                },
            )

        return results
