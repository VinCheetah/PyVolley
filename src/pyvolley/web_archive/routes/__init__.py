"""
Routes web — Agrégation de tous les sous-routeurs.

Chaque domaine métier a son propre module de routes.
"""

from fastapi import APIRouter

from pyvolley.web.routes.dashboard import router as dashboard_router
from pyvolley.web.routes.search import router as search_router
from pyvolley.web.routes.joueurs import router as joueurs_router
from pyvolley.web.routes.equipes import router as equipes_router
from pyvolley.web.routes.clubs import router as clubs_router
from pyvolley.web.routes.matchs import router as matchs_router
from pyvolley.web.routes.arbitres import router as arbitres_router
from pyvolley.web.routes.competitions import router as competitions_router
from pyvolley.web.routes.poules import router as poules_router
from pyvolley.web.routes.statistiques import router as statistiques_router
from pyvolley.web.routes.entraineurs import router as entraineurs_router

web_router = APIRouter()

web_router.include_router(dashboard_router)
web_router.include_router(search_router)
web_router.include_router(joueurs_router)
web_router.include_router(equipes_router)
web_router.include_router(clubs_router)
web_router.include_router(matchs_router)
web_router.include_router(arbitres_router)
web_router.include_router(entraineurs_router)
web_router.include_router(competitions_router)
web_router.include_router(poules_router)
web_router.include_router(statistiques_router)

__all__ = ["web_router"]
