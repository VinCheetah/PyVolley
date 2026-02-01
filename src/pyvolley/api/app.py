"""
Configuration de l'application FastAPI.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pyvolley.core.config import settings
from pyvolley.database.connection import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application."""
    # Startup
    init_db()
    yield
    # Shutdown


def create_app() -> FastAPI:
    """Crée et configure l'application FastAPI."""
    application = FastAPI(
        title="PyVolley API",
        description="API pour la gestion des données de volleyball FFVB",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    
    # CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # À restreindre en production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Routes
    from pyvolley.api.routes import router
    application.include_router(router, prefix="/api")
    
    return application


# Instance globale
app = create_app()
