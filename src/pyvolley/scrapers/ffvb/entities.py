"""
Découverte des entités FFVB (ligues, comités, compétitions nationales).
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from pyvolley.core.exceptions import ScrapingError
from pyvolley.scrapers.ffvb.models import EntityInfo, ScrapeContext

logger = logging.getLogger(__name__)

# Entités non listées dans le menu déroulant du site mais accessibles directement
HIDDEN_ENTITIES = [
    EntityInfo(code="AALNV", nom="Compétitions Professionnelles LNV", type="nationale"),
    EntityInfo(code="ACJEUNES", nom="Coupe de France Jeunes", type="nationale"),
]


def get_entities(ctx: ScrapeContext) -> list[EntityInfo]:
    """
    Récupère la liste de toutes les entités depuis planning_volley.php.
    """
    url = urljoin(ctx.base_url, "planning_volley.php")
    soup = ctx.client.get_soup(url)

    entities: list[EntityInfo] = []
    select = soup.find("select", {"name": "sel_entites"})

    if not select:
        raise ScrapingError("Select 'sel_entites' non trouvé sur la page")

    for option in select.find_all("option"):
        code = option.get("value", "").strip()
        nom = option.text.strip()

        if not code or code == "0" or code.startswith("-"):
            continue

        entity_type = detect_entity_type(code, nom)
        entities.append(EntityInfo(code=code, nom=nom, type=entity_type))

    # Ajouter les entités cachées
    existing_codes = {e.code for e in entities}
    for hidden in HIDDEN_ENTITIES:
        if hidden.code not in existing_codes:
            entities.append(hidden)

    return entities


def detect_entity_type(code: str, nom: str) -> str:
    """Détecte le type d'entité depuis le code et le nom."""
    nom_lower = nom.lower()

    if code.startswith("A") or "nationale" in nom_lower:
        return "nationale"
    if code.startswith("LI") or "ligue" in nom_lower:
        return "ligue"
    if code.startswith("PT") or "comité" in nom_lower or code.startswith("CD"):
        return "comite"
    return "autre"
