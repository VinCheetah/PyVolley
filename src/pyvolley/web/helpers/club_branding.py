"""Helpers pour le branding des clubs (couleurs + logo)."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional
from urllib.parse import urljoin
import re
import unicodedata

import requests
from bs4 import BeautifulSoup


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

_LOGO_POSITIVE_HINTS = (
    "logo",
    "logos",
    "blason",
    "ecusson",
    "emblem",
    "club",
)
_LOGO_NEGATIVE_HINTS = (
    "facebook",
    "instagram",
    "twitter",
    "youtube",
    "sponsor",
    "banner",
    "banniere",
    "ico",
    "icon",
    "sprite",
    "favicon",
)


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


def _score_logo_candidate(url: str, attrs_blob: str, code_ffvb: str | None) -> int:
    score = 0
    url_lower = url.lower()
    blob_lower = attrs_blob.lower()

    for hint in _LOGO_POSITIVE_HINTS:
        if hint in url_lower or hint in blob_lower:
            score += 3

    for hint in _LOGO_NEGATIVE_HINTS:
        if hint in url_lower or hint in blob_lower:
            score -= 4

    if code_ffvb and code_ffvb in url_lower:
        score += 4

    if url_lower.endswith((".svg", ".png", ".jpg", ".jpeg", ".webp")):
        score += 2

    if "club" in blob_lower:
        score += 1

    return score


@lru_cache(maxsize=512)
def detect_club_logo_url(
    url_planning: str | None,
    url_classement: str | None,
    code_ffvb: str | None,
) -> str | None:
    """Tente de trouver le logo d'un club depuis les pages FFVB connues."""
    page_urls = [u for u in [url_planning, url_classement] if u]
    if not page_urls:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }

    candidates: list[tuple[int, str]] = []
    code_norm = (code_ffvb or "").strip().lower() or None

    for page_url in page_urls:
        try:
            response = requests.get(page_url, headers=headers, timeout=(1.8, 2.4))
            if response.status_code != 200 or "text/html" not in response.headers.get("content-type", ""):
                continue
        except Exception:
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            if not src or src.startswith("data:"):
                continue

            abs_url = urljoin(page_url, src)
            attrs_blob = " ".join(
                str(v)
                for v in [
                    img.get("alt", ""),
                    img.get("title", ""),
                    " ".join(img.get("class", [])) if img.get("class") else "",
                    img.get("id", ""),
                ]
            )
            score = _score_logo_candidate(abs_url, attrs_blob, code_norm)
            if score > 0:
                candidates.append((score, abs_url))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def build_club_branding(
    couleurs: str | None,
    url_planning: str | None,
    url_classement: str | None,
    code_ffvb: str | None,
) -> dict:
    """Construit un objet branding pour la vue club."""
    palette = parse_club_colors(couleurs)
    logo_url = detect_club_logo_url(url_planning, url_classement, code_ffvb)
    return {
        **palette,
        "logo_url": logo_url,
    }
