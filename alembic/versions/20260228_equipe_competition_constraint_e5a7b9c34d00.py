"""Change equipe unique constraint to include competition_id.

Teams with the same name but in different competitions (e.g., same club
in SENIOR vs M18) should be treated as distinct entities.

Revision ID: e5a7b9c34d00
Revises: d4e6f8a23b00
Create Date: 2026-02-28
"""

from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a7b9c34d00"
down_revision: Union[str, None] = "d4e6f8a23b00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite doesn't support DROP CONSTRAINT directly, use batch mode
    with op.batch_alter_table("equipes") as batch_op:
        batch_op.drop_constraint("uq_equipe_nom_saison", type_="unique")
        batch_op.create_unique_constraint(
            "uq_equipe_nom_saison_competition",
            ["nom", "saison_id", "competition_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("equipes") as batch_op:
        batch_op.drop_constraint("uq_equipe_nom_saison_competition", type_="unique")
        batch_op.create_unique_constraint(
            "uq_equipe_nom_saison",
            ["nom", "saison_id"],
        )
