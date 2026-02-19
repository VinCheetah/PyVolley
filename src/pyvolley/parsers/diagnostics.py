"""
Système de diagnostic structuré pour le parsing des feuilles de match.

Sépare clairement :
- Les problèmes de **données** : information absente ou incomplète
  dans le PDF source (ne dépend pas du parser).
- Les problèmes de **parsing** : incohérence détectée lors de
  l'extraction, probable erreur de lecture ou de logique.
- Les **informations** : événements normaux mais notables
  (match non joué, format détecté, récupération de données…).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DiagnosticLevel(str, Enum):
    """Niveau de sévérité d'un diagnostic."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticOrigin(str, Enum):
    """Origine du problème détecté.

    Permet de distinguer un défaut du PDF source d'une erreur
    dans la logique d'extraction.
    """
    DATA = "data"       # Donnée absente / incomplète dans le PDF
    PARSING = "parsing" # Incohérence ou erreur de lecture du parser


class DiagnosticCategory(str, Enum):
    """Catégorie fonctionnelle du diagnostic."""
    # ── Identité du match ──
    CODE_MATCH = "code_match"
    DATE = "date"
    HEURE = "heure"
    LIEU = "lieu"
    SALLE = "salle"
    SAISON = "saison"
    COMPETITION = "competition"

    # ── Équipes ──
    EQUIPE = "equipe"
    JOUEUR = "joueur"
    CAPITAINE = "capitaine"
    LICENCE = "licence"
    LIBERO = "libero"
    OFFICIEL = "officiel"

    # ── Arbitrage ──
    ARBITRE = "arbitre"

    # ── Scores ──
    SCORE = "score"
    SET = "set"
    FORMATION = "formation"

    # ── Sanctions ──
    SANCTION = "sanction"

    # ── Intégrité ──
    DUPLICATION = "duplication"
    COHERENCE = "coherence"

    # ── Général ──
    MATCH_STATUS = "match_status"
    GENERAL = "general"


# Mapping catégorie → nom de dossier pour le classement des problèmes
CATEGORY_FOLDERS: dict[DiagnosticCategory, tuple[str, str]] = {
    # (folder_name, display_label)
    DiagnosticCategory.CODE_MATCH: ("code_match_manquant", "Code match manquant"),
    DiagnosticCategory.DATE: ("date_manquante", "Date manquante"),
    DiagnosticCategory.HEURE: ("heure_manquante", "Heure manquante"),
    DiagnosticCategory.LIEU: ("lieu_manquant", "Lieu manquant"),
    DiagnosticCategory.SALLE: ("salle_manquante", "Salle manquante"),
    DiagnosticCategory.SAISON: ("saison_manquante", "Saison non déterminée"),
    DiagnosticCategory.COMPETITION: ("competition_manquante", "Compétition manquante"),
    DiagnosticCategory.EQUIPE: ("nom_equipe_generique", "Nom d'équipe générique"),
    DiagnosticCategory.JOUEUR: ("aucun_joueur", "Aucun joueur détecté"),
    DiagnosticCategory.CAPITAINE: ("capitaine_non_detecte", "Capitaine non détecté"),
    DiagnosticCategory.LICENCE: ("licence_manquante", "Licence manquante"),
    DiagnosticCategory.LIBERO: ("libero", "Libéro"),
    DiagnosticCategory.OFFICIEL: ("officiel", "Officiel"),
    DiagnosticCategory.ARBITRE: ("arbitre_non_detecte", "Arbitre non détecté"),
    DiagnosticCategory.SCORE: ("score_invalide", "Score invalide"),
    DiagnosticCategory.SET: ("set", "Set"),
    DiagnosticCategory.FORMATION: ("formation", "Formation"),
    DiagnosticCategory.SANCTION: ("sanction", "Sanction détectée"),
    DiagnosticCategory.DUPLICATION: ("duplication", "Feuille dupliquée"),
    DiagnosticCategory.COHERENCE: ("incoherence_score", "Incohérence de score"),
    DiagnosticCategory.MATCH_STATUS: ("match_non_joue", "Match non joué"),
    DiagnosticCategory.GENERAL: ("autre", "Autre"),
}


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Un diagnostic individuel émis pendant le parsing.

    Attributes:
        level: Sévérité (info, warning, error).
        origin: Origine du problème (data ou parsing).
        category: Catégorie fonctionnelle.
        message: Description lisible du problème.
        context: Détails techniques optionnels (set, équipe, etc.).
    """
    level: DiagnosticLevel
    origin: DiagnosticOrigin
    category: DiagnosticCategory
    message: str
    context: Optional[dict] = None

    # ── Raccourcis de construction ──

    @classmethod
    def data_info(
        cls, category: DiagnosticCategory, message: str, **ctx,
    ) -> Diagnostic:
        """Donnée absente – informatif (pas une erreur)."""
        return cls(DiagnosticLevel.INFO, DiagnosticOrigin.DATA, category, message,
                   ctx or None)

    @classmethod
    def data_warning(
        cls, category: DiagnosticCategory, message: str, **ctx,
    ) -> Diagnostic:
        """Donnée manquante ou suspecte dans le PDF source."""
        return cls(DiagnosticLevel.WARNING, DiagnosticOrigin.DATA, category, message,
                   ctx or None)

    @classmethod
    def parse_warning(
        cls, category: DiagnosticCategory, message: str, **ctx,
    ) -> Diagnostic:
        """Incohérence détectée par le parser (erreur probable de lecture)."""
        return cls(DiagnosticLevel.WARNING, DiagnosticOrigin.PARSING, category, message,
                   ctx or None)

    @classmethod
    def parse_error(
        cls, category: DiagnosticCategory, message: str, **ctx,
    ) -> Diagnostic:
        """Erreur critique de parsing."""
        return cls(DiagnosticLevel.ERROR, DiagnosticOrigin.PARSING, category, message,
                   ctx or None)

    # ── Représentation ──

    def __str__(self) -> str:
        tag = f"[{self.origin.value}]" if self.origin == DiagnosticOrigin.DATA else ""
        return f"{tag} {self.message}".strip()


@dataclass
class DiagnosticCollector:
    """Collecteur de diagnostics pour une exécution de parsing.

    Fournit des méthodes pratiques pour émettre des diagnostics
    et les filtrer par niveau / origine / catégorie.
    """
    _items: list[Diagnostic] = field(default_factory=list)

    # ── Émission ──

    def add(self, diagnostic: Diagnostic) -> None:
        self._items.append(diagnostic)

    def data_info(self, category: DiagnosticCategory, message: str, **ctx) -> None:
        self._items.append(Diagnostic.data_info(category, message, **ctx))

    def data_warning(self, category: DiagnosticCategory, message: str, **ctx) -> None:
        self._items.append(Diagnostic.data_warning(category, message, **ctx))

    def parse_warning(self, category: DiagnosticCategory, message: str, **ctx) -> None:
        self._items.append(Diagnostic.parse_warning(category, message, **ctx))

    def parse_error(self, category: DiagnosticCategory, message: str, **ctx) -> None:
        self._items.append(Diagnostic.parse_error(category, message, **ctx))

    def extend(self, diagnostics: list[Diagnostic]) -> None:
        self._items.extend(diagnostics)

    # ── Accès ──

    @property
    def all(self) -> list[Diagnostic]:
        return list(self._items)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self._items if d.level == DiagnosticLevel.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self._items if d.level == DiagnosticLevel.WARNING]

    @property
    def infos(self) -> list[Diagnostic]:
        return [d for d in self._items if d.level == DiagnosticLevel.INFO]

    @property
    def data_issues(self) -> list[Diagnostic]:
        return [d for d in self._items if d.origin == DiagnosticOrigin.DATA]

    @property
    def parsing_issues(self) -> list[Diagnostic]:
        return [d for d in self._items if d.origin == DiagnosticOrigin.PARSING]

    def by_category(self, category: DiagnosticCategory) -> list[Diagnostic]:
        return [d for d in self._items if d.category == category]

    @property
    def has_errors(self) -> bool:
        return any(d.level == DiagnosticLevel.ERROR for d in self._items)

    @property
    def has_warnings(self) -> bool:
        return any(d.level == DiagnosticLevel.WARNING for d in self._items)

    # ── Résumé ──

    def summary(self) -> dict[str, int]:
        """Compteurs par (origin, level)."""
        from collections import Counter
        c: Counter = Counter()
        for d in self._items:
            c[f"{d.origin.value}_{d.level.value}"] += 1
        return dict(c)

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)
