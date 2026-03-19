"""
add_logo_url_to_clubs

Adds an optional persistent URL for club logos sourced externally.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-16 16:15:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("clubs")}

    if "logo_url" not in columns:
        with op.batch_alter_table("clubs", schema=None) as batch_op:
            batch_op.add_column(sa.Column("logo_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("clubs")}

    if "logo_url" in columns:
        with op.batch_alter_table("clubs", schema=None) as batch_op:
            batch_op.drop_column("logo_url")
