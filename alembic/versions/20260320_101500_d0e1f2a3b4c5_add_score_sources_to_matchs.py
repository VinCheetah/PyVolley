"""
add_score_sources_to_matchs

Store export and PDF scores separately on matchs.

Revision ID: d0e1f2a3b4c5
Revises: b8c9d0e1f2a3
Create Date: 2026-03-20 10:15:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("matchs")}

    with op.batch_alter_table("matchs", schema=None) as batch_op:
        if "score_export" not in columns:
            batch_op.add_column(sa.Column("score_export", sa.String(length=10), nullable=True))
        if "score_pdf" not in columns:
            batch_op.add_column(sa.Column("score_pdf", sa.String(length=10), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("matchs")}

    with op.batch_alter_table("matchs", schema=None) as batch_op:
        if "score_pdf" in columns:
            batch_op.drop_column("score_pdf")
        if "score_export" in columns:
            batch_op.drop_column("score_export")
