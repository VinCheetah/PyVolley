"""
Résolution des badges et hiérarchie exhaustive des niveaux de volley-ball FFVB.

Couvre la totalité des échelons administratifs et sportifs :
1. Coupe de France (Senior & Jeunes)
2. Professionnel (Pro A, Pro B)
3. Élite (Elite, Elite Avenir, Jeunes Elite)
4. National (N1, N2, N3, National générique)
5. Régional (Prénat, R1, R2, R3, R4, Régional générique, Jeunes Régional)
6. Départemental (Préreg, D1, D2, D3, D4, Dép générique, Jeunes Dép)
7. Loisir / Brassage / Détente

Fournit une classification multi-niveaux précise :
- Categorie principale (échelon fédéral)
- Division (numéro précis le cas échéant)
- Indicateur Jeunes
- Label affiché et classe CSS pour les badges
- Rang numérique stable de 0 à 18 pour les tris et graphiques
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from pyvolley.shared.categorisation import (
    extract_division_number,
    is_youth_category,
    normalize_categorie,
    normalize_text_upper,
)


@dataclass(frozen=True)
class LevelClassification:
    """Structure descriptive complète du niveau d'une compétition/équipe/match."""

    categorie_principale: str  # PRO, ELITE, NATIONALE, PRE_NATIONALE, REGIONALE, PRE_REGIONALE, DEPARTEMENTALE, COUPE_DE_FRANCE, LOISIR
    division: Optional[str]  # "1", "2", "3", "4", None
    is_youth: bool
    label: str  # ex: "Pro A", "Elite", "N2", "Prénat", "R1", "Préreg", "D1", "Jeunes Régional", etc.
    css_class: str  # ex: "badge-red", "badge-gold", "badge-teal", etc.
    rank: int  # Rang ordinal de 0 (Loisir) à 18 (CdF)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "css_class": self.css_class,
            "categorie_principale": self.categorie_principale,
            "division": self.division,
            "is_youth": self.is_youth,
            "rank": self.rank,
        }

    def __getitem__(self, item: str):
        return getattr(self, item)

    def get(self, item: str, default=None):
        return getattr(self, item, default)


# ── Hiérarchie des rangs ordinaux (0 = le plus bas, 18 = le plus haut) ──
LEVEL_SORT_ORDER: dict[str, int] = {
    # Loisir
    "LOISIR": 0,
    "BRASSAGE": 0,
    # Départemental
    "D4": 1,
    "DEPARTEMENTALE 4": 1,
    "DÉPARTEMENTALE 4": 1,
    "D3": 2,
    "DEPARTEMENTALE 3": 2,
    "DÉPARTEMENTALE 3": 2,
    "D2": 3,
    "DEPARTEMENTALE 2": 3,
    "DÉPARTEMENTALE 2": 3,
    "D1": 4,
    "DEPARTEMENTALE 1": 4,
    "DÉPARTEMENTALE 1": 4,
    "DEP": 4,
    "DÉP": 4,
    "DEPARTEMENTAL": 4,
    "DÉPARTEMENTAL": 4,
    "DEPARTEMENTALE": 4,
    "DÉPARTEMENTALE": 4,
    "JEUNES DEP": 4,
    "JEUNES DÉP": 4,
    "JEUNES D1": 4,
    "JEUNES D2": 3,
    # Coupes jeunes (open jeunes de tous niveaux)
    "JEUNES CDF": 5,
    "JEUNES COUPE DE FRANCE": 5,
    "COUPE DE FRANCE JEUNES": 5,
    "CDF JEUNES": 5,
    # Pré-régionale départementale
    "PRE REG": 6,
    "PREREG": 6,
    "PRÉREG": 6,
    "PRE_REGIONALE": 6,
    "PRÉ_RÉGIONALE": 6,
    "PREREGIONALE": 6,
    "PRÉRÉGIONALE": 6,
    # Régional
    "R4": 7,
    "REGIONALE 4": 7,
    "RÉGIONALE 4": 7,
    "R3": 7,
    "REGIONALE 3": 7,
    "RÉGIONALE 3": 7,
    "R2": 8,
    "REGIONALE 2": 8,
    "RÉGIONALE 2": 8,
    "R1": 9,
    "REGIONALE 1": 9,
    "RÉGIONALE 1": 9,
    "REGIONAL": 9,
    "RÉGIONAL": 9,
    "REGIONALE": 9,
    "RÉGIONALE": 9,
    "JEUNES REGIONAL": 9,
    "JEUNES RÉGIONAL": 9,
    "JEUNES R1": 9,
    "JEUNES R2": 8,
    # Pré-nationale régionale
    "PRENAT": 10,
    "PRÉNAT": 10,
    "PRE NAT": 10,
    "PRE_NATIONALE": 10,
    "PRÉ_NATIONALE": 10,
    "PRENATIONAL": 10,
    "PRÉNATIONAL": 10,
    "PRENATIONALE": 10,
    "PRÉNATIONALE": 10,
    "ACCESSION REGIONALE": 10,
    "ACCESSION RÉGIONALE": 10,
    # National
    "N3": 11,
    "NATIONALE 3": 11,
    "JEUNES N3": 11,
    "N2": 12,
    "NATIONALE 2": 12,
    "JEUNES N2": 12,
    "NATIONAL": 12,
    "NATIONALE": 12,
    "JEUNES NATIONAL": 12,
    "N1": 13,
    "NATIONALE 1": 13,
    "JEUNES N1": 13,
    # Elite
    "ELITE AVENIR": 14,
    "ÉLITE AVENIR": 14,
    "ELITE": 15,
    "ÉLITE": 15,
    "JEUNES ELITE": 15,
    # Pro
    "PRO": 16,
    "PRO B": 16,
    "LIGUE B": 16,
    "LBM": 16,
    "LBF": 16,
    "PRO A": 17,
    "LIGUE A": 17,
    "LAM": 17,
    "LAF": 17,
    # Coupe de France Senior
    "CDF": 18,
    "COUPE DE FRANCE": 18,
}

RANK_REFERENCE_LABELS: dict[int, str] = {
    0: "Loisir",
    1: "D4",
    2: "D3",
    3: "D2",
    4: "D1/Dép",
    5: "Jeunes CdF",
    6: "Préreg",
    7: "R3",
    8: "R2",
    9: "R1/Régional",
    10: "Prénat",
    11: "N3",
    12: "N2",
    13: "N1",
    14: "Elite Avenir",
    15: "Elite",
    16: "Pro B",
    17: "Pro A",
    18: "CdF",
}


_RE_YOUTH_WORDS = re.compile(
    r"\b(M9|M11|M13|M14|M15|M16|M17|M18|M19|M20|M21|U9|U11|U13|U14|U15|U16|U17|U18|U19|U20|U21|JEUNES?|CADETS?|CADETTES?|MINIMES?|BENJAMINS?|BENJAMINES?|POUSSINS?|POUSSINES?)\b",
    re.IGNORECASE,
)
_RE_REGIONAL_WORDS = re.compile(r"\b(REGIONAL(?:E|AUX|ES?)?|R[1-4])\b", re.IGNORECASE)
_RE_DEPARTMENTAL_WORDS = re.compile(r"\b(DEPARTEMENTAL(?:E|AUX|ES?)?|D[1-4]|INTERDEPARTEMENTAL(?:E|AUX|ES?)?)\b", re.IGNORECASE)


def normalize_level_text(value: str) -> str:
    """Supprime les accents, normalise les espaces et met en majuscules."""
    return normalize_text_upper(value)


def classify_level(
    competition_name: Optional[str] = None,
    niveau: Optional[str] = None,
    categorie: Optional[str] = None,
    division: Optional[str | int] = None,
    raw_division_cat: Optional[str] = None,
) -> LevelClassification:
    """Identifie avec précision le niveau et la subdivision d'une compétition ou équipe.

    Prend en compte l'ensemble des contextes départementaux, régionaux et nationaux,
    ainsi que les distinctions spécifiques Jeunes / Seniors.
    """
    parts = [p for p in [competition_name, niveau, categorie, raw_division_cat] if p]
    full_text = normalize_text_upper(" ".join(str(p) for p in parts))

    # Catégorie d'âge & détection jeune
    norm_cat = normalize_categorie(categorie) or normalize_categorie(full_text)
    is_youth = is_youth_category(norm_cat) or bool(_RE_YOUTH_WORDS.search(full_text))

    # Division explicite ou déduite
    div_num = str(division).strip() if division is not None and str(division).strip() else None
    if not div_num or div_num.upper() == "NONE":
        div_num = extract_division_number(competition_name) or extract_division_number(raw_division_cat) or extract_division_number(niveau)

    # Contexte bas niveau (régional ou départemental)
    has_regional = bool(_RE_REGIONAL_WORDS.search(full_text))
    has_departmental = bool(_RE_DEPARTMENTAL_WORDS.search(full_text))
    has_lower_context = has_regional or has_departmental

    # ── 1. Coupe de France ──────────────────────────────────────────
    if "COUPE DE FRANCE" in full_text or re.search(r"\bCDF\b", full_text):
        if is_youth:
            return LevelClassification(
                categorie_principale="COUPE_DE_FRANCE",
                division=div_num,
                is_youth=True,
                label="Jeunes CdF",
                css_class="badge-cyan",
                rank=5,
            )
        return LevelClassification(
            categorie_principale="COUPE_DE_FRANCE",
            division=div_num,
            is_youth=False,
            label="CdF",
            css_class="badge-purple",
            rank=18,
        )

    # ── 2. Professionnel (Pro A, Pro B) ────────────────────────────
    if re.search(r"\b(PRO\s*A|LIGUE\s*A\b|LAM\b|LAF\b)\b", full_text):
        return LevelClassification(
            categorie_principale="PRO",
            division=None,
            is_youth=False,
            label="Pro A",
            css_class="badge-red",
            rank=17,
        )
    if re.search(r"\b(PRO\s*B|LIGUE\s*B\b|LBM\b|LBF\b)\b", full_text):
        return LevelClassification(
            categorie_principale="PRO",
            division=None,
            is_youth=False,
            label="Pro B",
            css_class="badge-red",
            rank=16,
        )
    if re.search(r"\bPRO\b", full_text) and not has_lower_context:
        return LevelClassification(
            categorie_principale="PRO",
            division=None,
            is_youth=False,
            label="Pro",
            css_class="badge-red",
            rank=16,
        )

    # ── 3. Élite & Élite Avenir ────────────────────────────────────
    # Si le texte comporte un qualificatif régional ou départemental,
    # c'est un championnat régional jeune d'élite, PAS l'Élite nationale !
    if not has_lower_context and re.search(r"\bELITE\b", full_text):
        if re.search(r"\bELITE\s*AVENIR\b", full_text):
            return LevelClassification(
                categorie_principale="ELITE",
                division=None,
                is_youth=False,
                label="Elite Avenir",
                css_class="badge-gold",
                rank=14,
            )
        if is_youth:
            return LevelClassification(
                categorie_principale="ELITE",
                division=None,
                is_youth=True,
                label="Jeunes Elite",
                css_class="badge-gold",
                rank=15,
            )
        return LevelClassification(
            categorie_principale="ELITE",
            division=None,
            is_youth=False,
            label="Elite",
            css_class="badge-gold",
            rank=15,
        )

    # ── 4. Divisions Nationales (N1, N2, N3, National) ─────────────
    # N1
    if re.search(r"\b(NATIONALE?\s*1|N1|1\s*[MF]|NM1|NF1)\b", full_text) and not has_lower_context:
        label = "Jeunes N1" if is_youth else "N1"
        return LevelClassification(
            categorie_principale="NATIONALE",
            division="1",
            is_youth=is_youth,
            label=label,
            css_class="badge-gold",
            rank=13,
        )
    # N2
    if re.search(r"\b(NATIONALE?\s*2|N2|2\s*[MF]|NM2|NF2|2FA|2MA)\b", full_text) and not has_lower_context:
        label = "Jeunes N2" if is_youth else "N2"
        return LevelClassification(
            categorie_principale="NATIONALE",
            division="2",
            is_youth=is_youth,
            label=label,
            css_class="badge-orange",
            rank=12,
        )
    # N3
    if re.search(r"\b(NATIONALE?\s*3|N3|3\s*[MF]|NM3|NF3|3FA|3MA)\b", full_text) and not has_lower_context:
        label = "Jeunes N3" if is_youth else "N3"
        return LevelClassification(
            categorie_principale="NATIONALE",
            division="3",
            is_youth=is_youth,
            label=label,
            css_class="badge-teal",
            rank=11,
        )
    if div_num in {"1", "2", "3"} and re.search(r"\bNATIONAL(?:E|AUX|ES?)?\b", full_text) and not has_lower_context:
        ranks = {"1": 13, "2": 12, "3": 11}
        css = {"1": "badge-gold", "2": "badge-orange", "3": "badge-teal"}[div_num]
        label = f"Jeunes N{div_num}" if is_youth else f"N{div_num}"
        return LevelClassification(
            categorie_principale="NATIONALE",
            division=div_num,
            is_youth=is_youth,
            label=label,
            css_class=css,
            rank=ranks[div_num],
        )

    # ── 5. Prénationale (Plus haut niveau régional) ────────────────
    if re.search(
        r"\b(PRE\s*-?\s*NAT(?:IONAL(?:E|AUX|ES?)?)?|PRE_?NAT(?:IONAL(?:E|AUX|ES?)?)?|PRENAT(?:IONAL(?:E|AUX|ES?)?)?|PNM|PNF)\b",
        full_text,
    ) or re.search(r"\bACCESSION\s+REGIONAL(?:E|AUX|ES?)?\b", full_text):
        return LevelClassification(
            categorie_principale="PRE_NATIONALE",
            division=div_num,
            is_youth=is_youth,
            label="Prénat",
            css_class="badge-orange",
            rank=10,
        )

    # ── 6. Pré-régionale (Plus haut niveau départemental) ──────────
    if re.search(
        r"\b(PRE\s*-?\s*REG(?:IONAL(?:E|AUX|ES?)?)?|PRE_?REG(?:IONAL(?:E|AUX|ES?)?)?|PREREG(?:IONAL(?:E|AUX|ES?)?)?|PRM|PRF)\b",
        full_text,
    ) or re.search(r"\bACCESSION\s+PREREGIONAL(?:E|AUX|ES?)?\b", full_text):
        return LevelClassification(
            categorie_principale="PRE_REGIONALE",
            division=div_num,
            is_youth=is_youth,
            label="Préreg",
            css_class="badge-teal",
            rank=6,
        )

    # ── 7. Régionale avec division (R1, R2, R3, R4) ────────────────
    # R1
    if re.search(r"\b(REGIONALE?\s*1|R1|R1M|R1F)\b", full_text) or (has_regional and div_num == "1"):
        label = "Jeunes R1" if is_youth else "R1"
        return LevelClassification(
            categorie_principale="REGIONALE",
            division="1",
            is_youth=is_youth,
            label=label,
            css_class="badge-blue",
            rank=9,
        )
    # R2
    if re.search(r"\b(REGIONALE?\s*2|R2|R2M|R2F)\b", full_text) or (has_regional and div_num == "2"):
        label = "Jeunes R2" if is_youth else "R2"
        return LevelClassification(
            categorie_principale="REGIONALE",
            division="2",
            is_youth=is_youth,
            label=label,
            css_class="badge-blue",
            rank=8,
        )
    # R3 / R4
    if re.search(r"\b(REGIONALE?\s*3|R3|R3M|R3F)\b", full_text) or (has_regional and div_num == "3"):
        return LevelClassification(
            categorie_principale="REGIONALE",
            division="3",
            is_youth=is_youth,
            label="R3",
            css_class="badge-blue",
            rank=7,
        )
    if re.search(r"\b(REGIONALE?\s*4|R4|R4M|R4F)\b", full_text) or (has_regional and div_num == "4"):
        return LevelClassification(
            categorie_principale="REGIONALE",
            division="4",
            is_youth=is_youth,
            label="R4",
            css_class="badge-blue",
            rank=7,
        )

    # Régional générique
    if has_regional:
        label = "Jeunes Régional" if is_youth else "Régional"
        return LevelClassification(
            categorie_principale="REGIONALE",
            division=div_num,
            is_youth=is_youth,
            label=label,
            css_class="badge-blue",
            rank=9,
        )

    # ── 8. Départementale avec division (D1, D2, D3, D4) ───────────
    # D1
    if re.search(r"\b(DEPARTEMENTALE?\s*1|D1|D1M|D1F)\b", full_text) or (has_departmental and div_num == "1"):
        label = "Jeunes D1" if is_youth else "D1"
        return LevelClassification(
            categorie_principale="DEPARTEMENTALE",
            division="1",
            is_youth=is_youth,
            label=label,
            css_class="badge-cyan",
            rank=4,
        )
    # D2
    if re.search(r"\b(DEPARTEMENTALE?\s*2|D2|D2M|D2F)\b", full_text) or (has_departmental and div_num == "2"):
        label = "Jeunes D2" if is_youth else "D2"
        return LevelClassification(
            categorie_principale="DEPARTEMENTALE",
            division="2",
            is_youth=is_youth,
            label=label,
            css_class="badge-cyan",
            rank=3,
        )
    # D3
    if re.search(r"\b(DEPARTEMENTALE?\s*3|D3|D3M|D3F)\b", full_text) or (has_departmental and div_num == "3"):
        return LevelClassification(
            categorie_principale="DEPARTEMENTALE",
            division="3",
            is_youth=is_youth,
            label="D3",
            css_class="badge-cyan",
            rank=2,
        )
    # D4
    if re.search(r"\b(DEPARTEMENTALE?\s*4|D4|D4M|D4F)\b", full_text) or (has_departmental and div_num == "4"):
        return LevelClassification(
            categorie_principale="DEPARTEMENTALE",
            division="4",
            is_youth=is_youth,
            label="D4",
            css_class="badge-cyan",
            rank=1,
        )

    # Départemental générique
    if has_departmental:
        label = "Jeunes Dép" if is_youth else "Dép"
        return LevelClassification(
            categorie_principale="DEPARTEMENTALE",
            division=div_num,
            is_youth=is_youth,
            label=label,
            css_class="badge-cyan",
            rank=4,
        )

    # ── 9. Loisir & Brassage ───────────────────────────────────────
    if re.search(r"\b(LOISIRS?|BRASSAGES?|COMPET\s*FUN|COMPET\s*MOUV|DETENTE)\b", full_text):
        return LevelClassification(
            categorie_principale="LOISIR",
            division=div_num,
            is_youth=is_youth,
            label="Loisir",
            css_class="badge-purple",
            rank=0,
        )

    # ── 10. National générique ─────────────────────────────────────
    if re.search(r"\bNATIONAL(?:E|AUX|ES?)?\b", full_text):
        label = "Jeunes National" if is_youth else "National"
        return LevelClassification(
            categorie_principale="NATIONALE",
            division=div_num,
            is_youth=is_youth,
            label=label,
            css_class="badge-green",
            rank=12,
        )

    # ── Fallback ──────────────────────────────────────────────────
    clean_niv = (niveau or "").strip()
    if clean_niv:
        clean_upper = normalize_text_upper(clean_niv)
        rank_val = LEVEL_SORT_ORDER.get(clean_upper, 4)
        return LevelClassification(
            categorie_principale=clean_upper,
            division=div_num,
            is_youth=is_youth,
            label=clean_niv,
            css_class="badge-green",
            rank=rank_val,
        )

    # Par défaut départemental
    return LevelClassification(
        categorie_principale="DEPARTEMENTALE",
        division=div_num,
        is_youth=is_youth,
        label="Jeunes Dép" if is_youth else "Dép",
        css_class="badge-cyan",
        rank=4,
    )


def resolve_niveau_badge(
    niveau: str | None,
    competition_name: str | None = None,
    categorie: str | None = None,
    division: str | int | None = None,
    raw_division_cat: str | None = None,
) -> dict | None:
    """Résout le badge de niveau à afficher pour une compétition/équipe/match."""
    parts = [p for p in [niveau, competition_name, categorie, raw_division_cat] if p]
    if not parts:
        return None

    classification = classify_level(
        competition_name=competition_name,
        niveau=niveau,
        categorie=categorie,
        division=division,
        raw_division_cat=raw_division_cat,
    )
    return {"label": classification.label, "css_class": classification.css_class}


def niveau_sort_rank(label: str | None) -> int:
    """Retourne un rang de tri stable pour les niveaux (plus haut = plus fort)."""
    if not label:
        return -1
    norm = normalize_level_text(label)
    if norm in LEVEL_SORT_ORDER:
        return LEVEL_SORT_ORDER[norm]
    # Si le label commence par Jeunes, essayer sans
    without_jeunes = re.sub(r"^JEUNES\s+", "", norm).strip()
    if without_jeunes in LEVEL_SORT_ORDER:
        return LEVEL_SORT_ORDER[without_jeunes]
    return -1


def niveau_sort_key(label: str | None) -> tuple[int, str]:
    """Clé de tri des labels de niveau."""
    if not label:
        return (-1, "")
    return (niveau_sort_rank(label), normalize_level_text(label))


def niveau_reference_labels() -> list[dict[str, int | str]]:
    """Liste ordonnée des niveaux de référence utilisés pour l'axe du graphique."""
    return [
        {"rank": rank, "label": label}
        for rank, label in sorted(RANK_REFERENCE_LABELS.items(), key=lambda item: item[0])
    ]


# ── Échelons administratifs / territoriaux ───────────────────────────

ECHELON_METADATA: dict[str, dict[str, Any]] = {
    "national": {
        "key": "national",
        "label": "National",
        "short_label": "National",
        "icon": "trophy",
        "badge_css": "badge-gold",
        "description": "Championnats de France et divisions fédérales (Pro A, Pro B, Élite, N2, N3)",
        "order": 1,
    },
    "regional": {
        "key": "regional",
        "label": "Régional",
        "short_label": "Régional",
        "icon": "map",
        "badge_css": "badge-blue",
        "description": "Ligues régionales (Pré-Nationale, Régionale 1, Régionale 2, Jeunes Régionaux)",
        "order": 2,
    },
    "departemental": {
        "key": "departemental",
        "label": "Départemental",
        "short_label": "Départemental",
        "icon": "map-pin",
        "badge_css": "badge-teal",
        "description": "Comités départementaux (Pré-Régionale, D1, D2, D3, D4, Tournois Départementaux)",
        "order": 3,
    },
    "coupe_de_france": {
        "key": "coupe_de_france",
        "label": "Coupe de France",
        "short_label": "Coupes",
        "icon": "award",
        "badge_css": "badge-purple",
        "description": "Coupes de France Seniors, Fédérales et Jeunes (M13 à M21)",
        "order": 4,
    },
    "loisir": {
        "key": "loisir",
        "label": "Loisir & Autres",
        "short_label": "Loisir",
        "icon": "smile",
        "badge_css": "badge-yellow",
        "description": "Championnats loisirs, corpo, détente, brassage et compétitions non officielles",
        "order": 5,
    },
}


def resolve_competition_echelon(
    nom: Optional[str] = None,
    niveau: Optional[str] = None,
    categorie: Optional[str] = None,
    division: Optional[str | int] = None,
    entite_type: Optional[str] = None,
    code_competition: Optional[str] = None,
) -> str:
    """Détermine l'échelon territorial ('national', 'regional', 'departemental', 'coupe_de_france', 'loisir')."""
    text = normalize_text_upper(f"{nom or ''} {code_competition or ''}")

    # 1. Coupe de France
    if "COUPE DE FRANCE" in text or re.search(r"\bCDF\b", text):
        return "coupe_de_france"

    # 2. Loisir & détente
    if any(k in text for k in ("LOISIR", "BRASSAGE", "COMPET'FUN", "COMPET FUN", "COMPET'MOUV")):
        return "loisir"

    # 3. Entité organisatrice explicite
    if entite_type:
        ent_norm = entite_type.strip().lower()
        if ent_norm in ("nationale", "national"):
            return "national"
        if ent_norm in ("ligue", "regionale", "regional"):
            return "regional"
        if ent_norm in ("comite", "departementale", "departemental"):
            return "departemental"

    # 4. Classification du niveau
    classification = classify_level(
        competition_name=nom,
        niveau=niveau,
        categorie=categorie,
        division=division,
    )
    cat_princ = classification.categorie_principale
    if cat_princ in ("PRO", "ELITE", "NATIONALE"):
        return "national"
    if cat_princ in ("PRE_NATIONALE", "REGIONALE"):
        return "regional"
    if cat_princ in ("PRE_REGIONALE", "DEPARTEMENTALE"):
        return "departemental"
    if cat_princ == "COUPE_DE_FRANCE":
        return "coupe_de_france"
    if cat_princ == "LOISIR":
        return "loisir"

    # 5. Regex directes sur le nom/code
    if re.search(r"\b(PRO\s*[AB]?|ELITE|NATIONAL(?:E|ES|S)?|N[1-3])\b", text):
        return "national"
    if re.search(r"\b(REGIONAL(?:E|ES|S)?|PRE-?NAT(?:IONALE?)?|R[1-4]|TID)\b", text):
        return "regional"
    if re.search(r"\b(DEPARTEMENTAL(?:E|ES|S)?|PRE-?REG(?:IONALE?)?|D[1-4])\b", text):
        return "departemental"

    return "regional"

