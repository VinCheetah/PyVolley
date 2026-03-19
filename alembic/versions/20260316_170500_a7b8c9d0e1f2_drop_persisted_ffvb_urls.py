"""
drop_persisted_ffvb_urls

Remove FFVB URL columns that are now reconstructed at runtime in the web layer.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-16 17:05:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _drop_if_exists(table_name: str, column_name: str) -> None:
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        if column_name in existing_columns:
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.drop_column(column_name)

    _drop_if_exists("clubs", "url_planning")
    _drop_if_exists("clubs", "url_classement")
    _drop_if_exists("competitions", "url_calendrier")
    _drop_if_exists("competitions", "url_classement")
    _drop_if_exists("poules", "url_calendrier")
    _drop_if_exists("poules", "url_classement")
    _drop_if_exists("entites_ffvb", "url_calendrier")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _add_if_missing(table_name: str, column: sa.Column) -> None:
        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        if column.name not in existing_columns:
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.add_column(column)

    _add_if_missing("entites_ffvb", sa.Column("url_calendrier", sa.String(length=500), nullable=True))
    _add_if_missing("poules", sa.Column("url_classement", sa.String(length=500), nullable=True))
    _add_if_missing("poules", sa.Column("url_calendrier", sa.String(length=500), nullable=True))
    _add_if_missing("competitions", sa.Column("url_classement", sa.String(length=500), nullable=True))
    _add_if_missing("competitions", sa.Column("url_calendrier", sa.String(length=500), nullable=True))
    _add_if_missing("clubs", sa.Column("url_classement", sa.String(length=500), nullable=True))
    _add_if_missing("clubs", sa.Column("url_planning", sa.String(length=500), nullable=True))
