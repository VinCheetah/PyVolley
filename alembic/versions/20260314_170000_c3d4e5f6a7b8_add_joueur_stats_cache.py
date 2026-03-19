"""
add_joueur_stats_cache

Adds the joueur_stats_cache table to store pre-computed per-player
performance statistics. This accelerates the player detail page by
avoiding re-computation of match analysis on every page load.

Revision ID: c3d4e5f6a7b8
Revises: f1e2d3c4b5a6
Create Date: 2026-03-14 17:00:00+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "f1e2d3c4b5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "joueur_stats_cache" not in table_names:
        op.create_table(
            "joueur_stats_cache",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("joueur_id", sa.Integer(), nullable=False),
            sa.Column("aggregated_stats", sa.JSON(), nullable=True),
            sa.Column("per_match_stats", sa.JSON(), nullable=True),
            sa.Column("match_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["joueur_id"], ["joueurs.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("joueur_id", name="uq_joueur_stats_cache_joueur_id"),
        )

    indexes = {index["name"] for index in inspector.get_indexes("joueur_stats_cache")}
    if "ix_joueur_stats_cache_joueur_id" not in indexes:
        op.create_index(
            "ix_joueur_stats_cache_joueur_id", "joueur_stats_cache", ["joueur_id"], unique=True
        )
    if "ix_joueur_stats_cache_computed_at" not in indexes:
        op.create_index(
            "ix_joueur_stats_cache_computed_at", "joueur_stats_cache", ["computed_at"], unique=False
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "joueur_stats_cache" in table_names:
        indexes = {index["name"] for index in inspector.get_indexes("joueur_stats_cache")}
        if "ix_joueur_stats_cache_computed_at" in indexes:
            op.drop_index("ix_joueur_stats_cache_computed_at", table_name="joueur_stats_cache")
        if "ix_joueur_stats_cache_joueur_id" in indexes:
            op.drop_index("ix_joueur_stats_cache_joueur_id", table_name="joueur_stats_cache")
        op.drop_table("joueur_stats_cache")
