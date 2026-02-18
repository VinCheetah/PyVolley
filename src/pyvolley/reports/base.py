"""
Classes de base pour le système de rapports PyVolley.

Le rapport est composé de sections modulaires. Chaque section
est indépendante et peut être incluse/exclue via configuration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.columns import Columns


@dataclass
class ReportSection:
    """Une section de rapport avec titre, contenu et métadonnées.

    Attributes:
        key: Identifiant unique de la section (ex: 'profil', 'matchs').
        title: Titre affiché (avec emoji optionnel).
        content: Contenu Rich renderable (Panel, Table, Text, str...).
        order: Ordre d'affichage (plus petit = plus haut).
        empty: True si la section n'a pas de données à afficher.
    """
    key: str
    title: str
    content: Any  # Rich renderable
    order: int = 0
    empty: bool = False


class Report(ABC):
    """Classe abstraite pour un rapport d'entité.

    Sous-classez et implémentez ``_build_sections`` pour créer
    un rapport spécifique (joueur, club, équipe, etc.).

    **Ajouter une section** : il suffit de rajouter un appel
    ``self._add(...)`` dans ``_build_sections``.

    **Retirer une section** : passez ``exclude={'key'}`` au constructeur
    ou à ``render()``.

    **Réordonner** : modifiez le paramètre ``order`` des sections.
    """

    def __init__(
        self,
        session,
        *,
        exclude: Optional[set[str]] = None,
        include: Optional[set[str]] = None,
        hide_empty: bool = True,
    ):
        self.session = session
        self.exclude = exclude or set()
        self.include = include  # None = toutes
        self.hide_empty = hide_empty
        self._sections: list[ReportSection] = []

    # ── API publique ────────────────────────────────────────────

    def build(self) -> list[ReportSection]:
        """Construit et retourne les sections du rapport."""
        self._sections.clear()
        self._build_sections()
        # Filtrer
        sections = [s for s in self._sections if self._should_include(s)]
        sections.sort(key=lambda s: s.order)
        return sections

    def render(self, console: Optional[Console] = None) -> None:
        """Construit et affiche le rapport dans la console Rich."""
        console = console or Console()
        sections = self.build()
        if not sections:
            console.print("[yellow]Aucune donnée à afficher pour ce rapport.[/yellow]")
            return
        for section in sections:
            console.print(section.content)

    def to_dict(self) -> dict[str, Any]:
        """Exporte le rapport en dictionnaire (pour JSON/API).

        Chaque section contribue une clé dans le dict.
        Seules les données textuelles sont exportées.
        """
        sections = self.build()
        return {
            "type": self.__class__.__name__,
            "sections": [
                {"key": s.key, "title": s.title, "empty": s.empty}
                for s in sections
            ],
        }

    # ── À implémenter ──────────────────────────────────────────

    @abstractmethod
    def _build_sections(self) -> None:
        """Construit les sections du rapport.

        Appeler ``self._add(...)`` pour chaque section.
        """
        ...

    # ── Helpers internes ────────────────────────────────────────

    def _add(self, section: ReportSection) -> None:
        """Ajoute une section au rapport."""
        self._sections.append(section)

    def _should_include(self, section: ReportSection) -> bool:
        """Détermine si une section doit être incluse."""
        if section.key in self.exclude:
            return False
        if self.include is not None and section.key not in self.include:
            return False
        if self.hide_empty and section.empty:
            return False
        return True

    # ── Helpers de rendu ────────────────────────────────────────

    @staticmethod
    def _panel(content: str, title: str, border_style: str = "blue") -> Panel:
        return Panel(content, title=title, border_style=border_style)

    @staticmethod
    def _table(title: str, columns: list[tuple[str, dict]], rows: list[list[str]]) -> Table:
        """Crée un Table Rich rapidement.

        Args:
            title: Titre du tableau.
            columns: Liste de (nom, kwargs_colonne).
            rows: Liste de lignes (liste de strings).
        """
        tbl = Table(title=title, box=box.SIMPLE, row_styles=["", "dim"])
        for col_name, col_kw in columns:
            tbl.add_column(col_name, **col_kw)
        for row in rows:
            tbl.add_row(*row)
        return tbl

    @staticmethod
    def _kv_panel(items: list[tuple[str, str]], *, title: str = "", border_style: str = "blue") -> Panel:
        """Panel avec des paires clé-valeur, alignées proprement."""
        if not items:
            return Panel("[dim]Aucune donnée[/dim]", title=title, border_style=border_style)
        max_label = max(len(label) for label, _ in items)
        lines = []
        for label, value in items:
            lines.append(f"[bold]{label:<{max_label}}[/bold]  {value}")
        return Panel("\n".join(lines), title=title, border_style=border_style)

    # ── Helpers utilitaires ─────────────────────────────────────

    @staticmethod
    def _safe(value: Any, default: str = "-") -> str:
        """Retourne la valeur en string, ou un défaut si None/vide."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return str(value)

    @staticmethod
    def _pct(numerator: int, denominator: int, *, decimals: int = 0) -> str:
        """Calcule un pourcentage avec gestion du division par zéro."""
        if denominator == 0:
            return "-"
        return f"{numerator / denominator * 100:.{decimals}f}%"

    @staticmethod
    def _ratio(a: int, b: int, *, decimals: int = 2) -> str:
        """Calcule un ratio avec gestion du division par zéro."""
        if b == 0:
            return "-"
        return f"{a / b:.{decimals}f}"
