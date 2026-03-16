"""
empty message

Revision ID: 64082b6bde8b
Revises: a1b2c3d4e5f7, f6a7b8c9d0e1
Create Date: 2026-03-16 15:20:54.903336+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# Revision identifiers
revision: str = '64082b6bde8b'
down_revision: Union[str, None] = ('a1b2c3d4e5f7', 'f6a7b8c9d0e1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    pass


def downgrade() -> None:
    """Downgrade database schema."""
    pass
