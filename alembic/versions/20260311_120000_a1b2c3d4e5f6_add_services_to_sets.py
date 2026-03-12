"""
add_services_to_sets

Stores service data (position → cumulative scores) from PDF parsing
directly in the sets table, so that detailed player statistics
(points_gagnes, nb_services, meilleure_serie, temps_morts_provoques)
can be computed from DB data without requiring the original PDF.

Revision ID: a1b2c3d4e5f6
Revises: b2c7d9a1f4ab
Create Date: 2026-03-11 12:00:00+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "b2c7d9a1f4ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sets", sa.Column("services_a", sa.JSON(), nullable=True))
    op.add_column("sets", sa.Column("services_b", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("sets", "services_b")
    op.drop_column("sets", "services_a")
