"""
Application web FastAPI avec templates Jinja2.
"""

from pathlib import Path
from contextlib import asynccontextmanager
from datetime import date as dt_date

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
