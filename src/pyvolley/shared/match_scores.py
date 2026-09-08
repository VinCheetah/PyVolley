"""Helpers pour comparer et afficher plusieurs sources de score de match."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .match_status import normalize_score_sets


@dataclass(frozen=True)
class MatchScoreResolution:
    """Résultat normalisé d'une comparaison de scores."""

    score_export: Optional[str]
    score_pdf: Optional[str]
    score_effective: Optional[str]
    score_display: Optional[str]
    primary_source: Optional[str]
    secondary_source: Optional[str]
    conflict: bool


def score_sets_to_pair(score_sets: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """Convertit un score de sets normalisé en paire d'entiers."""
    normalized = normalize_score_sets(score_sets, replace_forfeit_with_zero=True)
    if not normalized:
        return None, None

    left_raw, right_raw = normalized.split("/", 1)
    left = int(left_raw) if left_raw.isdigit() else None
    right = int(right_raw) if right_raw.isdigit() else None
    return left, right


def resolve_match_score(
    score_export: Optional[str],
    score_pdf: Optional[str],
    *,
    legacy_score: Optional[str] = None,
) -> MatchScoreResolution:
    """Résout les scores disponibles en choisissant une valeur effective.

    Priorité d'affichage et de traitement : score PDF > score export > score historique.
    Si les deux sources sont présentes et différentes, le score PDF reste la valeur
    effective mais la chaîne d'affichage expose explicitement l'écart.
    """
    export_norm = normalize_score_sets(score_export)
    pdf_norm = normalize_score_sets(score_pdf)
    legacy_norm = normalize_score_sets(legacy_score)

    score_effective = pdf_norm or export_norm or legacy_norm
    if pdf_norm and export_norm:
        conflict = pdf_norm != export_norm
        if conflict:
            score_display = f"PDF {pdf_norm} · export {export_norm}"
        else:
            score_display = pdf_norm
        return MatchScoreResolution(
            score_export=export_norm,
            score_pdf=pdf_norm,
            score_effective=score_effective,
            score_display=score_display,
            primary_source="pdf",
            secondary_source="export",
            conflict=conflict,
        )

    if pdf_norm:
        return MatchScoreResolution(
            score_export=export_norm,
            score_pdf=pdf_norm,
            score_effective=score_effective,
            score_display=pdf_norm,
            primary_source="pdf",
            secondary_source="export" if export_norm else None,
            conflict=False,
        )

    if export_norm:
        return MatchScoreResolution(
            score_export=export_norm,
            score_pdf=pdf_norm,
            score_effective=score_effective,
            score_display=export_norm,
            primary_source="export",
            secondary_source=None,
            conflict=False,
        )

    return MatchScoreResolution(
        score_export=export_norm,
        score_pdf=pdf_norm,
        score_effective=score_effective,
        score_display=legacy_norm,
        primary_source=None,
        secondary_source=None,
        conflict=False,
    )