"""
Utilitaire de bulk upsert (INSERT ... ON CONFLICT DO UPDATE) multi-dialectes pour SQLAlchemy 2.0.

Supporte nativement SQLite (développement) et PostgreSQL (production), avec découpage
automatique en lots pour respecter les limites de paramètres de requête.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence, Type

from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)


def bulk_upsert(
    session: Session,
    model: Type[Any],
    records: Sequence[dict[str, Any]],
    *,
    index_elements: Sequence[str],
    update_columns: Sequence[str] | None = None,
    batch_size: int = 1000,
) -> int:
    """Insère ou met à jour une liste de dictionnaires en base de données par lots.

    Args:
        session: Session SQLAlchemy active.
        model: Classe de modèle SQLAlchemy DeclarativeBase.
        records: Liste de dictionnaires contenant les données à insérer/mettre à jour.
        index_elements: Liste des noms de colonnes constituant la contrainte d'unicité / index unique.
        update_columns: Liste des noms de colonnes à mettre à jour en cas de conflit.
                        Si None, toutes les colonnes présentes sauf l'id et les index_elements.
        batch_size: Taille maximale du lot d'insertion (ajustée dynamiquement pour SQLite).

    Returns:
        Nombre total d'enregistrements traités.
    """
    if not records:
        return 0

    dialect_name = session.bind.dialect.name if session.bind else "sqlite"
    index_set = set(index_elements)

    # Déterminer les colonnes à mettre à jour
    sample_keys = records[0].keys()
    if update_columns is None:
        target_update_cols = [
            k for k in sample_keys
            if k not in index_set and k != "id"
        ]
    else:
        target_update_cols = [c for c in update_columns if c not in index_set and c != "id"]

    # Calcul de la taille de chunk sécurisée pour SQLite
    cols_count = max(1, len(sample_keys))
    if dialect_name == "sqlite":
        # SQLite a une limite de 999 variables par défaut (32766 à partir de SQLite 3.32.0).
        # Une marge à 900 garantit 100% de compatibilité quel que soit l'environnement.
        safe_batch_size = max(1, min(batch_size, 900 // cols_count))
    else:
        safe_batch_size = batch_size

    total_processed = 0

    for i in range(0, len(records), safe_batch_size):
        chunk = list(records[i : i + safe_batch_size])
        if not chunk:
            continue

        if dialect_name == "sqlite":
            stmt = sqlite_insert(model).values(chunk)
            if target_update_cols:
                set_dict = {col: getattr(stmt.excluded, col) for col in target_update_cols}
                stmt = stmt.on_conflict_do_update(
                    index_elements=list(index_elements),
                    set_=set_dict,
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=list(index_elements))
            session.execute(stmt)

        elif dialect_name == "postgresql":
            stmt = pg_insert(model).values(chunk)
            if target_update_cols:
                set_dict = {col: getattr(stmt.excluded, col) for col in target_update_cols}
                stmt = stmt.on_conflict_do_update(
                    index_elements=list(index_elements),
                    set_=set_dict,
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=list(index_elements))
            session.execute(stmt)

        else:
            # Fallback générique par objet pour d'autres moteurs
            for row in chunk:
                instance = model(**row)
                session.merge(instance)

        total_processed += len(chunk)

    return total_processed
