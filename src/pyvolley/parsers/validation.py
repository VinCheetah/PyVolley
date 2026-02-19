"""
Validation de cohérence des données parsées.

Vérifie : informations générales, équipes, scores, formations,
changements, et cohérence inter-champs.

Renvoie des *Diagnostic* structurés (niveau, origine, catégorie).
"""

from __future__ import annotations

from typing import Optional

from pyvolley.core.models import Match
from pyvolley.parsers.diagnostics import (
    Diagnostic, DiagnosticCategory as Cat,
)
from pyvolley.parsers.utils import best_team_match
from pyvolley.parsers.extractors.resultats import detect_set_target_score


def validate_match(
    match: Match, *, is_modern: bool = True,
) -> list[Diagnostic]:
    """Valide la cohérence des données parsées.

    Args:
        match: Le match parsé.
        is_modern: True si la saison est >= 2024-2025.

    Returns:
        Liste de Diagnostic structurés.
    """
    diags: list[Diagnostic] = []

    # ── Informations générales ──
    if not match.code_match or match.code_match == "UNKNOWN":
        diags.append(Diagnostic.data_warning(
            Cat.CODE_MATCH, "Code match manquant ou non détecté",
        ))
    if not match.date:
        diags.append(Diagnostic.data_warning(
            Cat.DATE, "Date du match manquante",
        ))
    if not match.saison:
        diags.append(Diagnostic.data_warning(
            Cat.SAISON, "Saison non déterminée",
        ))
    if not match.competition:
        diags.append(Diagnostic.data_warning(
            Cat.COMPETITION, "Nom de compétition manquant",
        ))

    # ── Équipes ──
    for label, eq in [('A', match.equipe_a), ('B', match.equipe_b)]:
        if not eq:
            diags.append(Diagnostic.parse_warning(
                Cat.EQUIPE, f"Équipe {label} non détectée",
                equipe=label,
            ))
            continue
        if not eq.nom or eq.nom in ("Équipe A", "Équipe B"):
            diags.append(Diagnostic.data_warning(
                Cat.EQUIPE, f"Nom d'équipe {label} manquant ou générique",
                equipe=label,
            ))
        if not eq.joueurs:
            diags.append(Diagnostic.data_warning(
                Cat.JOUEUR, f"Aucun joueur pour l'équipe {label}",
                equipe=label,
            ))

    # ── Cohérence des scores (match joué uniquement) ──
    if match.match_joue:
        # Vainqueur vs équipes
        if match.vainqueur_nom and match.equipe_a and match.equipe_b:
            best = best_team_match(
                match.vainqueur_nom,
                match.equipe_a.nom,
                match.equipe_b.nom,
            )
            if best is None:
                diags.append(Diagnostic.parse_warning(
                    Cat.COHERENCE,
                    f"Vainqueur '{match.vainqueur_nom}' ne correspond ni à "
                    f"'{match.equipe_a.nom}' ni à '{match.equipe_b.nom}'",
                ))

        if match.has_details and match.score_final and match.sets:
            try:
                sa, sb = match.score_final.split('/')
                expected_sets = int(sa) + int(sb)
                if len(match.sets) != expected_sets:
                    diags.append(Diagnostic.parse_warning(
                        Cat.COHERENCE,
                        f"Score final {match.score_final} implique "
                        f"{expected_sets} sets, mais "
                        f"{len(match.sets)} sets parsés",
                    ))
            except Exception:
                pass

            target_score = detect_set_target_score(
                match.competition, match.sets,
            )

            winning_sets = max(match.sets_a, match.sets_b)
            if winning_sets <= 1:
                deciding_set = 1
            elif winning_sets == 2:
                deciding_set = 3
            else:
                deciding_set = 5

            tiebreak_target = 15
            if target_score <= 15:
                tiebreak_target = target_score

            for s in match.sets:
                if s.score_a is None or s.score_b is None:
                    diags.append(Diagnostic.data_warning(
                        Cat.SCORE,
                        f"Set {s.numero}: score manquant "
                        f"({s.score_a}-{s.score_b})",
                        set_numero=s.numero,
                    ))
                elif s.score_a == 0 and s.score_b == 0:
                    diags.append(Diagnostic.data_warning(
                        Cat.SCORE,
                        f"Set {s.numero}: score 0-0 "
                        f"(probablement non renseigné)",
                        set_numero=s.numero,
                    ))
                else:
                    high = max(s.score_a, s.score_b)
                    low = min(s.score_a, s.score_b)

                    expected = (
                        tiebreak_target
                        if s.numero == deciding_set
                        else target_score
                    )

                    if high < expected:
                        diags.append(Diagnostic.data_warning(
                            Cat.SCORE,
                            f"Set {s.numero}: score "
                            f"{s.score_a}-{s.score_b} n'atteint pas "
                            f"{expected} points (format détecté: "
                            f"{target_score}pts)",
                            set_numero=s.numero,
                        ))
                    elif high > expected and (high - low) < 2:
                        diags.append(Diagnostic.data_warning(
                            Cat.SCORE,
                            f"Set {s.numero}: score "
                            f"{s.score_a}-{s.score_b} en prolongation "
                            f"mais écart < 2 points",
                            set_numero=s.numero,
                        ))
                    elif high == expected and (high - low) < 2:
                        diags.append(Diagnostic.data_warning(
                            Cat.SCORE,
                            f"Set {s.numero}: score "
                            f"{s.score_a}-{s.score_b} — le gagnant "
                            f"doit avoir 2 points d'avance",
                            set_numero=s.numero,
                        ))

            # Score final vs sets effectivement gagnés
            if match.sets_a + match.sets_b > 0:
                computed_a = sum(
                    1 for s in match.sets
                    if s.score_a is not None and s.score_b is not None
                    and s.score_a > s.score_b
                )
                computed_b = sum(
                    1 for s in match.sets
                    if s.score_a is not None and s.score_b is not None
                    and s.score_b > s.score_a
                )
                if computed_a + computed_b > 0:
                    if (computed_a != match.sets_a
                            or computed_b != match.sets_b):
                        diags.append(Diagnostic.parse_warning(
                            Cat.COHERENCE,
                            f"Incohérence score: final "
                            f"{match.sets_a}/{match.sets_b} vs calculé "
                            f"{computed_a}/{computed_b} depuis scores "
                            f"de sets",
                        ))

        # ── Formations vs effectif ──
        if match.has_details and match.sets:
            _validate_formations(match, diags)

    return diags


def _validate_formations(
    match: Match, diags: list[Diagnostic],
) -> None:
    """Valide que les numéros des formations et changements existent."""

    def _norm(n: str) -> str:
        return n.lstrip('0') or '0'

    for label, eq in [('A', match.equipe_a), ('B', match.equipe_b)]:
        if not eq or not eq.joueurs:
            continue

        roster_nums_raw = {j.numero for j in eq.joueurs if j.numero}
        roster_norm = {_norm(n) for n in roster_nums_raw}

        for s in match.sets:
            form = s.formation_a if label == 'A' else s.formation_b
            if not form:
                continue

            for pos_idx, num in enumerate(form.as_list()):
                if num and _norm(num) not in roster_norm:
                    diags.append(Diagnostic.parse_warning(
                        Cat.FORMATION,
                        f"Set {s.numero}, équipe {label}: joueur "
                        f"#{num} en position {pos_idx + 1} absent "
                        f"de l'effectif "
                        f"({sorted(roster_nums_raw)})",
                        equipe=label, set_numero=s.numero,
                    ))

            team_data = s.equipe_a if label == 'A' else s.equipe_b
            if team_data:
                for ch in team_data.changements:
                    if ch.joueur_entrant and \
                       _norm(ch.joueur_entrant) not in roster_norm:
                        diags.append(Diagnostic.parse_warning(
                            Cat.FORMATION,
                            f"Set {s.numero}, équipe {label}: "
                            f"remplaçant #{ch.joueur_entrant} "
                            f"absent de l'effectif",
                            equipe=label, set_numero=s.numero,
                        ))
