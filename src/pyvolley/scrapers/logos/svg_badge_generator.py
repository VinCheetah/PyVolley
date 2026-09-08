"""Générateur vectoriel SVG de blasons pour les clubs de volley.

Permet de générer une identité visuelle soignée pour les clubs ne disposant pas
de logo officiel sur le web, en exploitant leurs couleurs officielles FFVB
et leur sigle ou monogramme.
"""

from __future__ import annotations

import base64
import html
import re
from typing import Optional
import urllib.parse

from pyvolley.web.helpers.club_branding import parse_club_colors


class SvgBadgeGenerator:
    """Génère un blason vectoriel SVG élégant et moderne aux couleurs du club."""

    @staticmethod
    def extract_monogram(club_name: str) -> str:
        """Extrait un sigle ou monogramme concis (2 à 4 caractères)."""
        clean = re.sub(r"[.\-/\'\",;:()]+", " ", club_name or "").strip().upper()
        tokens = [t for t in clean.split() if t]
        if not tokens:
            return "VB"

        stop_words = {"DE", "DU", "DES", "LA", "LE", "LES", "ET", "D", "L"}
        sig_tokens = [t for t in tokens if t not in stop_words]

        # Si un seul token
        if len(sig_tokens) == 1:
            return sig_tokens[0][:4]

        # Si le premier token est un sigle court reconnu (ex: ASUL, VBC, AVB, USI, ASPTT)
        first = sig_tokens[0]
        if first in {"ASUL", "VBC", "AVB", "USI", "ASPTT", "PUC", "SNVBA", "TLM", "CVB", "TVB"}:
            return first

        # Initiales des tokens significatifs
        initials = "".join(t[0] for t in sig_tokens[:4])
        return initials

    @classmethod
    def generate_svg(
        cls,
        club_name: str,
        couleurs: Optional[str] = None,
        city: Optional[str] = None,
        size: int = 120,
    ) -> str:
        """Génère le balisage XML SVG du blason de club.

        Args:
            club_name: Nom du club.
            couleurs: Chaîne des couleurs officielles FFVB (ex: 'Bleu / Blanc').
            city: Ville optionnelle.
            size: Dimension carrée du viewBox en pixels.

        Returns:
            Chaîne XML SVG valide.
        """
        palette = parse_club_colors(couleurs)
        primary = palette["primary"]
        secondary = palette["secondary"]
        text_color = palette["text_on_primary"]

        monogram = cls.extract_monogram(club_name)
        safe_name = html.escape(club_name or "Club")
        safe_city = html.escape((city or "").upper())

        # Dégradé et style moderne
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="{size}" height="{size}" role="img" aria-label="Logo {safe_name}">
  <defs>
    <linearGradient id="shieldGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{primary}" />
      <stop offset="100%" stop-color="{secondary}" />
    </linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="3" stdDeviation="3" flood-opacity="0.25" />
    </filter>
  </defs>
  <!-- Blason extérieur -->
  <path d="M 60 8 C 85 8, 106 14, 106 32 C 106 72, 82 102, 60 112 C 38 102, 14 72, 14 32 C 14 14, 35 8, 60 8 Z"
        fill="url(#shieldGrad)" filter="url(#shadow)" stroke="#FFFFFF" stroke-width="2.5" stroke-opacity="0.8" />
  <!-- Arcs décoratifs ballon de volley -->
  <path d="M 30 24 C 50 40, 70 40, 90 24" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-opacity="0.25" />
  <path d="M 22 55 C 45 65, 75 65, 98 55" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-opacity="0.25" />
  <path d="M 60 20 L 60 98" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-opacity="0.25" />
  <!-- Monogramme central -->
  <text x="60" y="66" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
        font-size="{34 if len(monogram) <= 3 else 26}" font-weight="900" letter-spacing="1" fill="{text_color}" text-anchor="middle"
        style="text-shadow: 0 1px 3px rgba(0,0,0,0.35);">
    {monogram}
  </text>
  <!-- Ville / Sous-titre -->
  <text x="60" y="86" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
        font-size="8" font-weight="700" letter-spacing="1.5" fill="{text_color}" fill-opacity="0.9" text-anchor="middle">
    {safe_city[:12]}
  </text>
</svg>"""
        return svg.strip()

    @classmethod
    def generate_data_uri(
        cls,
        club_name: str,
        couleurs: Optional[str] = None,
        city: Optional[str] = None,
        size: int = 120,
    ) -> str:
        """Génère le blason sous forme de Data URI SVG encodée."""
        svg_content = cls.generate_svg(club_name, couleurs=couleurs, city=city, size=size)
        encoded = base64.b64encode(svg_content.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"
