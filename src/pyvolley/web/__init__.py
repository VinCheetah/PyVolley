"""
Module Web - Interface utilisateur web pour PyVolley.

Utilise FastAPI + Jinja2 pour le rendu des templates.
"""

from pyvolley.web.app import create_web_app, web_app
from pyvolley.web.routes import web_router


__all__ = [
    "create_web_app",
    "web_app",
    "web_router",
]
