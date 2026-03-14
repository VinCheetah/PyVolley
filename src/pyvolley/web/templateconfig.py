"""
Configuration des templates Jinja2 pour l'application web.

Centralise la configuration du moteur de templates, les filtres personnalisés,
et les variables globales disponibles dans tous les templates.
"""

from pathlib import Path
from datetime import date as dt_date

from fastapi.templating import Jinja2Templates

from pyvolley.web.helpers.niveau import resolve_niveau_badge


# ── Chemins ──────────────────────────────────────────────────────────
WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# ── Instance Jinja2 ─────────────────────────────────────────────────
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ═══════════════════════════════════════════════════════════════════
#  Filtres Jinja2
# ═══════════════════════════════════════════════════════════════════

def format_date(value, fmt="%d/%m/%Y"):
    """Formate une date au format français."""
    if value is None:
        return "-"
    if isinstance(value, dt_date):
        return value.strftime(fmt)
    return str(value)


def truncate_name(value, length=20):
    """Tronque un nom s'il dépasse la longueur maximale."""
    if value and len(value) > length:
        return value[:length] + "..."
    return value or "-"


templates.env.filters["format_date"] = format_date
templates.env.filters["truncate_name"] = truncate_name


# ═══════════════════════════════════════════════════════════════════
#  Variables globales Jinja2
# ═══════════════════════════════════════════════════════════════════

def path_for_entity(
    entity_type: str, entity_id: int | None, fallback: str = "#"
) -> str:
    """Génère l'URL pour une entité donnée."""
    if not entity_id:
        return fallback
    mapping = {
        "home": "/",
        "search": "/search",
        "match": f"/matchs/{entity_id}",
        "joueur": f"/joueurs/{entity_id}",
        "equipe": f"/equipes/{entity_id}",
        "club": f"/clubs/{entity_id}",
        "arbitre": f"/arbitres/{entity_id}",
        "entraineur": f"/entraineurs/{entity_id}",
        "competition": f"/competitions/{entity_id}",
        "poule": f"/poules/{entity_id}",
    }
    return mapping.get(entity_type, fallback)


def competition_url_for_equipe(equipe, fallback: str = "#") -> str:
    """Retourne l'URL de la compétition associée à une équipe."""
    if not equipe:
        return fallback

    competition = getattr(equipe, "competition", None)
    if competition is not None and getattr(competition, "id", None):
        return f"/competitions/{competition.id}"

    competition_id = getattr(equipe, "competition_id", None)
    if competition_id:
        return f"/competitions/{competition_id}"

    return fallback


templates.env.globals["now_date"] = lambda: dt_date.today().isoformat()
templates.env.globals["resolve_niveau_badge"] = resolve_niveau_badge
templates.env.globals["path_for_entity"] = path_for_entity
templates.env.globals["competition_url_for_equipe"] = competition_url_for_equipe
