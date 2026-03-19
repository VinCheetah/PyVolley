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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    club_columns = {column["name"] for column in inspector.get_columns("clubs")}
    salles_columns = {column["name"] for column in inspector.get_columns("salles_club")}

    with op.batch_alter_table("clubs", schema=None) as batch_op:
        if "latitude" not in club_columns:
            batch_op.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        if "longitude" not in club_columns:
            batch_op.add_column(sa.Column("longitude", sa.Float(), nullable=True))

    with op.batch_alter_table("salles_club", schema=None) as batch_op:
        if "latitude" not in salles_columns:
            batch_op.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        if "longitude" not in salles_columns:
            batch_op.add_column(sa.Column("longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    club_columns = {column["name"] for column in inspector.get_columns("clubs")}
    salles_columns = {column["name"] for column in inspector.get_columns("salles_club")}

    with op.batch_alter_table("salles_club", schema=None) as batch_op:
        if "longitude" in salles_columns:
            batch_op.drop_column("longitude")
        if "latitude" in salles_columns:
            batch_op.drop_column("latitude")

    with op.batch_alter_table("clubs", schema=None) as batch_op:
        if "longitude" in club_columns:
            batch_op.drop_column("longitude")
        if "latitude" in club_columns:
            batch_op.drop_column("latitude")
