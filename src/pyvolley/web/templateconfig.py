"""
Configuration des templates Jinja2 pour l'application web.

Centralise la configuration du moteur de templates, les filtres personnalisés,
et les variables globales disponibles dans tous les templates.
"""

from pathlib import Path
from datetime import date as dt_date

from urllib.parse import urlencode
from jinja2 import pass_context

from fastapi.templating import Jinja2Templates

from pyvolley.web.helpers.niveau import resolve_niveau_badge


# ── Chemins ──────────────────────────────────────────────────────────
WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# ── Instance Jinja2 ─────────────────────────────────────────────────
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


_template_response = templates.TemplateResponse


def _template_response_compat(*args, **kwargs):
    """Compatibilité entre l'ancien et le nouvel ordre d'arguments.

    Starlette attend maintenant ``TemplateResponse(request, name, context)``,
    alors que plusieurs routes du projet utilisent encore
    ``TemplateResponse(name, context)``.
    """
    if args and hasattr(args[0], "scope") and len(args) >= 2 and isinstance(args[1], str):
        return _template_response(*args, **kwargs)

    if args and isinstance(args[0], str):
        name = args[0]
        context = args[1] if len(args) >= 2 and isinstance(args[1], dict) else kwargs.pop("context", None)
        request = kwargs.pop("request", None)
        if request is None and isinstance(context, dict):
            request = context.get("request")
        if request is None:
            raise TypeError("TemplateResponse requires a request object in context")
        return _template_response(request, name, context, **kwargs)

    return _template_response(*args, **kwargs)


templates.TemplateResponse = _template_response_compat


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
    entity_type: str, entity: Any, fallback: str = "#"
) -> str:
    """Génère l'URL canonique pour une entité en privilégiant les identifiants FFVB."""
    if not entity:
        return fallback

    if entity_type == "home":
        return "/"
    if entity_type == "search":
        return "/search"

    if entity_type == "joueur":
        licence = getattr(entity, "licence", None)
        if not licence and isinstance(entity, dict):
            licence = entity.get("licence")
        val = licence or getattr(entity, "id", None) or entity
        return f"/joueurs/{val}"

    if entity_type == "club":
        code_ffvb = getattr(entity, "code_ffvb", None)
        if not code_ffvb and isinstance(entity, dict):
            code_ffvb = entity.get("code_ffvb")
        val = code_ffvb or getattr(entity, "id", None) or entity
        return f"/clubs/{val}"

    if entity_type == "match":
        code_match = getattr(entity, "code_match", None)
        if not code_match and isinstance(entity, dict):
            code_match = entity.get("code_match")
        val = code_match or getattr(entity, "id", None) or entity
        return f"/matchs/{val}"

    if entity_type == "arbitre":
        licence = getattr(entity, "licence", None)
        if not licence and isinstance(entity, dict):
            licence = entity.get("licence")
        val = licence or getattr(entity, "id", None) or entity
        return f"/arbitres/{val}"

    if entity_type == "competition":
        code = getattr(entity, "code_competition", None)
        if not code and isinstance(entity, dict):
            code = entity.get("code_competition")
        val = code or getattr(entity, "id", None) or entity
        return f"/competitions/{val}"

    if entity_type == "poule":
        code = getattr(entity, "code", None)
        if not code and isinstance(entity, dict):
            code = entity.get("code")
        val = code or getattr(entity, "id", None) or entity
        return f"/poules/{val}"

    if entity_type == "equipe":
        val = getattr(entity, "id", None) or entity
        return f"/equipes/{val}"

    if entity_type == "entraineur":
        licence = getattr(entity, "licence", None)
        if not licence and isinstance(entity, dict):
            licence = entity.get("licence")
        val = licence or getattr(entity, "id", None) or entity
        return f"/entraineurs/{val}"

    return fallback


def competition_url_for_equipe(equipe, fallback: str = "#") -> str:
    """Retourne l'URL de la compétition associée à une équipe."""
    if not equipe:
        return fallback

    competition = getattr(equipe, "competition", None)
    if competition is not None:
        target = getattr(competition, "code_competition", None) or getattr(competition, "id", None)
        if target:
            return f"/competitions/{target}"

    competition_id = getattr(equipe, "competition_id", None)
    if competition_id:
        return f"/competitions/{competition_id}"

    return fallback


from pyvolley.core.constants import ROLE_COLORS, ROLE_LABELS, get_role_label

@pass_context
def update_query_string(context, **kwargs) -> str:
    """Met à jour les paramètres de requête de l'URL courante.

    Permet d'ajouter, modifier ou supprimer des paramètres (si value est None ou '').
    """
    request = context.get("request")
    if not request:
        valid_kwargs = {k: v for k, v in kwargs.items() if v is not None and v != ""}
        return f"?{urlencode(valid_kwargs)}" if valid_kwargs else "?"

    params = dict(request.query_params)
    for k, v in kwargs.items():
        if v is None or v == "":
            params.pop(k, None)
        else:
            params[k] = str(v)

    query_str = urlencode(params)
    return f"?{query_str}" if query_str else "?"


templates.env.globals["now_date"] = lambda: dt_date.today().isoformat()
templates.env.globals["resolve_niveau_badge"] = resolve_niveau_badge
templates.env.globals["path_for_entity"] = path_for_entity
templates.env.globals["competition_url_for_equipe"] = competition_url_for_equipe
templates.env.globals["get_role_label"] = get_role_label
templates.env.globals["ROLE_COLORS"] = ROLE_COLORS
templates.env.globals["ROLE_LABELS"] = ROLE_LABELS
templates.env.globals["update_query_string"] = update_query_string
