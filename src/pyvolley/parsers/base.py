"""
Interface abstraite pour les parsers de feuilles de match.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

from pyvolley.core.models import Match


@dataclass
class ParseResult:
    """Résultat du parsing d'un PDF."""
    success: bool
    match: Optional[Match] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parse_time_ms: float = 0.0
    
    # Métriques de qualité
    fields_extracted: int = 0
    fields_total: int = 0
    
    @property
    def completeness(self) -> float:
        """Pourcentage de champs extraits."""
        if self.fields_total == 0:
            return 0.0
        return self.fields_extracted / self.fields_total
    
    def add_error(self, message: str):
        self.errors.append(message)
        
    def add_warning(self, message: str):
        self.warnings.append(message)


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
