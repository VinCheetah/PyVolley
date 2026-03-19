"""merge_heads_after_url_cleanup

Revision ID: b8c9d0e1f2a3
Revises: 64082b6bde8b, a7b8c9d0e1f2
Create Date: 2026-03-19 19:35:00+00:00
"""

from typing import Sequence, Union


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, tuple[str, str], None] = ("64082b6bde8b", "a7b8c9d0e1f2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge revision - no schema change."""
    pass


def downgrade() -> None:
    """Unmerge revision - no schema change."""
    pass
