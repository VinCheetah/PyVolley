"""
Factory pour la création et sélection des parsers.

Fournit un point d'accès unique et centralisé pour instancier
les parsers de feuilles de match.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Type

from pyvolley.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class ParserFactory:
    """Registre central des parsers de feuilles de match.

    Gère l'enregistrement, la sélection automatique et l'instanciation
    des différents parsers disponibles dans le projet.

    Exemples::

        # Obtenir le parser par défaut
        parser = ParserFactory.get_default()

        # Parser un PDF
        result = parser.parse("match.pdf")

        # Sélection automatique du meilleur parser
        parser = ParserFactory.auto_select("match.pdf")

        # Lister les parsers disponibles
        names = ParserFactory.list_parsers()
    """

    _parsers: dict[str, Type[BaseParser]] = {}
    _default_parser: Optional[str] = None
    _aliases: dict[str, str] = {
        "fast": "FastMatchSheetParser",
        "legacy": "MatchSheetParser",
        "pdfplumber": "MatchSheetParser",
        "simple": "MatchSheetParser",
    }

    @classmethod
    def resolve_name(cls, name: str) -> str:
        """Résout un nom ou un alias de parser en sa clé canonique."""
        lower_name = name.lower()
        if lower_name in cls._aliases:
            return cls._aliases[lower_name]
        for key in cls._parsers:
            if key.lower() == lower_name:
                return key
        return name

    @classmethod
    def register(cls, parser_class: Type[BaseParser], name: Optional[str] = None) -> None:
        """Enregistre un parser dans le registre.

        Args:
            parser_class: Classe du parser (doit hériter de BaseParser).
            name: Nom d'enregistrement. Si omis, utilise ``parser_class().name``.
        """
        instance = parser_class()
        key = name or instance.name
        cls._parsers[key] = parser_class

        if cls._default_parser is None:
            cls._default_parser = key
            logger.debug("Parser par défaut : %s (v%s)", key, instance.version)

    @classmethod
    def get(cls, name: str) -> BaseParser:
        """Instancie un parser par son nom ou son alias.

        Raises:
            KeyError: Si le parser n'est pas enregistré.
        """
        canonical_name = cls.resolve_name(name)
        if canonical_name not in cls._parsers:
            available = ", ".join(list(cls._parsers.keys()) + list(cls._aliases.keys()))
            raise KeyError(
                f"Parser '{name}' non trouvé. Disponibles : {available}"
            )
        return cls._parsers[canonical_name]()

    @classmethod
    def get_default(cls) -> BaseParser:
        """Retourne une instance du parser par défaut.

        Enregistre automatiquement ``FastMatchSheetParser`` et ``MatchSheetParser`` s'il n'y a aucun
        parser enregistré.

        Raises:
            RuntimeError: Aucun parser par défaut configuré.
        """
        if cls._default_parser is None:
            cls._ensure_default_registered()
        if cls._default_parser is None:
            raise RuntimeError("Aucun parser par défaut configuré")
        return cls.get(cls._default_parser)

    @classmethod
    def set_default(cls, name: str) -> None:
        """Change le parser par défaut.

        Raises:
            KeyError: Si le parser n'est pas enregistré.
        """
        canonical_name = cls.resolve_name(name)
        if canonical_name not in cls._parsers:
            raise KeyError(f"Parser '{name}' non trouvé")
        cls._default_parser = canonical_name

    @classmethod
    def list_parsers(cls) -> list[str]:
        """Liste les noms de tous les parsers enregistrés."""
        return list(cls._parsers.keys())

    @classmethod
    def auto_select(cls, pdf_path: Path | str) -> BaseParser:
        """Sélectionne automatiquement le parser le plus adapté à un PDF.

        Teste chaque parser enregistré via ``can_parse()`` et retourne le
        premier qui répond positivement. Retombe sur le parser par défaut
        si aucun ne se déclare compatible.
        """
        pdf_path = Path(pdf_path)

        for name, parser_class in cls._parsers.items():
            parser = parser_class()
            try:
                if parser.can_parse(pdf_path):
                    logger.debug("Auto-select : %s pour %s", name, pdf_path.name)
                    return parser
            except Exception:
                logger.debug("Erreur auto-select pour %s, ignoré", name, exc_info=True)

        return cls.get_default()

    @classmethod
    def _ensure_default_registered(cls) -> None:
        """Enregistre le parser principal si le registre est vide."""
        if cls._parsers:
            return
        from pyvolley.parsers.fast_parser import FastMatchSheetParser
        from pyvolley.parsers.parser import MatchSheetParser

        cls.register(FastMatchSheetParser)
        cls.register(MatchSheetParser)

    @classmethod
    def reset(cls) -> None:
        """Vide le registre (utile pour les tests)."""
        cls._parsers.clear()
        cls._default_parser = None


def get_parser(name: Optional[str] = None) -> BaseParser:
    """Raccourci pour obtenir un parser.

    Args:
        name: Nom du parser voulu, ou ``None`` pour le parser par défaut.
    """
    if name:
        return ParserFactory.get(name)
    return ParserFactory.get_default()


# ── Enregistrement automatique des parsers ──────────────────
from pyvolley.parsers.fast_parser import FastMatchSheetParser  # noqa: E402
from pyvolley.parsers.parser import MatchSheetParser  # noqa: E402

ParserFactory.register(FastMatchSheetParser)
ParserFactory.register(MatchSheetParser)
