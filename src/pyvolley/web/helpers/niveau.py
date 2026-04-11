"""
Resolution des badges de niveau pour les competitions/equipes.

Ordre de reference (du plus bas au plus haut) :
    Loisir < Dep < Jeunes CdF < Prereg < Regional < Prenat < National
    < N3 < N2 < N1 < Elite Avenir < Elite < Pro < Pro B < Pro A < CdF
"""

import re
import unicodedata


def _normalize_level_text(value: str) -> str:
    """Supprime les accents, normalise les espaces et met en majuscules."""
    normalized = unicodedata.normalize("NFD", value)
    without_accents = "".join(
        ch for ch in normalized if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"\s+", " ", without_accents).strip().upper()


_RE_YOUTH = re.compile(
    r"\b(M11|M13|M14|M15|M16|M17|M18|M19|M20|M21|U11|U13|U14|U15|U16|U17|U18|U19|U20|U21|JEUNES?)\b"
)
_RE_REGIONAL = re.compile(r"\b(REGIONAL(?:E|AUX|ES?)?|R[1-4])\b")
_RE_DEPARTMENTAL = re.compile(r"\b(DEPARTEMENTAL(?:E|AUX|ES?)?|D[1-4])\b")


LEVEL_SORT_ORDER = {
    "LOISIR": 0,
    "DEP": 1,
    "DEPARTEMENTAL": 1,
    "JEUNES CDF": 2,
    "JEUNES COUPE DE FRANCE": 2,
    "COUPE DE FRANCE JEUNES": 2,
    "CDF JEUNES": 2,
    "PRE REG": 3,
    "PREREG": 3,
    "REGIONAL": 4,
    "PRENAT": 5,
    "PRE NAT": 5,
    "NATIONAL": 6,
    "N3": 7,
    "N2": 8,
    "N1": 9,
    "ELITE AVENIR": 10,
    "ELITE": 11,
    "PRO": 12,
    "PRO B": 13,
    "PRO A": 14,
    "CDF": 15,
    "COUPE DE FRANCE": 15,
}


RANK_REFERENCE_LABELS = {
    0: "Loisir",
    1: "Dep",
    2: "Jeunes CdF",
    3: "Prereg",
    4: "Regional",
    5: "Prenat",
    6: "National",
    7: "N3",
    8: "N2",
    9: "N1",
    10: "Elite Avenir",
    11: "Elite",
    12: "Pro",
    13: "Pro B",
    14: "Pro A",
    15: "CdF",
}


def niveau_sort_rank(label: str | None) -> int:
    """Retourne un rang de tri stable pour les niveaux (plus haut = plus fort)."""
    if not label:
        return -1
    norm = _normalize_level_text(label)
    if norm in {"JEUNES CDF", "CDF JEUNES", "JEUNES COUPE DE FRANCE", "COUPE DE FRANCE JEUNES"}:
        return LEVEL_SORT_ORDER["JEUNES CDF"]
    # Retire le préfixe jeunes pour garder l'ordre du niveau sport.
    norm = re.sub(r"^JEUNES\s+", "", norm)
    return LEVEL_SORT_ORDER.get(norm, -1)


def niveau_sort_key(label: str | None) -> tuple[int, str]:
    """Clé de tri des labels de niveau."""
    if not label:
        return (-1, "")
    return (niveau_sort_rank(label), _normalize_level_text(label))


def niveau_reference_labels() -> list[dict[str, int | str]]:
    """Liste ordonnee des niveaux de reference utilises pour l'axe du graphique."""
    return [
        {"rank": rank, "label": label}
        for rank, label in sorted(RANK_REFERENCE_LABELS.items(), key=lambda item: item[0])
    ]


def resolve_niveau_badge(
    niveau: str | None,
    competition_name: str | None = None,
    categorie: str | None = None,
    division: str | int | None = None,
) -> dict | None:
    """Résout le badge de niveau à afficher pour une compétition/équipe.

    Retourne un dict {label, css_class} ou None.

    Garde-fou jeunes : « CHAMPIONNAT REGIONAL ELITE M15 » est Régional,
    pas Elite. Seules les compétitions sans qualificatif régional/dép.
    reçoivent le badge Elite ou Elite Avenir.
    """
    parts = [p for p in [niveau, competition_name, categorie] if p]
    if not parts:
        return None

    full_text = _normalize_level_text(" ".join(parts))
    niveau_text = _normalize_level_text(niveau or "")
    division_text = str(division).strip() if division is not None else ""
    is_youth = bool(_RE_YOUTH.search(full_text))

    # Contexte « bas niveau » : présence d'un qualificatif régional ou dép.
    has_regional = bool(_RE_REGIONAL.search(full_text))
    has_departmental = bool(_RE_DEPARTMENTAL.search(full_text))
    has_lower_context = has_regional or has_departmental

    # ── 1. Coupe de France ──────────────────────────────────────────
    if "COUPE DE FRANCE" in full_text or re.search(r"\bCDF\b", full_text):
        if is_youth:
            return {"label": "Jeunes CdF", "css_class": "badge-cyan"}
        return {"label": "CdF", "css_class": "badge-purple"}

    # ── 2. Pro ──────────────────────────────────────────────────────
    if re.search(r"\b(PRO\s*A|LIGUE\s*A\b|LAM|LAF)\b", full_text):
        return {"label": "Pro A", "css_class": "badge-red"}
    if re.search(r"\b(PRO\s*B|LIGUE\s*B\b|LBM|LBF)\b", full_text):
        return {"label": "Pro B", "css_class": "badge-red"}
    if re.search(r"\bPRO\b", full_text) and not has_lower_context:
        return {"label": "Pro", "css_class": "badge-red"}

    # ── 3. Elite / Elite Avenir (seulement si PAS de contexte rég/dép) ─
    if not has_lower_context and re.search(r"\bELITE\b", full_text):
        if re.search(r"\bELITE\s*AVENIR\b", full_text):
            return {"label": "Elite Avenir", "css_class": "badge-gold"}
        # En jeunes, on n'assimile pas automatiquement "Elite" à Elite Avenir.
        # Cela évite de surclasser des compétitions régionales jeunes.
        if is_youth:
            return {"label": "Jeunes Elite", "css_class": "badge-gold"}
        return {"label": "Elite", "css_class": "badge-gold"}

    # ── 4. Divisions nationales ────────────────────────────────────
    if re.search(r"\bNATIONALE?\s*1\b|\bN1\b", full_text):
        return {"label": "Jeunes N1" if is_youth else "N1", "css_class": "badge-gold"}
    if re.search(r"\bNATIONALE?\s*2\b|\bN2\b", full_text):
        return {"label": "Jeunes N2" if is_youth else "N2", "css_class": "badge-orange"}
    if re.search(r"\bNATIONALE?\s*3\b|\bN3\b", full_text):
        return {"label": "Jeunes N3" if is_youth else "N3", "css_class": "badge-teal"}
    if division_text in {"1", "2", "3"} and re.search(
        r"\bNATIONAL(?:E|AUX|ES?)?\b", full_text
    ):
        css = {"1": "badge-gold", "2": "badge-orange", "3": "badge-teal"}[
            division_text
        ]
        label = f"N{division_text}"
        if is_youth:
            label = f"Jeunes {label}"
        return {"label": label, "css_class": css}

    # ── 5. Prénat ──────────────────────────────────────────────────
    if re.search(
        r"\b(PRE\s*-?\s*NAT(?:IONAL(?:E|AUX|ES?)?)?|PRE_?NAT(?:IONAL(?:E|AUX|ES?)?)?|PRENAT(?:IONAL(?:E|AUX|ES?)?)?)\b",
        full_text,
    ):
        return {"label": "Prénat", "css_class": "badge-orange"}
    if re.search(r"\bACCESSION\s+REGIONAL(?:E|AUX|ES?)?\b", full_text):
        return {"label": "Prénat", "css_class": "badge-orange"}

    # ── 6. Préreg ──────────────────────────────────────────────────
    if re.search(
        r"\b(PRE\s*-?\s*REG(?:IONAL(?:E|AUX|ES?)?)?|PRE_?REG(?:IONAL(?:E|AUX|ES?)?)?|PREREG(?:IONAL(?:E|AUX|ES?)?)?)\b",
        full_text,
    ):
        return {"label": "Préreg", "css_class": "badge-teal"}

    # ── 7. Régional ────────────────────────────────────────────────
    if has_regional:
        return {"label": "Jeunes Régional" if is_youth else "Régional", "css_class": "badge-blue"}

    # ── 8. Départemental ───────────────────────────────────────────
    if has_departmental:
        return {"label": "Jeunes Dép" if is_youth else "Dép", "css_class": "badge-cyan"}

    # ── 9. Loisir ──────────────────────────────────────────────────
    if re.search(
        r"\b(LOISIRS?|BRASSAGES?|COMPET\s*FUN|COMPET\s*MOUV)\b", full_text
    ):
        return {"label": "Loisir", "css_class": "badge-purple"}

    # ── 10. National générique (sans numéro de division) ───────────
    if re.search(r"\bNATIONAL(?:E|AUX|ES?)?\b", full_text):
        return {"label": "Jeunes National" if is_youth else "National", "css_class": "badge-green"}

    # ── Fallback : afficher le niveau brut ─────────────────────────
    if niveau_text:
        return {"label": (niveau or "").strip(), "css_class": "badge-green"}
    return None
