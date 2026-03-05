"""
Add niveau, division, competition_id fields to equipes table.
Add index on competition_id for equipes.

Revision ID: d4e6f8a23b00
Revises: c3b5e7f12a00
Create Date: 2026-02-22
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "d4e6f8a23b00"
down_revision: Union[str, None] = "c3b5e7f12a00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add niveau, division, competition_id to equipes table."""

    # ── 1. Nouvelles colonnes ──────────────────────────────────────
    op.add_column(
        "equipes",
        sa.Column("niveau", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "equipes",
        sa.Column("division", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "equipes",
        sa.Column(
            "competition_id",
            sa.Integer(),
            sa.ForeignKey("competitions.id"),
            nullable=True,
        ),
    )

    # ── 2. Index ───────────────────────────────────────────────────
    op.create_index(
        "ix_equipes_competition",
        "equipes",
        ["competition_id"],
    )


def downgrade() -> None:
    """Remove niveau, division, competition_id from equipes."""
    op.drop_index("ix_equipes_competition", table_name="equipes")
    op.drop_column("equipes", "competition_id")
    op.drop_column("equipes", "division")
    op.drop_column("equipes", "niveau")
