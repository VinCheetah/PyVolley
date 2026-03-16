"""
Routes API — Agrégation de tous les sous-routeurs.

Chaque domaine métier a son propre module de routes.
"""

from fastapi import APIRouter

from pyvolley.api.routes.health import router as health_router
from pyvolley.api.routes.search import router as search_router
from pyvolley.api.routes.joueurs import router as joueurs_router
from pyvolley.api.routes.clubs import router as clubs_router
from pyvolley.api.routes.equipes import router as equipes_router
from pyvolley.api.routes.matchs import router as matchs_router
from pyvolley.api.routes.arbitres import router as arbitres_router
from pyvolley.api.routes.saisons import router as saisons_router
from pyvolley.api.routes.competitions import router as competitions_router
from pyvolley.api.routes.stats import router as stats_router
from pyvolley.api.routes.map import router as map_router

router = APIRouter()

router.include_router(health_router)
router.include_router(search_router)
router.include_router(joueurs_router)
router.include_router(clubs_router)
router.include_router(equipes_router)
router.include_router(matchs_router)
router.include_router(arbitres_router)
router.include_router(saisons_router)
router.include_router(competitions_router)
router.include_router(stats_router)
router.include_router(map_router)

__all__ = ["router"]
