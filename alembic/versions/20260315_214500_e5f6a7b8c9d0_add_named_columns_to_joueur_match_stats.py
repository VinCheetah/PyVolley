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
    op.add_column("joueur_match_stats", sa.Column("points_gagnes", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("joueur_match_stats", sa.Column("points_perdus", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("joueur_match_stats", sa.Column("points_joues", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("joueur_match_stats", sa.Column("points_gagnes_service", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("joueur_match_stats", sa.Column("services", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("joueur_match_stats", sa.Column("series", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("joueur_match_stats", sa.Column("max_serie", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("joueur_match_stats", sa.Column("moyenne_services_par_serie", sa.Float(), nullable=False, server_default="0"))
    op.add_column("joueur_match_stats", sa.Column("ratio_points_gagnes", sa.Float(), nullable=False, server_default="0"))

    op.create_index("ix_joueur_match_stats_services", "joueur_match_stats", ["services"], unique=False)
    op.create_index("ix_joueur_match_stats_points_gagnes", "joueur_match_stats", ["points_gagnes"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_joueur_match_stats_points_gagnes", table_name="joueur_match_stats")
    op.drop_index("ix_joueur_match_stats_services", table_name="joueur_match_stats")

    op.drop_column("joueur_match_stats", "ratio_points_gagnes")
    op.drop_column("joueur_match_stats", "moyenne_services_par_serie")
    op.drop_column("joueur_match_stats", "max_serie")
    op.drop_column("joueur_match_stats", "series")
    op.drop_column("joueur_match_stats", "services")
    op.drop_column("joueur_match_stats", "points_gagnes_service")
    op.drop_column("joueur_match_stats", "points_joues")
    op.drop_column("joueur_match_stats", "points_perdus")
    op.drop_column("joueur_match_stats", "points_gagnes")
