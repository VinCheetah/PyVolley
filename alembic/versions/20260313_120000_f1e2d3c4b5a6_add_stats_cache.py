"""
add_stats_cache

Adds the stats_cache table to store pre-computed palmarès statistics
keyed by filter combinations (saison, genre, categorie, niveau, departement).
This allows the /palmares web route to serve results instantly from the
database instead of recomputing all 16+ aggregation queries on every request.

Revision ID: f1e2d3c4b5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-03-13 12:00:00+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "f1e2d3c4b5a6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "stats_cache" not in table_names:
        op.create_table(
            "stats_cache",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("filter_key", sa.String(length=500), nullable=False),
            sa.Column("stats_data", sa.JSON(), nullable=False),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
            sa.Column("match_count", sa.Integer(), nullable=False, server_default="0"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("filter_key", name="uq_stats_cache_filter_key"),
        )

    indexes = {index["name"] for index in inspector.get_indexes("stats_cache")}
    if "ix_stats_cache_computed_at" not in indexes:
        op.create_index("ix_stats_cache_computed_at", "stats_cache", ["computed_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "stats_cache" in table_names:
        indexes = {index["name"] for index in inspector.get_indexes("stats_cache")}
        if "ix_stats_cache_computed_at" in indexes:
            op.drop_index("ix_stats_cache_computed_at", table_name="stats_cache")
        op.drop_table("stats_cache")
