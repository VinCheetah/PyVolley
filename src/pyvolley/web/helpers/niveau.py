"""
Résolution des badges de niveau pour les compétitions/équipes.

Hiérarchie (du plus spécifique au plus générique) :
  CdF > Pro A > Pro B > Pro > Elite > Elite Avenir > N1 > N2 > N3
  > Prénat > Préreg > Régional > Dép > Loisir
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
    r"\b(M13|M15|M17|M18|M20|M21|U13|U15|U17|U18|U20|U21|JEUNES?)\b"
)
_RE_REGIONAL = re.compile(r"\b(REGIONAL(?:E|AUX|ES?)?|R[1-4])\b")
_RE_DEPARTMENTAL = re.compile(r"\b(DEPARTEMENTAL(?:E|AUX|ES?)?|D[1-4])\b")


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
        if is_youth:
            return {"label": "Elite Avenir", "css_class": "badge-gold"}
        return {"label": "Elite", "css_class": "badge-gold"}

    # ── 4. Divisions nationales ────────────────────────────────────
    if re.search(r"\bNATIONALE?\s*1\b|\bN1\b", full_text):
        return {"label": "N1", "css_class": "badge-gold"}
    if re.search(r"\bNATIONALE?\s*2\b|\bN2\b", full_text):
        return {"label": "N2", "css_class": "badge-orange"}
    if re.search(r"\bNATIONALE?\s*3\b|\bN3\b", full_text):
        return {"label": "N3", "css_class": "badge-teal"}
    if division_text in {"1", "2", "3"} and re.search(
        r"\bNATIONAL(?:E|AUX|ES?)?\b", full_text
    ):
        css = {"1": "badge-gold", "2": "badge-orange", "3": "badge-teal"}[
            division_text
        ]
        return {"label": f"N{division_text}", "css_class": css}

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
        return {"label": "Régional", "css_class": "badge-blue"}

    # ── 8. Départemental ───────────────────────────────────────────
    if has_departmental:
        return {"label": "Dép", "css_class": "badge-cyan"}

    # ── 9. Loisir ──────────────────────────────────────────────────
    if re.search(
        r"\b(LOISIRS?|BRASSAGES?|COMPET\s*FUN|COMPET\s*MOUV)\b", full_text
    ):
        return {"label": "Loisir", "css_class": "badge-purple"}

    # ── 10. National générique (sans numéro de division) ───────────
    if re.search(r"\bNATIONAL(?:E|AUX|ES?)?\b", full_text):
        return {"label": "National", "css_class": "badge-green"}

    # ── Fallback : afficher le niveau brut ─────────────────────────
    if niveau_text:
        return {"label": (niveau or "").strip(), "css_class": "badge-green"}
    return None
