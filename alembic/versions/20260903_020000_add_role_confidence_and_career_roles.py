"""
add_role_confidence_and_career_roles

Ajoute role_confiance et role_distribution à stats_joueur_saison,
et role_principal, role_confiance, roles_frequence, role_distribution à stats_joueur_carriere.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-09-03 02:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def col_names(tbl: str) -> set[str]:
        if tbl in inspector.get_table_names():
            return {c["name"] for c in inspector.get_columns(tbl)}
        return set()

    # 1. stats_joueur_saison
    if "stats_joueur_saison" in inspector.get_table_names():
        sjs_cols = col_names("stats_joueur_saison")
        with op.batch_alter_table("stats_joueur_saison") as batch_op:
            if "role_confiance" not in sjs_cols:
                batch_op.add_column(sa.Column("role_confiance", sa.Float(), server_default="0.0", nullable=False))
            if "role_distribution" not in sjs_cols:
                batch_op.add_column(sa.Column("role_distribution", sa.JSON(), nullable=True))

    # 2. stats_joueur_carriere
    if "stats_joueur_carriere" in inspector.get_table_names():
        sjc_cols = col_names("stats_joueur_carriere")
        with op.batch_alter_table("stats_joueur_carriere") as batch_op:
            if "role_principal" not in sjc_cols:
                batch_op.add_column(sa.Column("role_principal", sa.String(30), nullable=True))
            if "role_confiance" not in sjc_cols:
                batch_op.add_column(sa.Column("role_confiance", sa.Float(), server_default="0.0", nullable=False))
            if "roles_frequence" not in sjc_cols:
                batch_op.add_column(sa.Column("roles_frequence", sa.JSON(), nullable=True))
            if "role_distribution" not in sjc_cols:
                batch_op.add_column(sa.Column("role_distribution", sa.JSON(), nullable=True))

        # Index sur role_principal
        existing_indexes = {ix["name"] for ix in inspector.get_indexes("stats_joueur_carriere")}
        if "ix_sjc_role_principal" not in existing_indexes:
            with op.batch_alter_table("stats_joueur_carriere") as batch_op:
                batch_op.create_index("ix_sjc_role_principal", ["role_principal"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def col_names(tbl: str) -> set[str]:
        if tbl in inspector.get_table_names():
            return {c["name"] for c in inspector.get_columns(tbl)}
        return set()

    if "stats_joueur_carriere" in inspector.get_table_names():
        existing_indexes = {ix["name"] for ix in inspector.get_indexes("stats_joueur_carriere")}
        if "ix_sjc_role_principal" in existing_indexes:
            with op.batch_alter_table("stats_joueur_carriere") as batch_op:
                batch_op.drop_index("ix_sjc_role_principal")

        sjc_cols = col_names("stats_joueur_carriere")
        with op.batch_alter_table("stats_joueur_carriere") as batch_op:
            for col in ("role_distribution", "roles_frequence", "role_confiance", "role_principal"):
                if col in sjc_cols:
                    batch_op.drop_column(col)

    if "stats_joueur_saison" in inspector.get_table_names():
        sjs_cols = col_names("stats_joueur_saison")
        with op.batch_alter_table("stats_joueur_saison") as batch_op:
            for col in ("role_distribution", "role_confiance"):
                if col in sjs_cols:
                    batch_op.drop_column(col)
