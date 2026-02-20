"""
Patterns de poules connus pour les compétitions nationales FFVB.

Utilisés en dernier recours lorsque la découverte dynamique (scraping
des pages home / calendrier) ne renvoie rien.

Chaque pattern est un tuple ``(code, nom)`` ou ``(code, nom, is_division)``.
Si ``is_division`` est omis, il vaut ``False`` (poule classique).
"""

from __future__ import annotations

from pyvolley.scrapers.ffvb.models import PouleInfo

# Type d'un pattern : (code, nom) ou (code, nom, is_division)
_PatternEntry = tuple[str, str] | tuple[str, str, bool]


def get_known_poules(entity_code: str, saison: str) -> list[PouleInfo]:
    """
    Retourne les poules connues pour une entité nationale.

    Args:
        entity_code: Code de l'entité (ABCCS, ACJEUNES, AALNV)
        saison: Saison au format YYYY/YYYY
    """
    patterns = _PATTERNS.get(entity_code)
    if patterns is None:
        return []
    return [
        PouleInfo(
            code=entry[0],
            nom=entry[1],
            entity_code=entity_code,
            saison=saison,
            is_division=entry[2] if len(entry) > 2 else False,
        )
        for entry in patterns
    ]


# ── Entités couvertes par des patterns connus ──────────────────────────────

PATTERN_ENTITY_CODES = frozenset({"ABCCS", "ACJEUNES", "AALNV"})

# ── Patterns ───────────────────────────────────────────────────────────────

_ABCCS_PATTERNS: list[_PatternEntry] = [
    # Matches internationaux
    ("INT", "Matches Internationaux"),
    # Supercoupes
    ("SCF", "Supercoupe Féminine"),
    ("SCM", "Supercoupe Masculine"),
    # Coupe de France Pro
    ("CFF", "Coupe de France Féminine Pro"),
    ("CFM", "Coupe de France Masculine Pro"),
    # Elite Féminine
    ("EFA", "Elite Féminine - Poule Haute"),
    ("EFB", "Elite Féminine - Poule Basse"),
    ("EFC", "Elite Féminine - Play-Off"),
    ("EFD", "Elite Féminine - Play-Down 1"),
    ("EFE", "Elite Féminine - Play-Down 2"),
    ("EFF", "Elite Féminine - Play-Off"),
    ("EFG", "Elite Féminine - Play-Down"),
    ("EFH", "Elite Féminine - Barrage"),
    # Elite Masculine
    ("EMA", "Elite Masculine - Poule A"),
    ("EMB", "Elite Masculine - Poule B"),
    ("EMC", "Elite Masculine - Play-Off"),
    ("EMD", "Elite Masculine - Play-Down 1"),
    ("EME", "Elite Masculine - Play-Down 2"),
    # EAM (Elite Avenir Masculine)
    ("EAA", "EAM - Poule A"),
    ("EAB", "EAM - Poule B"),
    ("EAC", "EAM - Barrages"),
    ("EAD", "EAM - Poule D"),
    ("EAE", "EAM - Barrages"),
    ("EAF", "EAM - Zone Nord Poule Haute"),
    ("EAG", "EAM - Zone Nord Poule Basse"),
    ("EAH", "EAM - Zone Sud Poule Haute"),
    ("EAI", "EAM - Zone Sud Poule Basse"),
    ("EAJ", "EAM - Barrages Poules Hautes"),
    ("EAK", "EAM - Barrages Poules Basses"),
    ("EAX", "EAM - Délégations"),
    ("EPA", "EAM - Phase Finale Poule A"),
    ("EPB", "EAM - Phase Finale Poule B"),
    ("EPC", "EAM - Phase Finale Poule C"),
    ("EPD", "EAM - Phase Finale Poule D"),
    ("EPE", "EAM - Phase Finale Poule E"),
    ("EPF", "EAM - Phase Finale"),
    ("EPG", "EAM - Classement 9-11"),
    ("EPH", "EAM - Phase Finale"),
    # N2 Féminine
    ("2FA", "N2 Féminine Poule A"),
    ("2FB", "N2 Féminine Poule B"),
    ("2FC", "N2 Féminine Poule C"),
    ("2FD", "N2 Féminine Poule D"),
    ("2FE", "N2 Féminine Final Four"),
    ("2FF", "N2 Féminine Barrage"),
    ("2FG", "N2 Féminine Final Four"),
    ("2FN", "Poule Finale N2F/Ultramarin"),
    ("2FU", "Finale N2F/Ultramarin"),
    ("2FX", "N2 Féminine Délégations"),
    ("F2A", "Finale N2F/Ultramarin Poule A"),
    ("F2B", "Finale N2F/Ultramarin Poule B"),
    ("F2F", "Finale N2F/Ultramarin"),
    ("FUA", "Poule Finale Féminine Ultramarine"),
    ("FUF", "Finale Féminine Ultramarine"),
    ("FUX", "Finale Féminine Ultramarine Délégations"),
    # N2 Masculine
    ("2MA", "N2 Masculine Poule A"),
    ("2MB", "N2 Masculine Poule B"),
    ("2MC", "N2 Masculine Poule C"),
    ("2MD", "N2 Masculine Poule D"),
    ("2ME", "N2 Masculine Final Four"),
    ("2MN", "Poule Finale N2M/Ultramarin"),
    ("2MU", "Finale N2M/Ultramarin"),
    ("2MX", "N2 Masculine Délégations"),
    ("M2A", "Finale N2M/Ultramarin Poule A"),
    ("M2B", "Finale N2M/Ultramarin Poule B"),
    ("M2F", "Finale N2M/Ultramarin"),
    ("MUA", "Poule Finale Masculine Ultramarine"),
    ("MUF", "Finale Masculine Ultramarine"),
    ("MUX", "Finale Masculine Ultramarine Délégations"),
    # N3 Féminine
    ("3FA", "N3 Féminine Poule A"),
    ("3FB", "N3 Féminine Poule B"),
    ("3FC", "N3 Féminine Poule C"),
    ("3FD", "N3 Féminine Poule D"),
    ("3FE", "N3 Féminine Poule E"),
    ("3FF", "N3 Féminine Poule F"),
    ("3FG", "N3 Féminine Poule G"),
    ("3FH", "N3 Féminine Poule H"),
    ("3FI", "Qualifications Phase Finale N3F"),
    ("3FJ", "N3 Féminine Final Four"),
    ("3FK", "Barrages Maintien N3F"),
    ("3FT", "Tournoi d'Accession en N2F"),
    ("3FX", "Poule Finale N3F Délégations"),
    ("F3A", "Poule Finale N3F/Ultramarin"),
    ("F3F", "N3F Phase Finale"),
    # N3 Masculine
    ("3MA", "N3 Masculine Poule A"),
    ("3MB", "N3 Masculine Poule B"),
    ("3MC", "N3 Masculine Poule C"),
    ("3MD", "N3 Masculine Poule D"),
    ("3ME", "N3 Masculine Poule E"),
    ("3MF", "N3 Masculine Poule F"),
    ("3MG", "N3 Masculine Poule G"),
    ("3MH", "N3 Masculine Poule H"),
    ("3MI", "Qualifications Phase Finale N3M"),
    ("3MJ", "N3 Masculine Final Four"),
    ("3MK", "Barrages Maintien N3M"),
    ("3MT", "Tournoi d'Accession en N2M"),
    ("3MX", "Poule Finale N3M Délégations"),
    ("M3A", "Poule Finale N3M/Ultramarin Poule A"),
    ("M3B", "Poule Finale N3M/Ultramarin Poule B"),
    ("M3C", "Poule Finale N3M/Ultramarin Poule C"),
    ("M3D", "Poule Finale N3M/Ultramarin"),
    ("M3F", "N3M Phase Finale"),
    # Coupe de France Fédérale
    ("CDF", "Coupe de France Fédérale Féminine"),
    ("CDM", "Coupe de France Fédérale Masculine"),
]

_ACJEUNES_PATTERNS: list[_PatternEntry] = [
    # ── Divisions principales (division=, actives 2024+) ──────────────
    ("JFX", "CdF Jeunes M21 Féminine", True),
    ("JMX", "CdF Jeunes M21 Masculine", True),
    ("CFX", "CdF Jeunes M18 Féminine", True),
    ("CMX", "CdF Jeunes M18 Masculine", True),
    ("RFX", "CdF Jeunes M15 Féminine", True),
    ("RMX", "CdF Jeunes M15 Masculine", True),
    ("MFX", "CdF Jeunes M13 Féminine", True),
    ("MMX", "CdF Jeunes M13 Masculine", True),
    ("BFX", "CdF Jeunes Benjamines Féminine", True),
    ("BMX", "CdF Jeunes Benjamins Masculine", True),
    # ── Divisions additionnelles (certaines saisons 2021-2025) ────────
    ("PFX", "CdF Jeunes Poussines Féminine", True),
    ("PMX", "CdF Jeunes Poussins Masculine", True),
    ("MVF", "CdF Jeunes Micro-Volley Féminine", True),
    ("MVM", "CdF Jeunes Micro-Volley Masculine", True),
    ("VYF", "CdF Jeunes VY Féminine", True),
    ("VYM", "CdF Jeunes VY Masculine", True),
    ("XVF", "CdF Jeunes XV Féminine", True),
    ("XVM", "CdF Jeunes XV Masculine", True),
    # ── Phases finales (poule=, anciennes saisons) ────────────────────
    ("JFA", "CdF Jeunes Juniors Féminine Finale"),
    ("JMA", "CdF Jeunes Juniors Masculine Finale"),
    # ── Poules historiques (poule=, pré-2024) ─────────────────────────
    ("CLA", "CdF Jeunes Cadets Poule A"),
    ("CLB", "CdF Jeunes Cadets Poule B"),
    ("CLC", "CdF Jeunes Cadets Poule C"),
    ("CLD", "CdF Jeunes Cadets Poule D"),
    ("CRA", "CdF Jeunes Cadets CRA"),
    ("CRB", "CdF Jeunes Cadets CRB"),
]

_AALNV_PATTERNS: list[_PatternEntry] = [
    ("MSL", "Marmara SpikeLigue"),
    ("SPS", "Saforelle Power 6"),
    ("LBM", "Ligue B Masculine"),
    ("PAZ", "Marmara SpikeLigue - Playoffs"),
    ("FAZ", "Saforelle Power 6 - Playoffs"),
    ("DAZ", "Ligue A Masculine - Qualification Europe"),
    ("PBA", "Ligue B Masculine - Playoffs Poule A"),
    ("PBB", "Ligue B Masculine - Playoffs Poule B"),
    ("PBZ", "Ligue B Masculine - Playoffs"),
]

_PATTERNS: dict[str, list[_PatternEntry]] = {
    "ABCCS": _ABCCS_PATTERNS,
    "ACJEUNES": _ACJEUNES_PATTERNS,
    "AALNV": _AALNV_PATTERNS,
}
