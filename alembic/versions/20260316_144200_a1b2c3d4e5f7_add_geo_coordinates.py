"""
add_geo_coordinates

Adds latitude/longitude columns to clubs and salles_club tables
for the interactive map feature.

Revision ID: a1b2c3d4e5f7
Revises: e5f6a7b8c9d0
Create Date: 2026-03-16 14:42:00+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clubs", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("clubs", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("salles_club", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("salles_club", sa.Column("longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("salles_club", "longitude")
    op.drop_column("salles_club", "latitude")
    op.drop_column("clubs", "longitude")
    op.drop_column("clubs", "latitude")
