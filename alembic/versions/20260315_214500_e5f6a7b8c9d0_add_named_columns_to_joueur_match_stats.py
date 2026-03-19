"""
add_named_columns_to_joueur_match_stats

Adds typed/statistically useful columns to joueur_match_stats while keeping
stats_data JSON for full detail payload.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-15 21:45:00+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("joueur_match_stats")}

    with op.batch_alter_table("joueur_match_stats", schema=None) as batch_op:
        if "points_gagnes" not in columns:
            batch_op.add_column(sa.Column("points_gagnes", sa.Integer(), nullable=False, server_default="0"))
        if "points_perdus" not in columns:
            batch_op.add_column(sa.Column("points_perdus", sa.Integer(), nullable=False, server_default="0"))
        if "points_joues" not in columns:
            batch_op.add_column(sa.Column("points_joues", sa.Integer(), nullable=False, server_default="0"))
        if "points_gagnes_service" not in columns:
            batch_op.add_column(sa.Column("points_gagnes_service", sa.Integer(), nullable=False, server_default="0"))
        if "services" not in columns:
            batch_op.add_column(sa.Column("services", sa.Integer(), nullable=False, server_default="0"))
        if "series" not in columns:
            batch_op.add_column(sa.Column("series", sa.Integer(), nullable=False, server_default="0"))
        if "max_serie" not in columns:
            batch_op.add_column(sa.Column("max_serie", sa.Integer(), nullable=False, server_default="0"))
        if "moyenne_services_par_serie" not in columns:
            batch_op.add_column(sa.Column("moyenne_services_par_serie", sa.Float(), nullable=False, server_default="0"))
        if "ratio_points_gagnes" not in columns:
            batch_op.add_column(sa.Column("ratio_points_gagnes", sa.Float(), nullable=False, server_default="0"))

    indexes = {index["name"] for index in inspector.get_indexes("joueur_match_stats")}
    if "ix_joueur_match_stats_services" not in indexes:
        op.create_index("ix_joueur_match_stats_services", "joueur_match_stats", ["services"], unique=False)
    if "ix_joueur_match_stats_points_gagnes" not in indexes:
        op.create_index("ix_joueur_match_stats_points_gagnes", "joueur_match_stats", ["points_gagnes"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("joueur_match_stats")}
    indexes = {index["name"] for index in inspector.get_indexes("joueur_match_stats")}

    if "ix_joueur_match_stats_points_gagnes" in indexes:
        op.drop_index("ix_joueur_match_stats_points_gagnes", table_name="joueur_match_stats")
    if "ix_joueur_match_stats_services" in indexes:
        op.drop_index("ix_joueur_match_stats_services", table_name="joueur_match_stats")

    with op.batch_alter_table("joueur_match_stats", schema=None) as batch_op:
        if "ratio_points_gagnes" in columns:
            batch_op.drop_column("ratio_points_gagnes")
        if "moyenne_services_par_serie" in columns:
            batch_op.drop_column("moyenne_services_par_serie")
        if "max_serie" in columns:
            batch_op.drop_column("max_serie")
        if "series" in columns:
            batch_op.drop_column("series")
        if "services" in columns:
            batch_op.drop_column("services")
        if "points_gagnes_service" in columns:
            batch_op.drop_column("points_gagnes_service")
        if "points_joues" in columns:
            batch_op.drop_column("points_joues")
        if "points_perdus" in columns:
            batch_op.drop_column("points_perdus")
        if "points_gagnes" in columns:
            batch_op.drop_column("points_gagnes")
