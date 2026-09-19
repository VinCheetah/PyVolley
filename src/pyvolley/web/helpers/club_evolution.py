"""
Helper pour l'analyse et la visualisation de l'évolution des niveaux d'équipe d'un club.

Architecture adaptée aux exigences :
1. Graphique Principal : rassemble Hommes, Femmes et Jeunes (hors CdF) sur le même graphique
   - Couleurs différenciées Hommes (bleus) vs Femmes (roses/violets)
   - Axe Y adapté aux niveaux concernés (ex: si max = Prénat, rien au-dessus)
   - Anti-superposition (Jitter offset) pour séparer les équipes dans une même division
2. Graphique Coupe de France : dédié aux participations en Coupe de France
   - Axe Y = Catégories d'âge (M11, M13, M15, M18, M21, Senior...)
   - Axe Y adapté aux seules catégories concernées du club
   - Couleurs différenciées Hommes vs Femmes avec anti-superposition
   - Affiché UNIQUEMENT si le club a des équipes en Coupe de France
3. Récapitulatif interactif des changements de niveau (Promotions, Relégations, Maintiens, Créations)
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pyvolley.shared.categorisation import (
    is_youth_category,
    normalize_categorie,
    normalize_genre,
    normalize_text_upper,
)
from pyvolley.web.helpers.common import season_sort_key
from pyvolley.shared.niveau import (
    build_contextual_level_ladder,
    classify_level,
    resolve_niveau_badge,
)

# ── Échelle des niveaux pour le graphique principal ──
CHAMPIONSHIP_LEVEL_SCORES: dict[str, float] = {
    "PRO A": 17.0,
    "PRO B": 16.0,
    "PRO": 16.0,
    "ELITE": 15.0,
    "ÉLITE": 15.0,
    "JEUNES ELITE": 15.0,
    "ELITE AVENIR": 14.0,
    "ÉLITE AVENIR": 14.0,
    "N1": 13.0,
    "JEUNES N1": 13.0,
    "N2": 12.0,
    "JEUNES N2": 12.0,
    "N3": 11.0,
    "JEUNES N3": 11.0,
    "NATIONAL": 11.5,
    "PRENAT": 10.0,
    "PRÉNAT": 10.0,
    "R1": 9.0,
    "JEUNES R1": 9.0,
    "R2": 8.0,
    "JEUNES R2": 8.0,
    "R3": 7.0,
    "R4": 7.0,
    "REGIONAL": 8.5,
    "RÉGIONAL": 8.5,
    "JEUNES REGIONAL": 8.5,
    "JEUNES RÉGIONAL": 8.5,
    "PREREG": 6.0,
    "PRÉREG": 6.0,
    "D1": 4.0,
    "JEUNES D1": 4.0,
    "D2": 3.0,
    "JEUNES D2": 3.0,
    "D3": 2.0,
    "D4": 1.0,
    "DEP": 3.0,
    "DÉP": 3.0,
    "JEUNES DEP": 3.0,
    "JEUNES DÉP": 3.0,
    "LOISIR": 0.0,
}

CHAMPIONSHIP_Y_TICKS_ALL: list[tuple[float, str]] = [
    (17.0, "Pro A"),
    (16.0, "Pro B"),
    (15.0, "Élite"),
    (14.0, "Élite Avenir"),
    (13.0, "N1"),
    (12.0, "N2"),
    (11.0, "N3"),
    (10.0, "Prénat"),
    (9.0, "R1"),
    (8.0, "R2"),
    (7.0, "R3"),
    (6.0, "Préreg"),
    (4.0, "D1"),
    (3.0, "D2"),
    (2.0, "D3"),
    (1.0, "D4"),
    (0.0, "Loisir"),
]

# ── Échelle des catégories d'âge pour la Coupe de France ──
CDF_AGE_CATEGORY_SCORES: dict[str, float] = {
    "M9": 1.0,
    "M11": 2.0,
    "M13": 3.0,
    "M15": 4.0,
    "M18": 5.0,
    "M21": 6.0,
    "SENIOR": 7.0,
    "VOLLEY ASSIS": 8.0,
    "MASTERS": 9.0,
}

CDF_AGE_TICKS_ALL: list[tuple[float, str]] = [
    (1.0, "M9"),
    (2.0, "M11"),
    (3.0, "M13"),
    (4.0, "M15"),
    (5.0, "M18"),
    (6.0, "M21"),
    (7.0, "Senior"),
    (8.0, "Volley Assis"),
    (9.0, "Masters"),
]

# Couleurs thématiques distinctes : 1 seule couleur pour Hommes, 1 seule couleur pour Femmes
COLOR_HOMMES = "#3b82f6"  # Bleu royal éclatant pour tous les hommes
COLOR_FEMMES = "#ec4899"  # Rose fuchsia éclatant pour toutes les femmes
COLOR_LOISIR = "#f59e0b"  # Ambre pour le loisir

PALETTE_HOMMES = [COLOR_HOMMES]
PALETTE_FEMMES = [COLOR_FEMMES]
PALETTE_LOISIR = [COLOR_LOISIR]


def _extract_team_number(team_nom: str) -> int:
    """Déduit le numéro d'équipe (1 pour l'équipe fanion, 2 pour la réserve, etc.)."""
    cleaned = team_nom.strip()
    m = re.search(r"(?:^|\s|-|_)([1-9])$", cleaned)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([1-9])\b", cleaned)
    if m:
        return int(m.group(1))
    return 1


def _is_loisir_or_mixte(genre: str | None, categorie: str | None, comp_name: str | None, niv: str | None) -> bool:
    text = f"{genre or ''} {categorie or ''} {comp_name or ''} {niv or ''}".upper()
    if any(k in text for k in (
        "LOISIR", "BRASSAGE", "DETENTE", "DÉTENTE",
        "COMPET'LIB", "COMPET LIB", "COMPETLIB",
        "COMPET'MOUV", "COMPET MOUV", "COMPETMOUV",
        "COMPET'FUN", "COMPET FUN", "COMPETFUN",
    )):
        return True
    if genre and "MIXTE" in genre.upper():
        return True
    return False


def _is_coupe_de_france(
    comp_name: str | None,
    raw_niv: str | None = None,
    comp_code: str | None = None,
    entite_code: str | None = None,
    entite_nom: str | None = None,
) -> bool:
    text = f"{comp_name or ''} {raw_niv or ''} {comp_code or ''} {entite_code or ''} {entite_nom or ''}".upper()
    if "COUPE DE FRANCE" in text or bool(re.search(r"\bCDF\b", text)) or "COUPE_DE_FRANCE" in text:
        return True
    if "CFA" in text and ("ADPVA" in text or "ASSIS" in text or "PARA" in text):
        return True
    return False


def _format_youth_label(cat: str | None, comp_name: str | None, level_label: str) -> tuple[str, bool]:
    is_cdf = _is_coupe_de_france(comp_name)
    m = re.search(r"\b(?:M|U)\s*([0-9]{1,2})(?:[MFG]|\b)", f"{cat or ''} {comp_name or ''}".upper(), re.IGNORECASE)
    cat_str = f"M{m.group(1)}" if m else (cat or "")
    if is_cdf:
        return f"CdF {cat_str}".strip(), True
    return f"{level_label} {cat_str}".strip(), False


def _get_level_score(label: str) -> float:
    upper = normalize_text_upper(label)
    if upper in CHAMPIONSHIP_LEVEL_SCORES:
        return CHAMPIONSHIP_LEVEL_SCORES[upper]
    for k, v in CHAMPIONSHIP_LEVEL_SCORES.items():
        if k in upper:
            return v
    return 3.0


def _get_cdf_age_category_score(cat: str) -> tuple[float, str]:
    """Retourne le score numérique et le nom canonique de la catégorie d'âge CdF."""
    upper = normalize_text_upper(cat)
    if "ASSIS" in upper or "ADPVA" in upper:
        return (8.0, "Volley Assis")
    for cdf_k, cdf_v in CDF_AGE_CATEGORY_SCORES.items():
        if cdf_k in upper:
            clean_name = "Volley Assis" if cdf_k == "VOLLEY ASSIS" else cdf_k.capitalize()
            return (cdf_v, clean_name)
    m = re.search(r"\b(?:M|U)\s*([0-9]{1,2})(?:[MFG]|\b)", upper, re.IGNORECASE)
    if m:
        k = f"M{m.group(1)}"
        if k in CDF_AGE_CATEGORY_SCORES:
            return (CDF_AGE_CATEGORY_SCORES[k], k)
    return (7.0, "Senior")


def _apply_anti_superposition_jitter(datasets: list[dict[str, Any]], seasons: list[str]) -> None:
    """Applique un micro-décalage vertical (jitter) déterministe pour séparer les équipes

    qui partagent exactement le même échelon lors d'une même saison.
    Les labels réels (Prénat, N2, etc.) restent parfaitement intacts pour les tooltips.
    """
    for s_idx in range(len(seasons)):
        # Regrouper les datasets qui ont un point dans cette saison par score arrondi
        by_score: dict[float, list[int]] = {}
        for ds_idx, ds in enumerate(datasets):
            raw_val = ds["raw_data"][s_idx]
            if raw_val is not None:
                # Regroupement par niveau de base (score)
                base = round(raw_val, 1)
                by_score.setdefault(base, []).append(ds_idx)

        for base, ds_indices in by_score.items():
            k = len(ds_indices)
            if k <= 1:
                # Pas de collision
                for idx in ds_indices:
                    datasets[idx]["data"][s_idx] = datasets[idx]["raw_data"][s_idx]
                continue

            # Ordonner les datasets en collision : Hommes d'abord, puis Femmes, puis Loisirs
            def _sort_key(idx: int):
                ds = datasets[idx]
                gender_weight = {"M": 0, "F": 1, "Mixte": 2}.get(ds.get("gender"), 3)
                return (gender_weight, ds["label"])

            sorted_indices = sorted(ds_indices, key=_sort_key)

            # Calcul des offsets symétriques élargis pour un écartement optimal
            max_spread = min(0.60, 0.18 * (k - 1))
            step = max_spread / (k - 1) if k > 1 else 0.0

            for i, ds_idx in enumerate(sorted_indices):
                offset = - (max_spread / 2.0) + (i * step)
                datasets[ds_idx]["data"][s_idx] = round(base + offset, 3)


def build_club_evolution_data(equipes: list[Any]) -> dict[str, Any]:
    """Analyse toutes les équipes d'un club et construit :

    1. Le graphique principal des championnats (Hommes, Femmes, Jeunes réunis avec axe adapté et sans superposition)
    2. Le graphique spécial Coupe de France (avec les catégories d'âge sur l'axe, si présent)
    3. Le récapitulatif interactif des changements de niveau (promotions/relégations)
    """
    if not equipes:
        return {
            "has_data": False,
            "charts": {},
            "transitions": [],
            "periods": [],
            "reference_seasons": [],
            "club_summary": {},
        }

    # 1. Extraction et séparation des équipes : Championnats vs Coupe de France
    seasons_set: set[str] = set()
    champ_teams: list[dict[str, Any]] = []
    cdf_teams: list[dict[str, Any]] = []

    for eq in equipes:
        saison_code = eq.saison.code if eq.saison and eq.saison.code else ""
        if not saison_code:
            continue
        seasons_set.add(saison_code)

        comp_name = eq.competition.nom if eq.competition else ""
        comp_code = eq.competition.code_competition if eq.competition else ""
        entite_code = eq.competition.entite.code if (eq.competition and eq.competition.entite) else ""
        entite_nom = eq.competition.entite.nom if (eq.competition and eq.competition.entite) else ""
        raw_genre = eq.genre or (eq.competition.genre if eq.competition else None)
        raw_cat = eq.categorie or (eq.competition.categorie if eq.competition else None)
        raw_niv = eq.niveau or (eq.competition.niveau if eq.competition else None)
        raw_div = eq.division or (eq.competition.division if eq.competition else None)

        norm_genre = normalize_genre(raw_genre) or "MASCULIN"
        norm_cat = normalize_categorie(raw_cat) or "SENIOR"
        is_youth = is_youth_category(norm_cat) or is_youth_category(raw_cat) or any(
            k in normalize_text_upper(comp_name) for k in ("M11", "M13", "M15", "M18", "M21", "JEUNE")
        )

        raw_div_cat = f"{raw_div or ''} {comp_code} {entite_code} {entite_nom}".strip() or None
        badge = resolve_niveau_badge(raw_niv, comp_name or eq.nom, raw_cat, raw_div, raw_division_cat=raw_div_cat)
        base_label = badge["label"] if badge else "Non classé"
        badge_css = badge["css_class"] if badge else "badge"

        team_num = _extract_team_number(eq.nom)
        is_loisir = _is_loisir_or_mixte(raw_genre, raw_cat, comp_name, raw_niv)

        # Détection Coupe de France
        is_cdf = _is_coupe_de_france(
            comp_name=comp_name,
            raw_niv=raw_niv,
            comp_code=comp_code,
            entite_code=entite_code,
            entite_nom=entite_nom,
        ) or (badge and badge.get("label", "").startswith("CdF"))

        if is_cdf:
            # Équipe Coupe de France
            is_assis = (
                "ASSIS" in f"{comp_name} {entite_nom}".upper()
                or entite_code == "ADPVA"
                or ("CFA" in f"{comp_name} {comp_code}".upper() and (entite_code == "ADPVA" or "ASSIS" in f"{comp_name} {entite_nom}".upper()))
            )
            if is_assis:
                cat_score, clean_cat = (8.0, "Volley Assis")
            else:
                m = re.search(r"\b(?:M|U)\s*([0-9]{1,2})(?:[MFG]|\b)", comp_name or "", re.IGNORECASE)
                age_cat = f"M{m.group(1)}" if m else norm_cat
                if age_cat not in CDF_AGE_CATEGORY_SCORES:
                    age_cat = "Senior" if not is_youth else "Jeunes"
                cat_score, clean_cat = _get_cdf_age_category_score(age_cat)

            gender_tag = "F" if norm_genre == "FEMININ" else "M"
            series_name = f"{clean_cat} {'Filles ♀' if gender_tag == 'F' else 'Garçons ♂'}"
            label = f"CdF {clean_cat} ({'Filles' if gender_tag == 'F' else 'Garçons'})"
            cdf_teams.append({
                "id": eq.id,
                "nom": eq.nom,
                "saison": saison_code,
                "gender": gender_tag,
                "age_category": clean_cat,
                "cat_score": cat_score,
                "series_key": f"cdf_{clean_cat}_{gender_tag}",
                "series_name": series_name,
                "display_label": f"CdF {clean_cat}",
                "badge_css": badge_css,
                "competition": comp_name,
            })
        else:
            # Équipe Championnat (Seniors + Jeunes championnats + Loisirs)
            score = _get_level_score(base_label)
            if is_loisir:
                gender_tag = "Mixte"
                series_key = f"loisir_{team_num}"
                series_name = f"Loisir {team_num}" if team_num > 1 else "Équipe Loisir"
            elif is_youth:
                gender_tag = "F" if norm_genre == "FEMININ" else "M"
                m = re.search(r"\b(?:M|U)\s*([0-9]{1,2})(?:[MFG]|\b)", comp_name or "", re.IGNORECASE)
                age_cat = f"M{m.group(1)}" if m else norm_cat
                series_key = f"youth_{age_cat}_{gender_tag}_{team_num}"
                team_suf = f" {team_num}" if team_num > 1 else ""
                series_name = f"{age_cat}{team_suf} ({'Filles ♀' if gender_tag == 'F' else 'Garçons ♂'})"
            else:
                gender_tag = "F" if norm_genre == "FEMININ" else "M"
                series_key = f"senior_{gender_tag}_{team_num}"
                role_label = "Fanion" if team_num == 1 else ("Réserve" if team_num == 2 else f"Équipe {team_num}")
                gender_str = "Femmes ♀" if gender_tag == "F" else "Hommes ♂"
                series_name = f"Équipe {team_num} ({role_label}) {gender_str}"

            champ_teams.append({
                "id": eq.id,
                "nom": eq.nom,
                "saison": saison_code,
                "gender": gender_tag,
                "is_youth": is_youth,
                "is_loisir": is_loisir,
                "series_key": series_key,
                "series_name": series_name,
                "team_num": team_num,
                "base_label": base_label,
                "display_label": base_label,
                "score": score,
                "badge_css": badge_css,
                "competition": comp_name,
                "group": "loisir_mixte" if is_loisir else ("seniors_feminin" if (gender_tag == "F" and not is_youth) else ("seniors_masculin" if (gender_tag == "M" and not is_youth) else ("jeunes_feminin" if gender_tag == "F" else "jeunes_masculin"))),
            })

    all_seasons = sorted(seasons_set, key=season_sort_key)
    if not all_seasons:
        return {
            "has_data": False,
            "charts": {},
            "transitions": [],
            "periods": [],
            "reference_seasons": [],
            "club_summary": {},
        }

    charts: dict[str, Any] = {}

    # ═════════════════════════════════════════════════════════════════
    # 2. Construction du Graphique Principal (Championnats Réunis H/F/Jeunes)
    # ═════════════════════════════════════════════════════════════════
    if champ_teams:
        # Résolution de l'échelle contextuelle spécifique au club et à son territoire
        ladder = build_contextual_level_ladder(champ_teams)
        for t in champ_teams:
            if t.get("is_loisir"):
                t["score"] = ladder.label_to_score.get("LOISIR", 0.0)
            else:
                lbl = t["base_label"]
                score = ladder.label_to_score.get(lbl)
                if score is None:
                    score = ladder.label_to_score.get(lbl.upper())
                if score is None:
                    score = ladder.label_to_score.get(normalize_text_upper(lbl))
                if score is None:
                    cl = classify_level(t.get("competition", "") or lbl)
                    score = ladder.label_to_score.get(cl.label, 0.0)
                t["score"] = score if score is not None else 0.0

        main_datasets: list[dict[str, Any]] = []

        # Séries ordonnées : Seniors Hommes (1,2,3), Seniors Femmes (1,2,3), Jeunes, Loisirs
        all_series_keys = sorted(
            {t["series_key"] for t in champ_teams},
            key=lambda k: (
                0 if k.startswith("senior_M") else (
                    1 if k.startswith("senior_F") else (
                        2 if k.startswith("youth_") else 3
                    )
                ),
                k,
            ),
        )

        for sk in all_series_keys:
            series_teams = [t for t in champ_teams if t["series_key"] == sk]
            if not series_teams:
                continue

            ref_t = series_teams[0]
            gender = ref_t["gender"]
            team_num = ref_t.get("team_num", 1)
            is_youth = ref_t.get("is_youth", False)

            # Une seule couleur pour les hommes, une seule couleur pour les femmes, ambre pour loisir
            if gender == "M":
                color = COLOR_HOMMES
            elif gender == "F":
                color = COLOR_FEMMES
            else:
                color = COLOR_LOISIR

            # Toutes les équipes visuellement identiques : ligne continue, sommets ronds élargis
            border_dash = []
            point_style = "circle"
            border_width = 3.0
            point_radius = 8.0

            # Pour chaque saison, retenir le meilleur niveau officiel
            by_season: dict[str, dict[str, Any]] = {}
            for t in series_teams:
                s = t["saison"]
                cur = by_season.get(s)
                if cur is None or t["score"] > cur["score"]:
                    by_season[s] = t

            raw_data: list[float | None] = []
            labels: list[str | None] = []
            comps: list[str | None] = []
            team_ids: list[int | None] = []

            for s in all_seasons:
                item = by_season.get(s)
                if item:
                    raw_data.append(item["score"])
                    labels.append(item["display_label"])
                    comps.append(item["competition"])
                    team_ids.append(item["id"])
                else:
                    raw_data.append(None)
                    labels.append(None)
                    comps.append(None)
                    team_ids.append(None)

            main_datasets.append({
                "key": sk,
                "label": ref_t["series_name"],
                "gender": gender,
                "team_num": team_num,
                "is_youth": is_youth,
                "color": color,
                "border_dash": border_dash,
                "point_style": point_style,
                "border_width": border_width,
                "point_radius": point_radius,
                "raw_data": raw_data,
                "data": list(raw_data),  # Sera ajusté par jitter
                "level_labels": labels,
                "competitions": comps,
                "team_ids": team_ids,
            })

        # Application de l'anti-superposition (Jitter offset)
        _apply_anti_superposition_jitter(main_datasets, all_seasons)

        # Axe Y dynamique sans niveaux fantômes via l'échelle contextuelle
        adapted_y_ticks = ladder.y_ticks
        separators = ladder.separators
        lanes = ladder.lanes
        y_min = ladder.y_min
        y_max = ladder.y_max

        # Analyse du graphique principal
        peak_t = max(champ_teams, key=lambda t: t["score"])
        main_highlights = [
            f"Sommet sportif : {peak_t['display_label']} ({peak_t['nom']} en {peak_t['saison']}).",
            f"{len([t for t in champ_teams if t['saison'] == all_seasons[-1]])} équipe(s) de championnat engagée(s) en {all_seasons[-1]}.",
            "Trajectoires comparées Hommes & Femmes avec adaptation automatique de l'échelle.",
        ]

        charts["main"] = {
            "key": "main",
            "title": "Évolution des Niveaux en Championnat",
            "subtitle": "Trajectoires comparées Hommes, Femmes & Jeunes",
            "icon": "trophy",
            "color": "#3b82f6",
            "seasons": all_seasons,
            "datasets": main_datasets,
            "y_ticks": adapted_y_ticks,
            "y_min": y_min,
            "y_max": y_max,
            "separators": separators,
            "lanes": lanes,
            "analysis": {
                "peak_label": peak_t["display_label"],
                "peak_season": peak_t["saison"],
                "highlights": main_highlights,
            },
        }

    # ═════════════════════════════════════════════════════════════════
    # 3. Construction du Graphique Spécial Coupe de France (par Catégorie d'Âge)
    # ═════════════════════════════════════════════════════════════════
    if cdf_teams:
        cdf_datasets: list[dict[str, Any]] = []

        # Séries uniques ordonnées par catégorie d'âge (M11, M13, M15, M18, M21...)
        cdf_series_keys = sorted(
            {t["series_key"] for t in cdf_teams},
            key=lambda k: (
                0 if "_M" in k else 1,
                k,
            ),
        )

        for sk in cdf_series_keys:
            s_teams = [t for t in cdf_teams if t["series_key"] == sk]
            if not s_teams:
                continue

            ref_t = s_teams[0]
            gender = ref_t["gender"]
            clean_cat = ref_t.get("age_category", "Senior")

            # 1 seule couleur pour Hommes, 1 seule pour Femmes, ligne continue, ronds élargis
            if gender == "M":
                color = COLOR_HOMMES
            else:
                color = COLOR_FEMMES

            border_dash = []
            border_width = 3.0
            point_style = "circle"
            point_radius = 8.0

            by_season: dict[str, dict[str, Any]] = {}
            for t in s_teams:
                by_season[t["saison"]] = t

            raw_data: list[float | None] = []
            labels: list[str | None] = []
            comps: list[str | None] = []
            team_ids: list[int | None] = []

            for s in all_seasons:
                item = by_season.get(s)
                if item:
                    raw_data.append(item["cat_score"])
                    labels.append(item["display_label"])
                    comps.append(item["competition"])
                    team_ids.append(item["id"])
                else:
                    raw_data.append(None)
                    labels.append(None)
                    comps.append(None)
                    team_ids.append(None)

            cdf_datasets.append({
                "key": sk,
                "label": ref_t["series_name"],
                "gender": gender,
                "color": color,
                "border_dash": border_dash,
                "point_style": point_style,
                "border_width": border_width,
                "point_radius": point_radius,
                "raw_data": raw_data,
                "data": list(raw_data),
                "level_labels": labels,
                "competitions": comps,
                "team_ids": team_ids,
            })

        # Anti-superposition pour la Coupe de France (décalage Hommes / Femmes)
        _apply_anti_superposition_jitter(cdf_datasets, all_seasons)

        # Axe adapté aux catégories d'âge concernées
        cdf_scores = [t["cat_score"] for t in cdf_teams]
        min_cat = min(cdf_scores) if cdf_scores else 1.0
        max_cat = max(cdf_scores) if cdf_scores else 7.0

        cdf_y_min = max(0.5, min_cat - 0.6)
        cdf_y_max = max_cat + 0.6

        adapted_cdf_ticks = [
            (val, lbl) for val, lbl in CDF_AGE_TICKS_ALL
            if (min_cat - 0.5) <= val <= (max_cat + 0.5)
        ]

        # Calcul des séparateurs horizontaux et couloirs pour la Coupe de France
        sorted_cdf_vals = sorted(t[0] for t in adapted_cdf_ticks)
        cdf_separators: list[float] = []
        for i in range(len(sorted_cdf_vals) - 1):
            mid = round((sorted_cdf_vals[i] + sorted_cdf_vals[i+1]) / 2.0, 2)
            cdf_separators.append(mid)

        cdf_lanes: list[dict[str, Any]] = []
        for i, v in enumerate(sorted_cdf_vals):
            bottom = (sorted_cdf_vals[i-1] + v) / 2.0 if i > 0 else v - 0.5
            top = (v + sorted_cdf_vals[i+1]) / 2.0 if i < len(sorted_cdf_vals) - 1 else v + 0.5
            lbl = next((l for val, l in adapted_cdf_ticks if val == v), "")
            cdf_lanes.append({"val": v, "label": lbl, "bottom": round(bottom, 2), "top": round(top, 2)})

        cats_list = sorted({t["age_category"] for t in cdf_teams})
        cdf_highlights = [
            f"Catégories d'âge engagées : {', '.join(cats_list)}.",
            f"{len(cdf_teams)} participation(s) en Coupe de France enregistrée(s).",
            f"{len([t for t in cdf_teams if t['saison'] == all_seasons[-1]])} équipe(s) engagée(s) en {all_seasons[-1]}.",
        ]

        charts["cdf"] = {
            "key": "cdf",
            "title": "Spécial Coupe de France (par Catégorie d'Âge)",
            "subtitle": "Engagements nationaux par tranche d'âge au fil des saisons",
            "icon": "award",
            "color": "#ec4899",
            "seasons": all_seasons,
            "datasets": cdf_datasets,
            "y_ticks": adapted_cdf_ticks,
            "y_min": cdf_y_min,
            "y_max": cdf_y_max,
            "separators": cdf_separators,
            "lanes": cdf_lanes,
            "analysis": {
                "peak_label": f"CdF ({', '.join(cats_list)})",
                "peak_season": all_seasons[-1],
                "highlights": cdf_highlights,
            },
        }

    # ═════════════════════════════════════════════════════════════════
    # 4. Transitions et mouvements de niveau
    # ═════════════════════════════════════════════════════════════════
    transitions_data = _build_level_transitions(champ_teams, all_seasons)
    transitions = transitions_data["all"]
    periods = transitions_data["periods"]

    # ═════════════════════════════════════════════════════════════════
    # 5. Synthèse globale du club
    # ═════════════════════════════════════════════════════════════════
    club_summary = _build_global_club_summary(champ_teams + cdf_teams, all_seasons, charts, transitions)

    return {
        "has_data": len(charts) > 0,
        "charts": charts,
        "transitions": transitions,
        "periods": periods,
        "reference_seasons": all_seasons,
        "club_summary": club_summary,
    }


def _build_level_transitions(
    teams: list[dict[str, Any]],
    all_seasons: list[str],
) -> dict[str, Any]:
    """Identifie les mouvements sportifs saison par saison ET depuis chaque saison de référence."""
    if len(all_seasons) < 2:
        return {
            "all": [],
            "periods": [],
        }

    status_order = {"promotion": 0, "relegation": 1, "new": 2, "stable": 3, "stopped": 4}
    latest_season = all_seasons[-1]
    all_transitions: list[dict[str, Any]] = []

    def _compare_seasons(s_from: str, s_to: str, period_id: str, is_cumulative: bool = False):
        from_teams = {t["series_key"]: t for t in teams if t["saison"] == s_from}
        to_teams = {t["series_key"]: t for t in teams if t["saison"] == s_to}
        all_keys = set(from_teams.keys()) | set(to_teams.keys())

        period_transitions: list[dict[str, Any]] = []
        for k in all_keys:
            t_prev = from_teams.get(k)
            t_next = to_teams.get(k)

            if (t_prev and t_prev.get("is_loisir")) or (t_next and t_next.get("is_loisir")):
                continue

            ref_team = t_next or t_prev
            if not ref_team:
                continue

            team_name = ref_team["series_name"]
            gender_tag = "Femmes" if ref_team.get("gender") == "F" else "Hommes"

            if t_prev and t_next:
                score_prev = t_prev["score"]
                score_next = t_next["score"]
                diff = score_next - score_prev

                if diff >= 0.8:
                    status = "promotion"
                    status_label = "Montée / Accession"
                    status_badge = "badge-green"
                    icon = "trending-up"
                    delta_text = f"+{int(round(diff))} niveau(x)"
                elif diff <= -0.8:
                    status = "relegation"
                    status_label = "Descente / Relégation"
                    status_badge = "badge-red"
                    icon = "trending-down"
                    delta_text = f"{int(round(diff))} niveau(x)"
                else:
                    status = "stable"
                    status_label = "Maintien"
                    status_badge = "badge-blue"
                    icon = "check-circle-2"
                    delta_text = "Maintien"

                period_transitions.append({
                    "period_id": period_id,
                    "is_cumulative": is_cumulative,
                    "season_from": s_from,
                    "season_to": s_to,
                    "season_label": f"{s_from} ➔ {s_to}",
                    "team_name": team_name,
                    "group": ref_team.get("group", ""),
                    "genre_tag": gender_tag,
                    "level_from": t_prev["display_label"],
                    "level_to": t_next["display_label"],
                    "comp_from": t_prev["competition"],
                    "comp_to": t_next["competition"],
                    "status": status,
                    "status_label": status_label,
                    "status_badge": status_badge,
                    "icon": icon,
                    "delta_text": delta_text,
                    "score_from": score_prev,
                    "score_to": score_next,
                })
            elif not t_prev and t_next:
                period_transitions.append({
                    "period_id": period_id,
                    "is_cumulative": is_cumulative,
                    "season_from": s_from,
                    "season_to": s_to,
                    "season_label": f"{s_from} ➔ {s_to}",
                    "team_name": team_name,
                    "group": ref_team.get("group", ""),
                    "genre_tag": gender_tag,
                    "level_from": "Non engagée",
                    "level_to": t_next["display_label"],
                    "comp_from": "",
                    "comp_to": t_next["competition"],
                    "status": "new",
                    "status_label": "Nouvelle équipe",
                    "status_badge": "badge-gold",
                    "icon": "sparkles",
                    "delta_text": "Création",
                    "score_from": 0.0,
                    "score_to": t_next["score"],
                })
            elif t_prev and not t_next:
                period_transitions.append({
                    "period_id": period_id,
                    "is_cumulative": is_cumulative,
                    "season_from": s_from,
                    "season_to": s_to,
                    "season_label": f"{s_from} ➔ {s_to}",
                    "team_name": team_name,
                    "group": ref_team.get("group", ""),
                    "genre_tag": gender_tag,
                    "level_from": t_prev["display_label"],
                    "level_to": "Non engagée",
                    "comp_from": t_prev["competition"],
                    "comp_to": "",
                    "status": "stopped",
                    "status_label": "Arrêt / Sommeil",
                    "status_badge": "badge",
                    "icon": "pause-circle",
                    "delta_text": "Non engagée",
                    "score_from": t_prev["score"],
                    "score_to": 0.0,
                })

        period_transitions.sort(
            key=lambda tr: (
                status_order.get(tr["status"], 9),
                tr["team_name"],
            )
        )
        return period_transitions

    periods: list[dict[str, Any]] = []

    # 1. Transitions consécutives
    for i in range(len(all_seasons) - 1):
        s_prev = all_seasons[i]
        s_next = all_seasons[i + 1]
        p_id = f"step_{s_prev}_{s_next}"
        t_list = _compare_seasons(s_prev, s_next, p_id, is_cumulative=False)
        all_transitions.extend(t_list)
        periods.append({
            "id": p_id,
            "label": f"Transition {s_prev} ➔ {s_next}",
            "short_label": f"{s_prev} ➔ {s_next}",
            "season_from": s_prev,
            "season_to": s_next,
            "is_cumulative": False,
            "count": len(t_list),
            "promotions": len([x for x in t_list if x["status"] == "promotion"]),
            "relegations": len([x for x in t_list if x["status"] == "relegation"]),
        })

    # 2. Transitions cumulatives depuis les saisons antérieures
    if len(all_seasons) > 2:
        for s_start in all_seasons[:-1]:
            if s_start == all_seasons[-2]:
                continue
            p_id = f"from_{s_start}"
            t_list = _compare_seasons(s_start, latest_season, p_id, is_cumulative=True)
            all_transitions.extend(t_list)
            periods.append({
                "id": p_id,
                "label": f"Bilan cumulé : Depuis {s_start} (➔ {latest_season})",
                "short_label": f"Depuis {s_start}",
                "season_from": s_start,
                "season_to": latest_season,
                "is_cumulative": True,
                "count": len(t_list),
                "promotions": len([x for x in t_list if x["status"] == "promotion"]),
                "relegations": len([x for x in t_list if x["status"] == "relegation"]),
            })

    periods.reverse()

    return {
        "all": all_transitions,
        "periods": periods,
    }


def _build_global_club_summary(
    teams: list[dict[str, Any]],
    all_seasons: list[str],
    charts: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_season = all_seasons[-1] if all_seasons else ""
    first_season = all_seasons[0] if all_seasons else ""

    latest_teams = [t for t in teams if t["saison"] == latest_season]
    first_teams = [t for t in teams if t["saison"] == first_season]

    # Plus haut niveau historique toutes catégories confondues
    champ_teams = [t for t in teams if "score" in t]
    peak_team = max(champ_teams, key=lambda t: t["score"]) if champ_teams else None
    peak_level = peak_team["display_label"] if peak_team else "—"
    peak_genre = "Masculine" if peak_team and peak_team.get("gender") == "M" else "Féminine"

    total_promotions = len([tr for tr in transitions if tr["status"] == "promotion" and not tr.get("is_cumulative")])
    total_relegations = len([tr for tr in transitions if tr["status"] == "relegation" and not tr.get("is_cumulative")])
    total_new = len([tr for tr in transitions if tr["status"] == "new" and not tr.get("is_cumulative")])

    return {
        "total_active_latest": len(latest_teams),
        "total_active_first": len(first_teams),
        "latest_season": latest_season,
        "first_season": first_season,
        "peak_level": peak_level,
        "peak_genre": peak_genre,
        "total_promotions": total_promotions,
        "total_relegations": total_relegations,
        "total_new": total_new,
        "active_poles_count": len(charts),
    }
