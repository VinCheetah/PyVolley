"""add_missing_player_stats_columns

Ajoute les colonnes de statistiques détaillées pour les joueurs
dans la table joueur_match_stats :
- sets_gagnes, sets_perdus, sets_commences, sets_termines
- titulaire_set_1, match_complet, match_non_joue
- presence_relative
- nb_entrees_sorties, nb_sorties_entrees
- plus_minus, differentiel_points_gagnes, sideout_win_rate
- max_services_set
- stats_rotations, stats_clutch

Revision ID: d4f5h6j7l8n9
Revises: c3e4g5i6k7m8
Create Date: 2026-09-13 14:00:00+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "d4f5h6j7l8n9"
down_revision: Union[str, None] = "c3e4g5i6k7m8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("joueur_match_stats") as batch_op:
        batch_op.add_column(
            sa.Column("sets_gagnes", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("sets_perdus", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("sets_commences", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("sets_termines", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("titulaire_set_1", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("match_complet", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("match_non_joue", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("presence_relative", sa.Float(), nullable=False, server_default=sa.text("0.0"))
        )
        batch_op.add_column(
            sa.Column("nb_entrees_sorties", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("nb_sorties_entrees", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("plus_minus", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("differentiel_points_gagnes", sa.Float(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("sideout_win_rate", sa.Float(), nullable=False, server_default=sa.text("0.0"))
        )
        batch_op.add_column(
            sa.Column("max_services_set", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("stats_rotations", sa.JSON(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("stats_clutch", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("joueur_match_stats") as batch_op:
        batch_op.drop_column("stats_clutch")
        batch_op.drop_column("stats_rotations")
        batch_op.drop_column("max_services_set")
        batch_op.drop_column("sideout_win_rate")
        batch_op.drop_column("differentiel_points_gagnes")
        batch_op.drop_column("plus_minus")
        batch_op.drop_column("nb_sorties_entrees")
        batch_op.drop_column("nb_entrees_sorties")
        batch_op.drop_column("presence_relative")
        batch_op.drop_column("match_non_joue")
        batch_op.drop_column("match_complet")
        batch_op.drop_column("titulaire_set_1")
        batch_op.drop_column("sets_termines")
        batch_op.drop_column("sets_commences")
        batch_op.drop_column("sets_perdus")
        batch_op.drop_column("sets_gagnes")
