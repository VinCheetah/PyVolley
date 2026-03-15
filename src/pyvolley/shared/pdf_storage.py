"""Helpers de stockage des PDFs de feuilles de match.

Convention de stockage :
    data/pdfs/<saison>/<entite>/<poule>/<filename>.pdf

Nom de fichier simplifié :
    <code_match>.pdf

L'unicité est assurée par l'arborescence (saison/entite/poule).
"""

from __future__ import annotations

import re
from pathlib import Path

_SAFE_PART_RE = re.compile(r"[^A-Za-z0-9_-]+")
_SAISON_RE = re.compile(r"^\d{4}-\d{4}$")


def sanitize_pdf_part(value: str | None, *, fallback: str = "UNKNOWN") -> str:
    """Normalise une partie de chemin/nom de fichier pour usage filesystem."""
    token = (value or "").strip().upper()
    token = _SAFE_PART_RE.sub("-", token)
    token = token.strip("-")
    return token or fallback


def normalize_saison_code(value: str | None) -> str:
    """Normalise une saison en format dossier ``YYYY-YYYY``."""
    token = (value or "").strip()
    if not token:
        return "unknown"
    token = token.replace("/", "-")
    return token if _SAISON_RE.match(token) else sanitize_pdf_part(token, fallback="unknown")


def build_pdf_filename(
    *,
    match_code: str,
    entite_code: str | None,
    poule_code: str | None,
    journee: str | None = None,
    unique_hint: str | int | None = None,
) -> str:
    """Construit un nom de fichier PDF simplifié."""
    code = sanitize_pdf_part(match_code, fallback="MATCH")
    return f"{code}.pdf"


def build_pdf_storage_path(
    base_dir: Path,
    *,
    saison_code: str | None,
    entite_code: str | None,
    poule_code: str | None,
    match_code: str,
    journee: str | None = None,
    unique_hint: str | int | None = None,
) -> Path:
    """Construit le chemin complet cible d'un PDF."""
    saison = normalize_saison_code(saison_code)
    entite = sanitize_pdf_part(entite_code)
    poule = sanitize_pdf_part(poule_code)
    filename = build_pdf_filename(
        match_code=match_code,
        entite_code=entite,
        poule_code=poule,
        journee=journee,
        unique_hint=unique_hint,
    )
    return Path(base_dir) / saison / entite / poule / filename


def extract_match_code_from_pdf_path(path: Path | str) -> str:
    """Extrait le code match depuis un chemin PDF."""
    stem = Path(path).stem

    # Ancien format transitoire : <CODE>__e-...__p-...__j-...__h-...
    if "__" in stem:
        return stem.split("__", 1)[0]

    # Ancien format : <ENTITE>_<CODE>
    if "_" in stem:
        return stem.split("_", 1)[1]

    # Ancien format saisonnier : <CODE>
    return stem
