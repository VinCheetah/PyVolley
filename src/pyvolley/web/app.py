"""
Application web FastAPI — Factory et instance globale.

La configuration des templates (filtres, globals) est dans templateconfig.py.
Les routes sont dans le package web.routes/.
Les helpers métier sont dans web.helpers/.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from pyvolley.database.connection import init_db
from pyvolley.web.templateconfig import STATIC_DIR, templates

# Import templateconfig pour que les filtres/globals Jinja2 soient enregistrés
import pyvolley.web.templateconfig  # noqa: F401

logger = logging.getLogger(__name__)


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
        docs_url="/api/docs",
        redoc_url="/api/redoc",
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

    # ── Error handlers ───────────────────────────────────────────────
    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """Affiche la page d'erreur pour les erreurs HTTP (404, 405, etc.)."""
        # Laisser les requêtes API recevoir du JSON
        if request.url.path.startswith("/api/"):
            return HTMLResponse(
                content=f'{{"detail": "{exc.detail}"}}',
                status_code=exc.status_code,
                media_type="application/json",
            )
        messages = {
            404: "Page non trouvée — vérifiez l'URL.",
            405: "Méthode non autorisée.",
            403: "Accès interdit.",
        }
        message = messages.get(exc.status_code, str(exc.detail))
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": f"Erreur {exc.status_code} — {message}"},
            status_code=exc.status_code,
        )

    @application.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        """Affiche la page d'erreur pour les exceptions non gérées (500)."""
        logger.exception("Erreur interne sur %s: %s", request.url.path, exc)
        if request.url.path.startswith("/api/"):
            return HTMLResponse(
                content='{"detail": "Erreur interne du serveur"}',
                status_code=500,
                media_type="application/json",
            )
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": "Erreur interne du serveur — réessayez plus tard."},
            status_code=500,
        )

    return application


# Instance globale
web_app = create_web_app()

