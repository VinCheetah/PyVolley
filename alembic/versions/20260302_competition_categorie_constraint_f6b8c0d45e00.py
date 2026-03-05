"""Add categorie to competition unique constraint.

Competitions are now uniquely identified by (nom, saison_id, genre, categorie)
to properly separate competitions of different age categories (e.g., SENIOR
vs M18) that may share the same name. Also adds an index on (genre, categorie)
for efficient filtering.

Revision ID: f6b8c0d45e00
Revises: e5a7b9c34d00
Create Date: 2026-03-02
"""

from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6b8c0d45e00"
down_revision: Union[str, None] = "e5a7b9c34d00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Update the unique constraint to include categorie
    with op.batch_alter_table("competitions") as batch_op:
        batch_op.drop_constraint("uq_competition_nom_saison_genre", type_="unique")
        batch_op.create_unique_constraint(
            "uq_competition_nom_saison_genre_cat",
            ["nom", "saison_id", "genre", "categorie"],
        )
        batch_op.create_index(
            "ix_competitions_genre_categorie",
            ["genre", "categorie"],
        )


def downgrade() -> None:
    with op.batch_alter_table("competitions") as batch_op:
        batch_op.drop_index("ix_competitions_genre_categorie")
        batch_op.drop_constraint("uq_competition_nom_saison_genre_cat", type_="unique")
        batch_op.create_unique_constraint(
            "uq_competition_nom_saison_genre",
            ["nom", "saison_id", "genre"],
        )
