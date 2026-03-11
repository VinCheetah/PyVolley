"""
Application web FastAPI avec templates Jinja2.
"""

from pathlib import Path
from contextlib import asynccontextmanager
from datetime import date as dt_date
import re
import unicodedata

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pyvolley.database.connection import init_db


# Chemins
WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# Templates Jinja2
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# Custom Jinja2 filters
def format_date(value, fmt="%d/%m/%Y"):
    if value is None:
        return "-"
    if isinstance(value, dt_date):
        return value.strftime(fmt)
    return str(value)


def truncate_name(value, length=20):
    if value and len(value) > length:
        return value[:length] + "..."
    return value or "-"


templates.env.filters["format_date"] = format_date
templates.env.filters["truncate_name"] = truncate_name


def _normalize_level_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    without_accents = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", without_accents).strip().upper()


_RE_YOUTH = re.compile(r"\b(M13|M15|M17|M18|M20|M21|U13|U15|U17|U18|U20|U21|JEUNES?)\b")


def resolve_niveau_badge(
    niveau: str | None,
    competition_name: str | None = None,
    categorie: str | None = None,
    division: str | int | None = None,
) -> dict | None:
    parts = [p for p in [niveau, competition_name, categorie] if p]
    if not parts:
        return None

    full_text = _normalize_level_text(" ".join(parts))
    niveau_text = _normalize_level_text(niveau or "")
    division_text = str(division).strip() if division is not None else ""
    is_youth = bool(_RE_YOUTH.search(full_text))

    if "COUPE DE FRANCE" in full_text or re.search(r"\bCDF\b", full_text):
        return {"label": "CdF", "css_class": "badge-purple"}

    if re.search(r"\b(PRO\s*A|LIGUE\s*A|LAM|LAF)\b", full_text):
        return {"label": "Pro A", "css_class": "badge-red"}
    if re.search(r"\b(PRO\s*B|LIGUE\s*B|LBM|LBF)\b", full_text):
        return {"label": "Pro B", "css_class": "badge-blue"}
    if re.search(r"\bPRO\b", full_text):
        return {"label": "Pro", "css_class": "badge-blue"}

    if re.search(r"\bELITE\s*AVENIR\b", full_text) or (is_youth and re.search(r"\bELITE\b", full_text)):
        return {"label": "Elite Avenir", "css_class": "badge-purple"}
    if re.search(r"\bELITE\b", full_text):
        return {"label": "Elite", "css_class": "badge-gold"}

    if division_text in {"1", "2", "3"} and (
        niveau_text in {"NATIONAL", "NATIONALE"}
        or re.search(r"\bNATIONAL(?:E|AUX|ES?)?\b", full_text)
    ):
        return {"label": f"N{division_text}", "css_class": "badge-green"}

    if re.search(r"\bNATIONALE?\s*1\b|\bN1\b", full_text):
        return {"label": "N1", "css_class": "badge-gold"}
    if re.search(r"\bNATIONALE?\s*2\b|\bN2\b", full_text):
        return {"label": "N2", "css_class": "badge-green"}
    if re.search(r"\bNATIONALE?\s*3\b|\bN3\b", full_text):
        return {"label": "N3", "css_class": "badge-green"}

    if re.search(r"\b(PRE\s*-?\s*REG(?:IONAL(?:E)?)?|PRE_?REG(?:IONAL(?:E)?)?|PREREG(?:IONALE?)?)\b", full_text):
        return {"label": "Préreg", "css_class": "badge-blue"}
    if re.search(r"\b(PRE\s*-?\s*NAT(?:IONAL(?:E)?)?|PRE_?NAT(?:IONAL(?:E)?)?|PRENAT|PRENATIONALE?)\b", full_text):
        return {"label": "Prénat", "css_class": "badge-blue"}

    if re.search(r"\b(REGIONAL|REGIONALE?|R1|R2|R3|R4)\b", full_text):
        return {"label": "Régional", "css_class": "badge-green"}
    if re.search(r"\b(DEPARTEMENTAL|DEPARTEMENTALE?|DEP\.?|D1|D2|D3|D4)\b", full_text):
        return {"label": "Dép", "css_class": "badge-green"}
    if re.search(r"\b(LOISIR|LOISIRS|BRASSAGE|COMPETF?UN|COMPET\s*MOUV)\b", full_text):
        return {"label": "Loisir", "css_class": "badge-purple"}

    if niveau_text:
        return {"label": (niveau or "").strip(), "css_class": "badge-green"}
    return None

# Global template variables
templates.env.globals["now_date"] = lambda: dt_date.today().isoformat()
templates.env.globals["resolve_niveau_badge"] = resolve_niveau_badge


def path_for_entity(entity_type: str, entity_id: int | None, fallback: str = "#") -> str:
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
        "competition": f"/competitions/{entity_id}",
        "poule": f"/poules/{entity_id}",
    }
    return mapping.get(entity_type, fallback)


def competition_url_for_equipe(equipe, fallback: str = "#") -> str:
    if not equipe:
        return fallback

    competition = getattr(equipe, "competition", None)
    if competition is not None and getattr(competition, "id", None):
        return f"/competitions/{competition.id}"

    competition_id = getattr(equipe, "competition_id", None)
    if competition_id:
        return f"/competitions/{competition_id}"

    return fallback


templates.env.globals["path_for_entity"] = path_for_entity
templates.env.globals["competition_url_for_equipe"] = competition_url_for_equipe


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_web_app() -> FastAPI:
    """Crée l'application web avec templates."""
    application = FastAPI(
        title="PyVolley",
        description="Application web pour la consultation des données volleyball FFVB",
        version="2.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )

    # Créer le dossier static s'il n'existe pas
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    # Fichiers statiques
    application.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )

    # Routes web
    from pyvolley.web.routes import web_router
    application.include_router(web_router)

    # Routes API
    from pyvolley.api.routes import router as api_router
    application.include_router(api_router, prefix="/api")

    return application


# Instance globale
web_app = create_web_app()
