"""
Add match_joue, has_details, score_source fields to matchs table.
Add indexes for score completion queries.

Revision ID: c3b5e7f12a00
Revises: a2f4c8d91e00
Create Date: 2026-02-14
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "c3b5e7f12a00"
down_revision: Union[str, None] = "a2f4c8d91e00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add match status columns and indexes."""

    # ── 1. Nouvelles colonnes ──────────────────────────────────────
    op.add_column(
        "matchs",
        sa.Column("match_joue", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "matchs",
        sa.Column("has_details", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "matchs",
        sa.Column("score_source", sa.String(length=20), nullable=True),
    )

    # ── 2. Indexes ─────────────────────────────────────────────────
    op.create_index(
        "ix_matchs_has_details",
        "matchs",
        ["has_details", "saison_id"],
    )

    # Partial unique index: empêche les doublons code_match quand
    # saison_id IS NULL (la contrainte UNIQUE standard ne protège pas
    # les NULL en SQL).
    # SQLite supporte WHERE dans CREATE INDEX depuis 3.15.0.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_matchs_code_no_saison "
        "ON matchs (code_match) WHERE saison_id IS NULL"
    )

    # ── 3. Remplir les valeurs pour les matchs existants ───────────
    # Matchs qui ont un vainqueur ou des sets > 0 → joués avec détails
    op.execute(
        "UPDATE matchs SET match_joue = 1, has_details = 1, score_source = 'pdf' "
        "WHERE vainqueur IS NOT NULL OR sets_equipe_a > 0"
    )


def downgrade() -> None:
    """Remove match status columns and indexes."""

    # Drop indexes
    op.execute("DROP INDEX IF EXISTS ix_matchs_code_no_saison")
    op.drop_index("ix_matchs_has_details", table_name="matchs")

    # Drop columns
    op.drop_column("matchs", "score_source")
    op.drop_column("matchs", "has_details")
    op.drop_column("matchs", "match_joue")
