"""
Helper pour la construction du tableau croisé des confrontations (matrice aller-retour).

Construit une matrice à double entrée :
- Lignes : Équipe hôte (domicile), ordonnées par points/classement
- Colonnes : Équipe visiteuse (extérieur), ordonnées de manière identique
- Diagonale : Neutralisée
- Cellules : Colorisées et renseignées selon le résultat par set
"""

from __future__ import annotations

import re
from typing import Any, Optional


def _generate_short_team_name(nom: str, max_len: int = 3) -> str:
    """Génère un trigramme ou code court élégant pour les en-têtes de colonnes."""
    if not nom:
        return "EQ"
    clean = re.sub(r"[^A-Za-z0-9\s]", " ", nom).strip()
    words = [w for w in clean.split() if w.upper() not in ("VOLLEY", "BALL", "VB", "VBC", "CLUB", "AS", "US", "ES", "CO")]
    if not words:
        words = clean.split()

    if len(words) >= 3:
        code = "".join(w[0] for w in words[:max_len]).upper()
    elif len(words) == 2:
        code = (words[0][:2] + words[1][:1]).upper() if max_len == 3 else (words[0][:2] + words[1][:2]).upper()
    elif words:
        code = words[0][:max_len].upper()
    else:
        code = nom[:max_len].upper()

    return code[:max_len]


def build_cross_table(
    equipes_classement: list[Any],
    matchs: list[Any],
    equipes_disponibles: list[Any] | None = None,
) -> dict[str, Any]:
    """Construit la structure de données pour le tableau croisé des confrontations.

    Args:
        equipes_classement: Liste d'objets LigneClassement (ou dictionnaires)
                            déjà triés par classement/points.
        matchs: Liste des objets MatchDB ou MatchData de la compétition ou de la poule.
        equipes_disponibles: Liste optionnelle d'objets EquipeDB enregistrés.

    Returns:
        Dictionnaire avec équipes, lignes, cellules et statistiques globales.
    """
    # ── 1. Extraire et normaliser les équipes ──
    teams: list[dict[str, Any]] = []
    seen_team_ids: set[int] = set()

    # D'abord : Équipes issues du classement (déjà ordonnées par rang / points)
    if equipes_classement:
        for idx, item in enumerate(equipes_classement):
            eq_id = getattr(item, "equipe_id", None)
            if eq_id is None and isinstance(item, dict):
                eq_id = item.get("equipe_id")
            eq_nom = getattr(item, "equipe_nom", None)
            if not eq_nom and isinstance(item, dict):
                eq_nom = item.get("equipe_nom", "")
            eq_nom = str(eq_nom or "")

            rang = getattr(item, "rang", idx + 1)
            if rang is None and isinstance(item, dict):
                rang = item.get("rang", idx + 1)
            points = getattr(item, "points", 0)
            if points is None and isinstance(item, dict):
                points = item.get("points", 0)
            victoires = getattr(item, "victoires", 0)
            if victoires is None and isinstance(item, dict):
                victoires = item.get("victoires", 0)
            defaites = getattr(item, "defaites", 0)
            if defaites is None and isinstance(item, dict):
                defaites = item.get("defaites", 0)

            if eq_id is not None and eq_id not in seen_team_ids:
                seen_team_ids.add(eq_id)
                teams.append({
                    "id": eq_id,
                    "nom": eq_nom,
                    "nom_court": _generate_short_team_name(eq_nom),
                    "rang": rang,
                    "points": points or 0,
                    "victoires": victoires or 0,
                    "defaites": defaites or 0,
                })

    # Ensuite : Extraire les équipes présentes dans les matchs non encore classées
    extra_teams: dict[int, str] = {}
    for m in matchs:
        a_id = getattr(m, "equipe_a_id", None)
        if a_id and a_id not in seen_team_ids and a_id not in extra_teams:
            a_nom = None
            eq_a = getattr(m, "equipe_a", None)
            if eq_a:
                a_nom = getattr(eq_a, "nom", None)
            if not a_nom:
                a_nom = getattr(m, "equipe_a_nom", None)
            if not a_nom:
                a_nom = f"Équipe {a_id}"
            extra_teams[a_id] = str(a_nom)

        b_id = getattr(m, "equipe_b_id", None)
        if b_id and b_id not in seen_team_ids and b_id not in extra_teams:
            b_nom = None
            eq_b = getattr(m, "equipe_b", None)
            if eq_b:
                b_nom = getattr(eq_b, "nom", None)
            if not b_nom:
                b_nom = getattr(m, "equipe_b_nom", None)
            if not b_nom:
                b_nom = f"Équipe {b_id}"
            extra_teams[b_id] = str(b_nom)

    # Ensuite : Équipes disponibles enregistrées (si fournies)
    if equipes_disponibles:
        for eq in equipes_disponibles:
            eq_id = getattr(eq, "id", None) or (eq.get("id") if isinstance(eq, dict) else None)
            eq_nom = getattr(eq, "nom", None) or (eq.get("nom") if isinstance(eq, dict) else "")
            if eq_id and eq_id not in seen_team_ids and eq_id not in extra_teams:
                extra_teams[eq_id] = str(eq_nom)

    # Ajouter les équipes supplémentaires triées par nom
    for t_id, t_nom in sorted(extra_teams.items(), key=lambda t: t[1]):
        seen_team_ids.add(t_id)
        teams.append({
            "id": t_id,
            "nom": t_nom,
            "nom_court": _generate_short_team_name(t_nom),
            "rang": len(teams) + 1,
            "points": 0,
            "victoires": 0,
            "defaites": 0,
        })

    if not teams:
        return {
            "equipes": [],
            "rows": [],
            "nb_equipes": 0,
            "nb_matchs_joues": 0,
            "nb_matchs_total": 0,
            "victoires_domicile": 0,
            "victoires_exterieur": 0,
            "pct_victoires_domicile": 0.0,
            "has_matches": False,
            "scores_distribution": {},
        }

    # ── 2. Indexer les matchs par paire (equipe_a_id, equipe_b_id) ──
    match_map: dict[tuple[int, int], Any] = {}
    for m in matchs:
        a_id = getattr(m, "equipe_a_id", None)
        b_id = getattr(m, "equipe_b_id", None)
        if a_id and b_id:
            # Si confrontation multiple, privilégier le match joué
            if (a_id, b_id) in match_map:
                curr = match_map[(a_id, b_id)]
                curr_played = bool(
                    getattr(curr, "match_joue", False)
                    or (getattr(curr, "sets_equipe_a", 0) or 0) > 0
                    or (getattr(curr, "sets_equipe_b", 0) or 0) > 0
                )
                m_played = bool(
                    getattr(m, "match_joue", False)
                    or (getattr(m, "sets_equipe_a", 0) or 0) > 0
                    or (getattr(m, "sets_equipe_b", 0) or 0) > 0
                )
                if not curr_played and m_played:
                    match_map[(a_id, b_id)] = m
            else:
                match_map[(a_id, b_id)] = m

    # ── 3. Statistiques globales ──
    nb_matchs_joues = 0
    victoires_domicile = 0
    victoires_exterieur = 0
    scores_dist = {
        "3-0": 0,
        "3-1": 0,
        "3-2": 0,
        "2-3": 0,
        "1-3": 0,
        "0-3": 0,
        "forfait": 0,
    }

    # ── 4. Construire la matrice ligne par ligne ──
    rows: list[dict[str, Any]] = []

    for host in teams:
        row_cells: list[dict[str, Any]] = []
        host_victoires_dom = 0
        host_defaites_dom = 0
        host_points_dom = 0

        for guest in teams:
            is_diagonal = (host["id"] == guest["id"])
            match = match_map.get((host["id"], guest["id"])) if not is_diagonal else None

            if is_diagonal:
                row_cells.append({
                    "is_diagonal": True,
                    "has_match": False,
                    "host_id": host["id"],
                    "guest_id": guest["id"],
                    "css_class": "matrix-cell-diagonal",
                    "score_display": "",
                    "tooltip_title": f"{host['nom']}",
                    "tooltip_body": "Confrontation directe impossible",
                })
                continue

            if not match:
                row_cells.append({
                    "is_diagonal": False,
                    "has_match": False,
                    "host_id": host["id"],
                    "guest_id": guest["id"],
                    "css_class": "matrix-cell-empty",
                    "score_display": "—",
                    "tooltip_title": f"{host['nom']} vs {guest['nom']}",
                    "tooltip_body": "Match non programmé",
                })
                continue

            # Un match existe
            match_id = getattr(match, "id", None) or getattr(match, "match_id", None)
            code_match = getattr(match, "code_match", "")
            date_val = getattr(match, "date_match", None)
            date_str = date_val.strftime("%d/%m/%Y") if hasattr(date_val, "strftime") else str(date_val or "")
            journee = getattr(match, "journee", "") or ""
            statut = getattr(match, "statut", "sans_résultat")

            sets_hote = getattr(match, "sets_equipe_a", None)
            if sets_hote is None:
                sets_hote = getattr(match, "sets_a", 0)
            sets_hote = sets_hote or 0

            sets_visiteur = getattr(match, "sets_equipe_b", None)
            if sets_visiteur is None:
                sets_visiteur = getattr(match, "sets_b", 0)
            sets_visiteur = sets_visiteur or 0

            is_forfait = bool(getattr(match, "forfait", False) or statut == "forfait")

            # Détection robuste du match joué : booléen match_joue, scores de sets présents, ou statut
            is_played = (
                getattr(match, "match_joue", False)
                or getattr(match, "is_played", False)
                or statut in ("joué", "forfait", "termine", "terminé")
                or (sets_hote > 0 or sets_visiteur > 0)
                or is_forfait
            )

            # Formattage des sets individuels
            sets_details_list = []
            sets_rel = getattr(match, "sets", None)
            if sets_rel:
                for s in sorted(sets_rel, key=lambda x: getattr(x, "numero", 0)):
                    sa = getattr(s, "score_a", None)
                    sb = getattr(s, "score_b", None)
                    if sa is not None and sb is not None:
                        sets_details_list.append(f"{sa}-{sb}")
            if not sets_details_list and getattr(match, "score_sets", None):
                score_s = str(getattr(match, "score_sets"))
                if "/" in score_s:
                    sets_details_list = [p.replace("/", "-") for p in score_s.split()]
            sets_detail_str = ", ".join(sets_details_list)

            if is_played and (sets_hote > 0 or sets_visiteur > 0 or is_forfait):
                nb_matchs_joues += 1
                is_double_forfait = bool(
                    getattr(match, "is_double_forfait", False)
                    or (is_forfait and sets_hote == 0 and sets_visiteur == 0 and not getattr(match, "vainqueur", None))
                )
                victoire_hote = (sets_hote > sets_visiteur) and not is_double_forfait
                victoire_visiteur = (sets_visiteur > sets_hote) and not is_double_forfait

                if victoire_hote:
                    host_victoires_dom += 1
                    victoires_domicile += 1
                elif victoire_visiteur:
                    host_defaites_dom += 1
                    victoires_exterieur += 1
                elif is_double_forfait:
                    host_defaites_dom += 1

                # Attribution des points et classes selon le score en sets
                score_tuple = (sets_hote, sets_visiteur)
                if is_forfait:
                    scores_dist["forfait"] += 1
                    if is_double_forfait:
                        css_class = "matrix-cell-forfait-double"
                        score_display = "P-P"
                        badge_label = "2F"
                        pts_hote, pts_visiteur = -1, -1
                    elif victoire_hote:
                        css_class = "matrix-cell-forfait-win"
                        score_display = f"{sets_hote}-{sets_visiteur}" if (sets_hote or sets_visiteur) else "3-0"
                        badge_label = "F"
                        pts_hote, pts_visiteur = 3, -1
                    else:
                        css_class = "matrix-cell-forfait-loss"
                        score_display = f"{sets_hote}-{sets_visiteur}" if (sets_hote or sets_visiteur) else "0-3"
                        badge_label = "F"
                        pts_hote, pts_visiteur = -1, 3
                elif score_tuple == (3, 0):
                    scores_dist["3-0"] += 1
                    css_class = "matrix-cell-win-3-0"
                    score_display = "3-0"
                    badge_label = "+3"
                    pts_hote, pts_visiteur = 3, 0
                elif score_tuple == (3, 1):
                    scores_dist["3-1"] += 1
                    css_class = "matrix-cell-win-3-1"
                    score_display = "3-1"
                    badge_label = "+3"
                    pts_hote, pts_visiteur = 3, 0
                elif score_tuple == (3, 2):
                    scores_dist["3-2"] += 1
                    css_class = "matrix-cell-win-3-2"
                    score_display = "3-2"
                    badge_label = "+2"
                    pts_hote, pts_visiteur = 2, 1
                elif score_tuple == (2, 3):
                    scores_dist["2-3"] += 1
                    css_class = "matrix-cell-loss-2-3"
                    score_display = "2-3"
                    badge_label = "+1"
                    pts_hote, pts_visiteur = 1, 2
                elif score_tuple == (1, 3):
                    scores_dist["1-3"] += 1
                    css_class = "matrix-cell-loss-1-3"
                    score_display = "1-3"
                    badge_label = "0"
                    pts_hote, pts_visiteur = 0, 3
                elif score_tuple == (0, 3):
                    scores_dist["0-3"] += 1
                    css_class = "matrix-cell-loss-0-3"
                    score_display = "0-3"
                    badge_label = "0"
                    pts_hote, pts_visiteur = 0, 3
                else:
                    # Score atypique
                    pts_hote = 3 if victoire_hote else 0
                    pts_visiteur = 0 if victoire_hote else 3
                    css_class = "matrix-cell-win-3-0" if victoire_hote else "matrix-cell-loss-0-3"
                    score_display = f"{sets_hote}-{sets_visiteur}"
                    badge_label = ""

                host_points_dom += pts_hote

                # Libellés riches pour popover / tooltip
                prefix_j = f"J{journee} • " if journee else ""
                tooltip_title = f"{prefix_j}{host['nom']} vs {guest['nom']}"
                tooltip_score = f"{score_display} ({sets_detail_str})" if sets_detail_str else score_display
                tooltip_pts = f"+{pts_hote} pts pour {host['nom']} | +{pts_visiteur} pts pour {guest['nom']}"

                row_cells.append({
                    "is_diagonal": False,
                    "has_match": True,
                    "match_id": match_id,
                    "code_match": code_match,
                    "date_str": date_str,
                    "journee": journee,
                    "statut": statut,
                    "is_played": True,
                    "is_forfait": is_forfait,
                    "sets_hote": sets_hote,
                    "sets_visiteur": sets_visiteur,
                    "score_display": score_display,
                    "badge_label": badge_label,
                    "sets_detail_str": sets_detail_str,
                    "victoire_hote": victoire_hote,
                    "points_hote": pts_hote,
                    "points_visiteur": pts_visiteur,
                    "css_class": css_class,
                    "host_id": host["id"],
                    "guest_id": guest["id"],
                    "tooltip_title": tooltip_title,
                    "tooltip_body": f"Score : {tooltip_score}\nPoints : {tooltip_pts}",
                })
            else:
                # Match programmé mais non joué
                prefix_j = f"J{journee}" if journee else "À venir"
                row_cells.append({
                    "is_diagonal": False,
                    "has_match": True,
                    "match_id": match_id,
                    "code_match": code_match,
                    "date_str": date_str,
                    "journee": journee,
                    "statut": statut,
                    "is_played": False,
                    "is_forfait": False,
                    "sets_hote": None,
                    "sets_visiteur": None,
                    "score_display": prefix_j if prefix_j else "—",
                    "badge_label": "",
                    "sets_detail_str": "",
                    "victoire_hote": None,
                    "points_hote": 0,
                    "points_visiteur": 0,
                    "css_class": "matrix-cell-upcoming",
                    "host_id": host["id"],
                    "guest_id": guest["id"],
                    "tooltip_title": f"{host['nom']} vs {guest['nom']}",
                    "tooltip_body": f"Prévu le {date_str}" if date_str else f"Match prévu ({prefix_j})",
                })

        rows.append({
            "hote": host,
            "cells": row_cells,
            "stats_domicile": {
                "victoires": host_victoires_dom,
                "defaites": host_defaites_dom,
                "points": host_points_dom,
                "total_joues": host_victoires_dom + host_defaites_dom,
            },
        })

    nb_total_matchs = len(matchs)
    pct_victoires_dom = round(victoires_domicile / nb_matchs_joues * 100, 1) if nb_matchs_joues > 0 else 0.0

    return {
        "equipes": teams,
        "rows": rows,
        "nb_equipes": len(teams),
        "nb_matchs_joues": nb_matchs_joues,
        "nb_matchs_total": nb_total_matchs,
        "victoires_domicile": victoires_domicile,
        "victoires_exterieur": victoires_exterieur,
        "pct_victoires_domicile": pct_victoires_dom,
        "has_matches": (nb_matchs_joues > 0 or len(matchs) > 0),
        "scores_distribution": scores_dist,
    }
