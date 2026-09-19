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

from typing import Any, Optional
from pyvolley.core.config import settings
from pyvolley.scrapers.ffvb.utils import (
    build_competition_calendar_url,
    build_classement_url,
    build_home_url,
    build_pdf_url,
)
from pyvolley.scrapers.ffvb.export_scraper import (
    build_export_url,
    build_feuille_match_url,
)
from pyvolley.scrapers.ffvb.annuaire_scraper import build_annuaire_url


def _extract_canonical_val(entity: Any, *keys: Any) -> Any:
    """Extrait une valeur canonique depuis un objet ou un dictionnaire."""
    if not entity:
        return None

    flat_keys = []
    for k in keys:
        if isinstance(k, (list, tuple)):
            flat_keys.extend(k)
        else:
            flat_keys.append(k)

    if isinstance(entity, dict):
        for k in flat_keys:
            v = entity.get(k)
            if v is not None and not isinstance(v, dict):
                return v
        v_id = entity.get("id")
        if v_id is not None and not isinstance(v_id, dict):
            return v_id
        return None

    # Objets (modèles SQLAlchemy, dataclasses, etc.)
    for k in flat_keys:
        v = getattr(entity, k, None)
        if v is not None and not isinstance(v, dict):
            return v

    v_id = getattr(entity, "id", None)
    if v_id is not None and not isinstance(v_id, dict):
        return v_id

    # Valeur scalaire directe (str, int)
    if isinstance(entity, (str, int, float)):
        return str(entity)

    return None


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
        val = _extract_canonical_val(entity, "licence")
        return f"/joueurs/{val}" if val is not None else fallback

    if entity_type == "club":
        val = _extract_canonical_val(entity, "code_ffvb")
        return f"/clubs/{val}" if val is not None else fallback

    if entity_type == "match":
        val = _extract_canonical_val(entity, "code_match")
        return f"/matchs/{val}" if val is not None else fallback

    if entity_type == "arbitre":
        val = _extract_canonical_val(entity, "licence")
        return f"/arbitres/{val}" if val is not None else fallback

    if entity_type == "competition":
        val = _extract_canonical_val(entity, "code_competition")
        return f"/competitions/{val}" if val is not None else fallback

    if entity_type == "poule":
        val = _extract_canonical_val(entity, "code")
        return f"/poules/{val}" if val is not None else fallback

    if entity_type == "equipe":
        val = _extract_canonical_val(entity, "id")
        return f"/equipes/{val}" if val is not None else fallback

    if entity_type == "entraineur":
        val = _extract_canonical_val(entity, "licence")
        return f"/entraineurs/{val}" if val is not None else fallback

    return fallback


def _resolve_match_saison(match: Any) -> Optional[str]:
    """Extrait la saison FFVB (YYYY/YYYY) d'un match."""
    saison_raw = getattr(match, "saison", None)
    if isinstance(saison_raw, dict):
        code = saison_raw.get("code")
    elif hasattr(saison_raw, "code"):
        code = saison_raw.code
    elif isinstance(saison_raw, str):
        code = saison_raw
    elif isinstance(match, dict):
        code = match.get("saison")
    else:
        code = None
    if code:
        return str(code).replace("-", "/")
    return None


def _resolve_match_entite_code(match: Any) -> Optional[str]:
    """Extrait le code entité (comité/ligue/ACJEUNES) lié à un match."""
    if not match:
        return None
    # 1. Directement sur poule
    poule = getattr(match, "poule", None)
    if isinstance(poule, dict):
        if poule.get("entite_code"):
            return poule["entite_code"]
    elif poule is not None:
        if getattr(poule, "entite_code", None):
            return poule.entite_code
        comp = getattr(poule, "competition", None)
        if comp:
            entite = getattr(comp, "entite", None)
            if hasattr(entite, "code") and entite.code:
                return entite.code
            if getattr(comp, "entite_code", None):
                return comp.entite_code

    # 2. Directement sur competition
    comp = getattr(match, "competition", None)
    if isinstance(comp, dict):
        if comp.get("entite_code"):
            return comp["entite_code"]
    elif comp is not None:
        entite = getattr(comp, "entite", None)
        if hasattr(entite, "code") and entite.code:
            return entite.code
        if getattr(comp, "entite_code", None):
            return comp.entite_code

    if isinstance(match, dict):
        return match.get("entite_code")

    return None


def ffvb_fdme_url(match: Any) -> Optional[str]:
    """Génère l'URL de la feuille de match officielle (FDME) FFVB."""
    if not match:
        return None
    # URL déjà présente en base
    url_fdme = getattr(match, "url_fdme", None)
    if not url_fdme and isinstance(match, dict):
        url_fdme = match.get("url_fdme")
    if url_fdme and isinstance(url_fdme, str) and url_fdme.startswith("http"):
        return url_fdme

    code_match = getattr(match, "code_match", None)
    if not code_match and isinstance(match, dict):
        code_match = match.get("code_match")
    if not code_match:
        return None

    entite_code = _resolve_match_entite_code(match)
    saison = _resolve_match_saison(match)
    if entite_code and saison:
        return build_feuille_match_url(settings.ffvb_base_url, entite_code, str(code_match), saison)
    return None


def _resolve_poule_context(target: Any) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Résout (poule_code, entite_code, saison) depuis une poule ou un match."""
    if not target:
        return None, None, None

    # Si c'est un match, récupérer sa poule
    poule = getattr(target, "poule", None)
    if poule is not None:
        poule_code = getattr(poule, "code", None) or (poule.get("code") if isinstance(poule, dict) else None)
        entite_code = _resolve_match_entite_code(target)
        saison = _resolve_match_saison(target)
        return poule_code, entite_code, saison

    # Sinon c'est directement une poule
    poule_code = getattr(target, "code", None) or (target.get("code") if isinstance(target, dict) else None)
    entite_code = getattr(target, "entite_code", None)
    comp = getattr(target, "competition", None)
    if not entite_code and comp:
        entite = getattr(comp, "entite", None)
        if hasattr(entite, "code") and entite.code:
            entite_code = entite.code
        elif getattr(comp, "entite_code", None):
            entite_code = comp.entite_code

    saison = getattr(target, "saison", None)
    if not saison and comp:
        comp_saison = getattr(comp, "saison", None)
        if hasattr(comp_saison, "code"):
            saison = comp_saison.code
        elif isinstance(comp_saison, str):
            saison = comp_saison
    if saison:
        if hasattr(saison, "code"):
            saison = saison.code
        saison = str(saison).replace("-", "/")

    return poule_code, entite_code, saison


def ffvb_poule_calendrier_url(target: Any) -> Optional[str]:
    """Génère l'URL du calendrier officiel FFVB pour une poule (ou un match)."""
    if not target:
        return None
    url_existante = getattr(target, "url_calendrier", None)
    if url_existante and isinstance(url_existante, str) and url_existante.startswith("http"):
        return url_existante

    poule_code, entite_code, saison = _resolve_poule_context(target)
    if poule_code and entite_code and saison:
        return build_competition_calendar_url(settings.ffvb_base_url, entite_code, saison, poule_code)
    return None


def ffvb_poule_classement_url(target: Any) -> Optional[str]:
    """Génère l'URL du classement officiel FFVB pour une poule (ou un match)."""
    if not target:
        return None
    url_existante = getattr(target, "url_classement", None)
    if url_existante and isinstance(url_existante, str) and url_existante.startswith("http"):
        return url_existante

    poule_code, entite_code, saison = _resolve_poule_context(target)
    if poule_code and entite_code and saison:
        return build_classement_url(settings.ffvb_base_url, entite_code, saison, poule_code)
    return None


def ffvb_poule_export_csv_url(target: Any) -> Optional[str]:
    """Génère l'URL de l'export CSV officiel FFVB utilisé par le scraper PyVolley."""
    if not target:
        return None
    url_existante = getattr(target, "url_export_csv", None)
    if url_existante and isinstance(url_existante, str) and url_existante.startswith("http"):
        return url_existante

    poule_code, entite_code, saison = _resolve_poule_context(target)
    if poule_code and entite_code and saison:
        return build_export_url(settings.ffvb_base_url, entite_code, saison, poule=poule_code)
    return None


def ffvb_entite_home_url(entite_code: Optional[str], saison: Optional[str] = None) -> Optional[str]:
    """Génère l'URL d'accueil FFVB pour une entité (comité/ligue/fédération)."""
    if not entite_code:
        return None
    saison_fmt = (saison or "2024/2025").replace("-", "/")
    return build_home_url(settings.ffvb_base_url, entite_code, saison_fmt)


def ffvb_annuaire_url(target: Any = None) -> str:
    """Retourne l'URL de l'annuaire fédéral officiel de la FFVB (générique ou pour un club spécifique)."""
    base_url = build_annuaire_url(settings.ffvb_base_url)
    if target:
        code_ffvb = _extract_canonical_val(target, "code_ffvb", "code", "numero_affiliation")
        if code_ffvb:
            return f"{base_url}?num_affil={code_ffvb}"
    return base_url


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
templates.env.globals["ffvb_fdme_url"] = ffvb_fdme_url
templates.env.globals["ffvb_poule_calendrier_url"] = ffvb_poule_calendrier_url
templates.env.globals["ffvb_poule_classement_url"] = ffvb_poule_classement_url
templates.env.globals["ffvb_poule_export_csv_url"] = ffvb_poule_export_csv_url
templates.env.globals["ffvb_entite_home_url"] = ffvb_entite_home_url
templates.env.globals["ffvb_annuaire_url"] = ffvb_annuaire_url
