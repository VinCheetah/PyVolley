"""Helpers pour le branding des clubs (couleurs + logo)."""

from __future__ import annotations

from typing import Optional
import re
import unicodedata


COLOR_MAP: dict[str, str] = {
    "NOIR": "#111827",
    "BLANC": "#F9FAFB",
    "BLEU": "#2563EB",
    "BLEU MARINE": "#1E3A8A",
    "BLEU ROI": "#1D4ED8",
    "ROUGE": "#DC2626",
    "VERT": "#16A34A",
    "JAUNE": "#EAB308",
    "OR": "#D97706",
    "DORE": "#D97706",
    "DORÉ": "#D97706",
    "ORANGE": "#EA580C",
    "VIOLET": "#7C3AED",
    "MAUVE": "#A855F7",
    "ROSE": "#EC4899",
    "GRIS": "#6B7280",
    "GRIS CLAIR": "#9CA3AF",
    "MARRON": "#92400E",
    "BRUN": "#78350F",
    "TURQUOISE": "#0D9488",
    "CYAN": "#0891B2",
    "BORDEAUX": "#9F1239",
}

_SEPARATORS_RE = re.compile(r"\s*(?:,|/|;|\+|\bet\b|\bET\b|\bavec\b|-|\|)\s*")


def _normalize(value: str) -> str:
    cleaned = unicodedata.normalize("NFD", value or "")
    without_accents = "".join(ch for ch in cleaned if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", without_accents).strip().upper()


def _text_color_for_bg(bg_hex: str) -> str:
    hex_clean = bg_hex.lstrip("#")
    if len(hex_clean) != 6:
        return "#FFFFFF"
    red = int(hex_clean[0:2], 16)
    green = int(hex_clean[2:4], 16)
    blue = int(hex_clean[4:6], 16)
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#0B0E17" if luminance > 0.62 else "#FFFFFF"


def parse_club_colors(raw_colors: Optional[str]) -> dict:
    """Parse une chaîne de couleurs FFVB et retourne une palette exploitable.

    Retour:
      {
        "raw": str,
        "tokens": list[str],
        "hexes": list[str],
        "primary": str,
        "secondary": str,
        "text_on_primary": str,
      }
    """
    raw = (raw_colors or "").strip()
    if not raw:
        return {
            "raw": "",
            "tokens": [],
            "hexes": [],
            "primary": "#F59E0B",
            "secondary": "#2563EB",
            "text_on_primary": "#0B0E17",
        }

    parts = [p.strip() for p in _SEPARATORS_RE.split(raw) if p.strip()]
    normalized_parts = [_normalize(p) for p in parts]

    found_hexes: list[str] = []
    for token in normalized_parts:
        exact = COLOR_MAP.get(token)
        if exact and exact not in found_hexes:
            found_hexes.append(exact)
            continue

        for key, value in COLOR_MAP.items():
            if key in token and value not in found_hexes:
                found_hexes.append(value)

    if not found_hexes:
        found_hexes = ["#F59E0B", "#2563EB"]
    elif len(found_hexes) == 1:
        found_hexes.append("#2563EB")

    primary = found_hexes[0]
    secondary = found_hexes[1]

    return {
        "raw": raw,
        "tokens": parts,
        "hexes": found_hexes,
        "primary": primary,
        "secondary": secondary,
        "text_on_primary": _text_color_for_bg(primary),
    }


def build_club_branding(
    couleurs: str | None,
    logo_url: str | None,
) -> dict:
    """Construit un objet branding pour la vue club."""
    palette = parse_club_colors(couleurs)
    return {
        **palette,
        "logo_url": logo_url,
    }
