"""
add_tour_to_poules

Revision ID: 10b6e92d44fe
Revises: 58b3c6e27025
Create Date: 2026-03-10 11:02:15.385425+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# Revision identifiers
revision: str = '10b6e92d44fe'
down_revision: Union[str, None] = '58b3c6e27025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("poules")}
    existing_indexes = {index["name"] for index in inspector.get_indexes("poules")}

    with op.batch_alter_table("poules", schema=None) as batch_op:
        if "tour" not in existing_columns:
            batch_op.add_column(sa.Column("tour", sa.Integer(), nullable=True))
        if "ix_poules_tour" not in existing_indexes:
            batch_op.create_index("ix_poules_tour", ["competition_id", "tour"], unique=False)


def downgrade() -> None:
    """Downgrade database schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("poules")}
    existing_indexes = {index["name"] for index in inspector.get_indexes("poules")}

    with op.batch_alter_table("poules", schema=None) as batch_op:
        if "ix_poules_tour" in existing_indexes:
            batch_op.drop_index("ix_poules_tour")
        if "tour" in existing_columns:
            batch_op.drop_column("tour")
