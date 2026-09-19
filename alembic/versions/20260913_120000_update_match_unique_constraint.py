"""update_match_unique_constraint

Fait évoluer la contrainte d'unicité de matchs de (code_match, saison_id)
vers (code_match, saison_id, competition_id) pour permettre aux entités distinctes
(ligues, comités) d'utiliser leurs propres codes sans écrasement mutuel.

Revision ID: c3e4g5i6k7m8
Revises: b2d3f4h5j6l7
Create Date: 2026-09-13 12:00:00+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "c3e4g5i6k7m8"
down_revision: Union[str, None] = "b2d3f4h5j6l7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("matchs") as batch_op:
        try:
            batch_op.drop_constraint("uq_match_code_saison", type_="unique")
        except Exception:
            pass
        batch_op.create_unique_constraint(
            "uq_match_code_saison_competition",
            ["code_match", "saison_id", "competition_id"],
        )
        batch_op.create_index(
            "ix_matchs_code_saison_comp",
            ["code_match", "saison_id", "competition_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("matchs") as batch_op:
        try:
            batch_op.drop_index("ix_matchs_code_saison_comp")
        except Exception:
            pass
        try:
            batch_op.drop_constraint("uq_match_code_saison_competition", type_="unique")
        except Exception:
            pass
        batch_op.create_unique_constraint(
            "uq_match_code_saison",
            ["code_match", "saison_id"],
        )
