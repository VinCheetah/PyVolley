"""
Application web FastAPI — Factory et instance globale.

La configuration des templates (filtres, globals) est dans templateconfig.py.
Les routes sont dans le package web.routes/.
Les helpers métier sont dans web.helpers/.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from pyvolley.database.connection import init_db
from pyvolley.web.templateconfig import STATIC_DIR

# Import templateconfig pour que les filtres/globals Jinja2 soient enregistrés
import pyvolley.web.templateconfig  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application."""
    init_db()
    yield


def create_web_app() -> FastAPI:
    """Crée l'application web avec templates et API."""
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
