"""
Utilitaires liés aux matchs pour l'interface web.

Contient la construction des données de simulation, l'évolution de scores,
et la hiérarchie des niveaux de volley.
"""

from typing import Optional, Any

from pyvolley.analysis.joueur_stats import build_set_timeline


# Hiérarchie des niveaux de volley (du plus bas au plus haut)
NIVEAU_ORDER: dict[str, int] = {
    "LOISIR": 0,
    "DEPARTEMENTAL": 1, "DÉPARTEMENTAL": 1, "DEPARTEMENTALE": 1, "DÉPARTEMENTALE": 1,
    "PRE_REGIONALE": 2, "PRÉ_RÉGIONALE": 2, "PREREGIONALE": 2,
    "REGIONAL": 3, "RÉGIONAL": 3, "REGIONALE": 3, "RÉGIONALE": 3,
    "PRE_NATIONALE": 4, "PRÉNATIONAL": 4, "PRENATIONAL": 4,
    "PRENATIONALE": 4, "PRÉNATIONALE": 4,
    "PRE-NATIONAL": 4, "PRÉ-NATIONAL": 4, "PRE-NATIONALE": 4, "PRÉ-NATIONALE": 4,
    "NATIONAL": 5, "NATIONALE": 5,
    "N3": 5, "N2": 6, "N1": 7,
    "ELITE": 8, "ÉLITE": 8,
    "PRO": 9, "PRO B": 9, "PRO A": 10,
}


def niveau_rank(niveau_str: Optional[str]) -> Optional[int]:
    """Retourne le rang numérique d'un niveau, ou None si inconnu."""
    if not niveau_str:
        return None
    return NIVEAU_ORDER.get(niveau_str.upper().strip())


def build_simulation_data(
    match, participants_a, participants_b, officiels_a, officiels_b
) -> dict:
    """Construit les données JSON pour le visualiseur de simulation embarqué."""
    equipe_a_name = match.equipe_a.nom if match.equipe_a else "Équipe A"
    equipe_b_name = match.equipe_b.nom if match.equipe_b else "Équipe B"

    # Joueurs
    joueurs_a = [
        {
            "numero": p.numero_maillot or "?",
            "nom": p.joueur.nom if p.joueur else "?",
            "prenom": p.joueur.prenom if p.joueur else "",
            "est_capitaine": p.est_capitaine,
            "est_libero": p.est_libero,
        }
        for p in participants_a
    ]
    joueurs_b = [
        {
            "numero": p.numero_maillot or "?",
            "nom": p.joueur.nom if p.joueur else "?",
            "prenom": p.joueur.prenom if p.joueur else "",
            "est_capitaine": p.est_capitaine,
            "est_libero": p.est_libero,
        }
        for p in participants_b
    ]

    # Officiels
    off_a = [{"role": o.role, "nom": o.nom, "prenom": o.prenom} for o in officiels_a]
    off_b = [{"role": o.role, "nom": o.nom, "prenom": o.prenom} for o in officiels_b]

    # Arbitres
    arbitres = [
        {
            "nom": am.arbitre.nom if am.arbitre else "?",
            "prenom": am.arbitre.prenom if am.arbitre else "",
            "role": am.role,
        }
        for am in (match.arbitrages or [])
    ]

    # Sets
    sets_data = []
    for s in match.sets or []:
        set_entry = {
            "numero": s.numero,
            "score_a": s.score_a or 0,
            "score_b": s.score_b or 0,
            "heure_debut": s.heure_debut,
            "heure_fin": s.heure_fin,
            "duree_minutes": s.duree_minutes,
            "service_initial": s.service_initial,
            "services_a": s.services_a or {},
            "services_b": s.services_b or {},
            "formation_a": {},
            "formation_b": {},
            "changements_a": [],
            "changements_b": [],
            "timeouts_a": [],
            "timeouts_b": [],
        }

        for f in s.formations or []:
            key = f"formation_{f.equipe.lower()}"
            set_entry[key] = {
                f"position_{i}": getattr(f, f"position_{i}", "") or ""
                for i in range(1, 7)
            }

        for c in s.changements or []:
            entry = {
                "joueur_entrant": c.joueur_entrant,
                "joueur_sortant": c.joueur_sortant,
                "position": c.position,
                "score_a": c.score_a,
                "score_b": c.score_b,
            }
            if c.equipe == "A":
                set_entry["changements_a"].append(entry)
            else:
                set_entry["changements_b"].append(entry)

        for t in s.timeouts or []:
            entry = {"score_a": t.score_a, "score_b": t.score_b}
            if t.equipe == "A":
                set_entry["timeouts_a"].append(entry)
            else:
                set_entry["timeouts_b"].append(entry)

        sets_data.append(set_entry)

    # Sanctions
    sanctions = [
        {
            "type": s.type_sanction,
            "equipe": s.equipe,
            "set_numero": s.set_numero,
            "joueur_numero": s.joueur_numero,
            "score_a": s.score_a,
            "score_b": s.score_b,
        }
        for s in (match.sanctions or [])
    ]

    return {
        "code_match": match.code_match,
        "date": str(match.date_match) if match.date_match else "",
        "lieu": match.salle or "",
        "salle": match.salle or "",
        "competition": match.competition.nom if match.competition else "",
        "journee": match.journee or "",
        "duree_totale": match.duree_totale or "",
        "equipe_a": {"nom": equipe_a_name, "joueurs": joueurs_a, "officiels": off_a},
        "equipe_b": {"nom": equipe_b_name, "joueurs": joueurs_b, "officiels": off_b},
        "sets_a": match.sets_equipe_a,
        "sets_b": match.sets_equipe_b,
        "vainqueur": match.vainqueur or "",
        "sets": sets_data,
        "arbitres": arbitres,
        "sanctions": sanctions,
    }


def build_match_score_evolution(matchs, equipe) -> list[dict[str, Any]]:
    """Construit la série chronologique des scores de matchs d'une équipe.

    Chaque point représente un match joué avec le score du point de vue de
    l'équipe, son résultat (V/D), l'adversaire et l'URL de navigation.
    """
    points: list[dict[str, Any]] = []

    for m in matchs:
        if not m.match_joue or not m.date_match:
            continue

        is_team_a = m.equipe_a_id == equipe.id
        if not is_team_a and m.equipe_b_id != equipe.id:
            continue

        sets_for = m.sets_equipe_a if is_team_a else m.sets_equipe_b
        sets_against = m.sets_equipe_b if is_team_a else m.sets_equipe_a
        if sets_for is None or sets_against is None:
            continue

        opponent = m.equipe_b if is_team_a else m.equipe_a
        won = sets_for > sets_against

        points.append(
            {
                "date": str(m.date_match),
                "adversaire": opponent.nom if opponent else "?",
                "resultat": "V" if won else "D",
                "score": f"{sets_for}-{sets_against}",
                "sets_for": int(sets_for),
                "sets_against": int(sets_against),
                "match_id": int(m.id),
                "match_url": f"/matchs/{m.id}",
                "competition": m.competition.nom if m.competition else "",
            }
        )

    points.sort(key=lambda p: (p["date"], p["match_id"]))
    return points


def build_niveau_evolution(matchs, equipe) -> list[dict[str, Any]]:
    """Alias de compatibilité vers la série d'évolution des scores."""
    return build_match_score_evolution(matchs, equipe)


def build_momentum_data(match_db, match_core) -> dict[str, Any]:
    """Construit les données de momentum à partir de la timeline service-order.

    Le calcul est aligné avec ``analysis.joueur_stats.build_set_timeline``.
    """
    team_a_name = match_db.equipe_a.nom if match_db.equipe_a else "Équipe A"
    team_b_name = match_db.equipe_b.nom if match_db.equipe_b else "Équipe B"

    core_sets_by_num = {s.numero: s for s in (match_core.sets or [])}
    sets_payload: list[dict[str, Any]] = []

    for set_db in sorted((match_db.sets or []), key=lambda s: s.numero):
        core_set = core_sets_by_num.get(set_db.numero)
        if not core_set:
            continue

        turns = build_set_timeline(core_set)
        if not turns:
            continue

        score_a = 0
        score_b = 0
        point_index = 0
        points = [{"x": 0, "y": 0, "score_a": 0, "score_b": 0}]

        for turn in turns:
            service_points = max(0, int(turn.points_scored or 0))
            for _ in range(service_points):
                point_index += 1
                if turn.team == "A":
                    score_a += 1
                else:
                    score_b += 1
                points.append(
                    {
                        "x": point_index,
                        "y": score_a - score_b,
                        "score_a": score_a,
                        "score_b": score_b,
                        "winner": turn.team,
                        "phase": "service",
                    }
                )

            if not turn.is_set_winner:
                point_index += 1
                if turn.team == "A":
                    score_b += 1
                    winner = "B"
                else:
                    score_a += 1
                    winner = "A"
                points.append(
                    {
                        "x": point_index,
                        "y": score_a - score_b,
                        "score_a": score_a,
                        "score_b": score_b,
                        "winner": winner,
                        "phase": "sideout",
                    }
                )

        events: list[dict[str, Any]] = []
        for timeout in (set_db.timeouts or []):
            if timeout.score_a is None or timeout.score_b is None:
                continue
            events.append(
                {
                    "type": "timeout",
                    "team": timeout.equipe,
                    "score_a": timeout.score_a,
                    "score_b": timeout.score_b,
                    "x": timeout.score_a + timeout.score_b,
                    "y": timeout.score_a - timeout.score_b,
                }
            )

        for change in (set_db.changements or []):
            if change.score_a is None or change.score_b is None:
                continue
            events.append(
                {
                    "type": "sub",
                    "team": change.equipe,
                    "score_a": change.score_a,
                    "score_b": change.score_b,
                    "x": change.score_a + change.score_b,
                    "y": change.score_a - change.score_b,
                    "entrant": change.joueur_entrant,
                    "sortant": change.joueur_sortant,
                }
            )

        events.sort(key=lambda item: (item["x"], 0 if item["type"] == "timeout" else 1))

        sets_payload.append(
            {
                "numero": set_db.numero,
                "score_a_final": set_db.score_a or score_a,
                "score_b_final": set_db.score_b or score_b,
                "points": points,
                "events": events,
            }
        )

    return {
        "teams": {"A": team_a_name, "B": team_b_name},
        "sets": sets_payload,
    }
