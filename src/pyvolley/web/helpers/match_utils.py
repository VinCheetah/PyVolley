"""
Utilitaires liés aux matchs pour l'interface web.

Contient la construction des données de simulation, l'évolution de niveau,
et la hiérarchie des niveaux de volley.
"""

from typing import Optional


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


def build_niveau_evolution(matchs, equipe) -> list:
    """Construit les données d'évolution du niveau pour le graphique.

    Pour chaque match joué, on regarde la compétition / le niveau de l'équipe
    au moment du match.

    Retourne une liste triée par date avec :
    - date, niveau, niveau_rank, adversaire, resultat, score, match_id, competition
    """
    points = []
    for m in matchs:
        if not m.match_joue or not m.date_match:
            continue

        niv = None
        if m.competition:
            niv = m.competition.niveau
        if not niv and equipe.niveau:
            niv = equipe.niveau

        rank = niveau_rank(niv)
        if rank is None and niv:
            rank = 2  # régional par défaut

        is_team_a = m.equipe_a_id == equipe.id
        opponent = m.equipe_b if is_team_a else m.equipe_a
        won = (is_team_a and m.sets_equipe_a > m.sets_equipe_b) or (
            not is_team_a and m.sets_equipe_b > m.sets_equipe_a
        )

        if is_team_a:
            score = f"{m.sets_equipe_a}-{m.sets_equipe_b}"
        else:
            score = f"{m.sets_equipe_b}-{m.sets_equipe_a}"

        points.append(
            {
                "date": str(m.date_match),
                "niveau": niv or "Inconnu",
                "niveau_rank": rank if rank is not None else 2,
                "adversaire": opponent.nom if opponent else "?",
                "resultat": "V" if won else "D",
                "score": score,
                "match_id": m.id,
                "competition": m.competition.nom if m.competition else "",
            }
        )

    points.sort(key=lambda p: p["date"])
    return points
