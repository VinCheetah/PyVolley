"""
initial_schema_v4

Revision ID: 58b3c6e27025
Revises: 
Create Date: 2026-03-06 15:54:03.379054+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from src.pyvolley.database.models import Base


# Revision identifiers
revision: str = '58b3c6e27025'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Downgrade database schema."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
