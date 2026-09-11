"""
add_type_forfait_to_matchs

Ajoute la colonne type_forfait à la table matchs.

Revision ID: b2d3f4h5j6l7
Revises: a1c2e3g4i5k6
Create Date: 2026-09-09 16:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2d3f4h5j6l7"
down_revision: Union[str, None] = "a1c2e3g4i5k6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("matchs")}

    if "type_forfait" not in existing_columns:
        op.add_column(
            "matchs",
            sa.Column("type_forfait", sa.String(length=20), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("matchs")}

    if "type_forfait" in existing_columns:
        with op.batch_alter_table("matchs") as batch_op:
            batch_op.drop_column("type_forfait")
