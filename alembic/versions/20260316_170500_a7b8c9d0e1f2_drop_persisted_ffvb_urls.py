"""
drop_persisted_ffvb_urls

Remove FFVB URL columns that are now reconstructed at runtime in the web layer.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-16 17:05:00+00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("clubs", "url_planning")
    op.drop_column("clubs", "url_classement")
    op.drop_column("competitions", "url_calendrier")
    op.drop_column("competitions", "url_classement")
    op.drop_column("poules", "url_calendrier")
    op.drop_column("poules", "url_classement")
    op.drop_column("entites_ffvb", "url_calendrier")


def downgrade() -> None:
    import sqlalchemy as sa

    op.add_column("entites_ffvb", sa.Column("url_calendrier", sa.String(length=500), nullable=True))
    op.add_column("poules", sa.Column("url_classement", sa.String(length=500), nullable=True))
    op.add_column("poules", sa.Column("url_calendrier", sa.String(length=500), nullable=True))
    op.add_column("competitions", sa.Column("url_classement", sa.String(length=500), nullable=True))
    op.add_column("competitions", sa.Column("url_calendrier", sa.String(length=500), nullable=True))
    op.add_column("clubs", sa.Column("url_classement", sa.String(length=500), nullable=True))
    op.add_column("clubs", sa.Column("url_planning", sa.String(length=500), nullable=True))
