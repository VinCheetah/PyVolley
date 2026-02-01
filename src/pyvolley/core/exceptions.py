"""
Exceptions personnalisées pour PyVolley.
"""


class PyVolleyError(Exception):
    """Exception de base pour PyVolley."""
    pass


# ============== Scraping ==============

class ScrapingError(PyVolleyError):
    """Erreur lors du scraping."""
    pass


class NetworkError(ScrapingError):
    """Erreur réseau lors du scraping."""
    pass


class PageNotFoundError(ScrapingError):
    """Page non trouvée."""
    pass


class RateLimitError(ScrapingError):
    """Limite de requêtes atteinte."""
    pass


# ============== Parsing ==============

class ParsingError(PyVolleyError):
    """Erreur lors du parsing d'un PDF."""
    pass


class InvalidPDFError(ParsingError):
    """PDF invalide ou corrompu."""
    pass


class MatchNotPlayedError(ParsingError):
    """Match non joué (feuille vide)."""
    pass


class DataExtractionError(ParsingError):
    """Erreur lors de l'extraction de données."""
    pass


# ============== Database ==============

class DatabaseError(PyVolleyError):
    """Erreur de base de données."""
    pass


class DuplicateEntryError(DatabaseError):
    """Entrée en double."""
    pass


class NotFoundError(DatabaseError):
    """Élément non trouvé."""
    pass


# ============== Validation ==============

class ValidationError(PyVolleyError):
    """Erreur de validation des données."""
    pass


class InvalidLicenceError(ValidationError):
    """Numéro de licence invalide."""
    pass


class InvalidScoreError(ValidationError):
    """Score invalide."""
    pass
