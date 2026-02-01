"""
Application web FastAPI avec templates Jinja2.
"""

from pathlib import Path
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application web."""
    init_db()
    yield


def create_web_app() -> FastAPI:
    """Crée l'application web avec templates."""
    application = FastAPI(
        title="PyVolley",
        description="Application web pour la consultation des données volleyball FFVB",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,  # Désactiver Swagger pour le web
        redoc_url=None,
    )
    
    # Fichiers statiques
    if STATIC_DIR.exists():
        application.mount(
            "/static", 
            StaticFiles(directory=str(STATIC_DIR)), 
            name="static"
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
