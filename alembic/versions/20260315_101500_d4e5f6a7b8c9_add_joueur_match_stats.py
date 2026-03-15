"""
add_joueur_match_stats

Adds the joueur_match_stats table to persist detailed per-player,
per-match statistics computed from parsed match sheets. This prevents
expensive recomputation in web/API views and enables CLI backfilling.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-15 10:15:00+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "joueur_match_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("joueur_id", sa.Integer(), nullable=False),
        sa.Column("equipe_id", sa.Integer(), nullable=True),
        sa.Column("stats_data", sa.JSON(), nullable=False),
        sa.Column("match_updated_at", sa.DateTime(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["match_id"], ["matchs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["joueur_id"], ["joueurs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["equipe_id"], ["equipes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("match_id", "joueur_id", name="uq_joueur_match_stats"),
    )
    op.create_index(
        "ix_joueur_match_stats_match",
        "joueur_match_stats",
        ["match_id"],
        unique=False,
    )
    op.create_index(
        "ix_joueur_match_stats_joueur",
        "joueur_match_stats",
        ["joueur_id"],
        unique=False,
    )
    op.create_index(
        "ix_joueur_match_stats_match_updated",
        "joueur_match_stats",
        ["match_updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_joueur_match_stats_match_updated", table_name="joueur_match_stats")
    op.drop_index("ix_joueur_match_stats_joueur", table_name="joueur_match_stats")
    op.drop_index("ix_joueur_match_stats_match", table_name="joueur_match_stats")
    op.drop_table("joueur_match_stats")
