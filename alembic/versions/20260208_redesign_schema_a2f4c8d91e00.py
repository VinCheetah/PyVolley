"""
Redesign schema: add formations, changements, timeouts, services tables;
clean up obsolete columns.

Revision ID: a2f4c8d91e00
Revises: b819250c7a7c
Create Date: 2026-02-08
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "a2f4c8d91e00"
down_revision: Union[str, None] = "b819250c7a7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade: add new tables, rename columns, drop obsolete columns."""

    # ── 1. Nouvelles tables ────────────────────────────────────────

    op.create_table(
        "formations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("equipe", sa.String(length=1), nullable=False),
        sa.Column("position_1", sa.String(length=2), nullable=True),
        sa.Column("position_2", sa.String(length=2), nullable=True),
        sa.Column("position_3", sa.String(length=2), nullable=True),
        sa.Column("position_4", sa.String(length=2), nullable=True),
        sa.Column("position_5", sa.String(length=2), nullable=True),
        sa.Column("position_6", sa.String(length=2), nullable=True),
        sa.ForeignKeyConstraint(["set_id"], ["sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("set_id", "equipe", name="uq_formation_set_equipe"),
    )

    op.create_table(
        "changements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("equipe", sa.String(length=1), nullable=False),
        sa.Column("joueur_entrant", sa.String(length=2), nullable=False),
        sa.Column("joueur_sortant", sa.String(length=2), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("score_a", sa.Integer(), nullable=True),
        sa.Column("score_b", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["set_id"], ["sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "timeouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("equipe", sa.String(length=1), nullable=False),
        sa.Column("score_a", sa.Integer(), nullable=False),
        sa.Column("score_b", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["set_id"], ["sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("equipe", sa.String(length=1), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("tour", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["set_id"], ["sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("services", schema=None) as batch_op:
        batch_op.create_index("ix_services_set_equipe", ["set_id", "equipe"])

    # ── 2. Modifier table sets ─────────────────────────────────────
    #    - Supprimer colonnes JSON (formation_a/b, timeouts_a/b)
    #    - Modifier type heure_debut/fin de String → Time

    with op.batch_alter_table("sets", schema=None) as batch_op:
        batch_op.drop_column("formation_a")
        batch_op.drop_column("formation_b")
        batch_op.drop_column("timeouts_a")
        batch_op.drop_column("timeouts_b")
        # Note: SQLite ne supporte pas ALTER COLUMN, batch mode gère cela
        batch_op.alter_column(
            "heure_debut",
            existing_type=sa.String(length=8),
            type_=sa.Time(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "heure_fin",
            existing_type=sa.String(length=8),
            type_=sa.Time(),
            existing_nullable=True,
        )

    # ── 3. Modifier table matchs ──────────────────────────────────
    #    - Renommer vainqueur_nom → vainqueur, score_final → score_sets
    #    - Supprimer vainqueur_id

    with op.batch_alter_table("matchs", schema=None) as batch_op:
        batch_op.alter_column("vainqueur_nom", new_column_name="vainqueur")
        batch_op.alter_column("score_final", new_column_name="score_sets")
        batch_op.drop_column("vainqueur_id")

    # ── 4. Modifier table joueurs ─────────────────────────────────
    #    - Supprimer colonnes obsolètes

    with op.batch_alter_table("joueurs", schema=None) as batch_op:
        batch_op.drop_column("date_naissance")
        batch_op.drop_column("nationalite")
        batch_op.drop_column("matchs_joues")
        batch_op.drop_column("sets_joues")

    # ── 5. Modifier table equipes ─────────────────────────────────

    with op.batch_alter_table("equipes", schema=None) as batch_op:
        batch_op.drop_column("nom_court")

    # ── 6. Modifier table arbitres ────────────────────────────────

    with op.batch_alter_table("arbitres", schema=None) as batch_op:
        batch_op.drop_column("grade")

    # ── 7. Modifier table sanctions ───────────────────────────────
    #    - Supprimer joueur_id FK

    with op.batch_alter_table("sanctions", schema=None) as batch_op:
        batch_op.drop_column("joueur_id")

    # ── 8. Modifier table participations_match ────────────────────
    #    - Supprimer est_titulaire

    with op.batch_alter_table("participations_match", schema=None) as batch_op:
        batch_op.drop_column("est_titulaire")


def downgrade() -> None:
    """Downgrade: revert all changes."""

    # 8. Restore est_titulaire
    with op.batch_alter_table("participations_match", schema=None) as batch_op:
        batch_op.add_column(sa.Column("est_titulaire", sa.Boolean(), nullable=False, server_default="0"))

    # 7. Restore joueur_id
    with op.batch_alter_table("sanctions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("joueur_id", sa.Integer(), nullable=True))

    # 6. Restore grade
    with op.batch_alter_table("arbitres", schema=None) as batch_op:
        batch_op.add_column(sa.Column("grade", sa.String(length=50), nullable=True))

    # 5. Restore nom_court
    with op.batch_alter_table("equipes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("nom_court", sa.String(length=100), nullable=True))

    # 4. Restore joueur columns
    with op.batch_alter_table("joueurs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("date_naissance", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("nationalite", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("matchs_joues", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("sets_joues", sa.Integer(), nullable=False, server_default="0"))

    # 3. Restore matchs columns
    with op.batch_alter_table("matchs", schema=None) as batch_op:
        batch_op.alter_column("vainqueur", new_column_name="vainqueur_nom")
        batch_op.alter_column("score_sets", new_column_name="score_final")
        batch_op.add_column(sa.Column("vainqueur_id", sa.Integer(), nullable=True))

    # 2. Restore sets columns
    with op.batch_alter_table("sets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("formation_a", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("formation_b", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("timeouts_a", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("timeouts_b", sa.Text(), nullable=True))
        batch_op.alter_column(
            "heure_debut",
            existing_type=sa.Time(),
            type_=sa.String(length=8),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "heure_fin",
            existing_type=sa.Time(),
            type_=sa.String(length=8),
            existing_nullable=True,
        )

    # 1. Drop new tables
    with op.batch_alter_table("services", schema=None) as batch_op:
        batch_op.drop_index("ix_services_set_equipe")
    op.drop_table("services")
    op.drop_table("timeouts")
    op.drop_table("changements")
    op.drop_table("formations")
