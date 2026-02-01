"""
Factory pour la création et sélection des parsers.
"""

from pathlib import Path
from typing import Type, Optional

from pyvolley.parsers.base import BaseParser
from pyvolley.parsers.v2 import MatchSheetParserV2
from pyvolley.parsers.v3 import MatchSheetParserV3


class ParserFactory:
    """
    Factory pour créer et gérer les parsers.
    
    Permet de :
    - Enregistrer différents parsers
    - Sélectionner automatiquement le meilleur parser
    - Comparer les performances
    """
    
    _parsers: dict[str, Type[BaseParser]] = {}
    _default_parser: Optional[str] = None
    
    @classmethod
    def register(cls, parser_class: Type[BaseParser], name: Optional[str] = None):
        """
        Enregistre un parser.
        
        Args:
            parser_class: Classe du parser
            name: Nom optionnel (utilise parser_class.name par défaut)
        """
        instance = parser_class()
        key = name or instance.name
        cls._parsers[key] = parser_class
        
        if cls._default_parser is None:
            cls._default_parser = key
    
    @classmethod
    def get(cls, name: str) -> BaseParser:
        """
        Récupère une instance de parser par son nom.
        
        Args:
            name: Nom du parser
            
        Returns:
            Instance du parser
            
        Raises:
            KeyError: Si le parser n'existe pas
        """
        if name not in cls._parsers:
            raise KeyError(f"Parser '{name}' non trouvé. Disponibles: {list(cls._parsers.keys())}")
        return cls._parsers[name]()
    
    @classmethod
    def get_default(cls) -> BaseParser:
        """Retourne le parser par défaut (V3 - pdfplumber)."""
        if cls._default_parser is None:
            # Enregistrer le parser par défaut (V3)
            cls.register(MatchSheetParserV3)
        if cls._default_parser is None:
            raise RuntimeError("Aucun parser par défaut configuré")
        return cls.get(cls._default_parser)
    
    @classmethod
    def set_default(cls, name: str):
        """Définit le parser par défaut."""
        if name not in cls._parsers:
            raise KeyError(f"Parser '{name}' non trouvé")
        cls._default_parser = name
    
    @classmethod
    def list_parsers(cls) -> list[str]:
        """Liste les parsers disponibles."""
        return list(cls._parsers.keys())
    
    @classmethod
    def auto_select(cls, pdf_path: Path) -> BaseParser:
        """
        Sélectionne automatiquement le meilleur parser pour un fichier.
        
        Args:
            pdf_path: Chemin vers le PDF
            
        Returns:
            Le parser le plus adapté
        """
        pdf_path = Path(pdf_path)
        
        for name, parser_class in cls._parsers.items():
            parser = parser_class()
            if parser.can_parse(pdf_path):
                return parser
        
        # Fallback au parser par défaut
        return cls.get_default()


def get_parser(name: Optional[str] = None) -> BaseParser:
    """
    Fonction utilitaire pour obtenir un parser.
    
    Args:
        name: Nom du parser (optionnel, utilise le défaut)
        
    Returns:
        Instance du parser
    """
    if name:
        return ParserFactory.get(name)
    return ParserFactory.get_default()


# Enregistrer les parsers par défaut
# V3 est le parser principal (pdfplumber, 100% de succès)
# V2 conservé pour référence (PyMuPDF, plus rapide mais non fonctionnel)
ParserFactory.register(MatchSheetParserV3)
ParserFactory.register(MatchSheetParserV2)
