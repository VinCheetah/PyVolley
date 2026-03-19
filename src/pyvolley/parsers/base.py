"""
Interface abstraite pour les parsers de feuilles de match.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, TYPE_CHECKING
from datetime import datetime

from pyvolley.core.models import Match

if TYPE_CHECKING:
    from pyvolley.parsers.diagnostics import Diagnostic
    from pyvolley.parsers.plausibility import PlausibilityReport


@dataclass
class ParseResult:
    """Résultat du parsing d'un PDF."""
    success: bool
    match: Optional[Match] = None
    errors: list[str] = field(default_factory=list)
    diagnostics: list["Diagnostic"] = field(default_factory=list)
    plausibility_report: Optional["PlausibilityReport"] = None
    parse_time_ms: float = 0.0
    
    # Métriques de qualité
    fields_extracted: int = 0
    fields_total: int = 0

    # Source tracking: maps field/section names to their extraction source.
    # Populated by the parser to show what data was extracted and from where.
    # Values are short source labels like "table_players", "header_line",
    # "words_positional", "table_results", "set_section", etc.
    field_sources: dict[str, str] = field(default_factory=dict)
    
    @property
    def completeness(self) -> float:
        """Pourcentage de champs extraits."""
        if self.fields_total == 0:
            return 0.0
        return self.fields_extracted / self.fields_total
    
    def add_error(self, message: str):
        self.errors.append(message)

    @property
    def warnings_count(self) -> int:
        """Nombre de diagnostics de niveau WARNING ou ERROR."""
        from pyvolley.parsers.diagnostics import DiagnosticLevel
        return sum(
            1 for d in self.diagnostics
            if d.level in (DiagnosticLevel.WARNING, DiagnosticLevel.ERROR)
        )

    @property
    def plausibility_changes_count(self) -> int:
        if not self.plausibility_report:
            return 0
        return self.plausibility_report.touched_count

    @property
    def plausibility_flagged_count(self) -> int:
        if not self.plausibility_report:
            return 0
        return self.plausibility_report.flagged_count


@dataclass
class ParserMetrics:
    """Métriques de performance d'un parser."""
    parser_name: str
    version: str
    total_parsed: int = 0
    successful: int = 0
    failed: int = 0
    total_time_ms: float = 0.0
    avg_time_ms: float = 0.0
    avg_completeness: float = 0.0
    
    def update(self, result: ParseResult):
        """Met à jour les métriques avec un nouveau résultat."""
        self.total_parsed += 1
        self.total_time_ms += result.parse_time_ms
        
        if result.success:
            self.successful += 1
        else:
            self.failed += 1
        
        # Recalculer les moyennes
        self.avg_time_ms = self.total_time_ms / self.total_parsed
        # Pour la complétude, on fait une moyenne mobile
        self.avg_completeness = (
            (self.avg_completeness * (self.total_parsed - 1) + result.completeness)
            / self.total_parsed
        )


class BaseParser(ABC):
    """
    Interface abstraite pour les parsers de feuilles de match FFVB.
    
    Permet de comparer différentes implémentations de parsing
    pour optimiser la performance et la précision.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du parser."""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """Version du parser."""
        pass
    
    @property
    def description(self) -> str:
        """Description du parser."""
        return f"{self.name} v{self.version}"
    
    @abstractmethod
    def parse(self, pdf_path: Path) -> ParseResult:
        """
        Parse un fichier PDF de feuille de match.
        
        Args:
            pdf_path: Chemin vers le fichier PDF
            
        Returns:
            ParseResult contenant le match parsé ou les erreurs
        """
        pass
    
    @abstractmethod
    def can_parse(self, pdf_path: Path) -> bool:
        """
        Vérifie si ce parser peut traiter le fichier.
        
        Args:
            pdf_path: Chemin vers le fichier PDF
            
        Returns:
            True si le parser peut traiter ce fichier
        """
        pass
    
    def parse_batch(self, pdf_paths: list[Path]) -> list[ParseResult]:
        """
        Parse plusieurs fichiers PDF.
        
        Args:
            pdf_paths: Liste des chemins PDF
            
        Returns:
            Liste des résultats
        """
        return [self.parse(path) for path in pdf_paths]
    
    def get_metrics(self) -> ParserMetrics:
        """
        Retourne les métriques de performance du parser.
        
        Returns:
            Métriques actuelles
        """
        if not hasattr(self, "_metrics"):
            self._metrics = ParserMetrics(
                parser_name=self.name,
                version=self.version
            )
        return self._metrics
    
    def _record_result(self, result: ParseResult):
        """Enregistre un résultat dans les métriques."""
        self.get_metrics().update(result)
