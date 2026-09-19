"""scope_competition_unique_constraint_by_entity

Fait évoluer la contrainte d'unicité de competitions de (nom, saison_id, genre, categorie)
vers (nom, saison_id, genre, categorie, entite_id) pour permettre aux entités distinctes
(ligues, comités) d'héberger leurs propres compétitions homonymes sans collision.

Revision ID: e5g6i7k8m9o0
Revises: d4f5h6j7l8n9
Create Date: 2026-09-15 12:00:00+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "e5g6i7k8m9o0"
down_revision: Union[str, None] = "d4f5h6j7l8n9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("competitions") as batch_op:
        try:
            batch_op.drop_constraint("uq_competition_nom_saison_genre_cat", type_="unique")
        except Exception:
            pass
        batch_op.create_unique_constraint(
            "uq_competition_nom_saison_genre_cat_entite",
            ["nom", "saison_id", "genre", "categorie", "entite_id"],
        )
        batch_op.create_index(
            "ix_competitions_entite_saison",
            ["entite_id", "saison_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("competitions") as batch_op:
        try:
            batch_op.drop_index("ix_competitions_entite_saison")
        except Exception:
            pass
        try:
            batch_op.drop_constraint("uq_competition_nom_saison_genre_cat_entite", type_="unique")
        except Exception:
            pass
        batch_op.create_unique_constraint(
            "uq_competition_nom_saison_genre_cat",
            ["nom", "saison_id", "genre", "categorie"],
        )
