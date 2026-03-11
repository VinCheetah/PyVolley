"""
add_personnes_and_link_officiels

Revision ID: b2c7d9a1f4ab
Revises: 10b6e92d44fe
Create Date: 2026-03-10 14:05:00+00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "b2c7d9a1f4ab"
down_revision: Union[str, None] = "10b6e92d44fe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "personnes" not in table_names:
        op.create_table(
            "personnes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("licence", sa.String(length=20), nullable=True),
            sa.Column("nom", sa.String(length=100), nullable=False),
            sa.Column("prenom", sa.String(length=100), nullable=True),
            sa.Column("categorie", sa.String(length=20), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    personnes_indexes = {index["name"] for index in inspector.get_indexes("personnes")}
    if "ix_personnes_licence" not in personnes_indexes:
        op.create_index("ix_personnes_licence", "personnes", ["licence"], unique=False)
    if "ix_personnes_nom" not in personnes_indexes:
        op.create_index("ix_personnes_nom", "personnes", ["nom"], unique=False)
    if "ix_personnes_nom_prenom" not in personnes_indexes:
        op.create_index("ix_personnes_nom_prenom", "personnes", ["nom", "prenom"], unique=False)

    joueur_columns = {column["name"] for column in inspector.get_columns("joueurs")}
    with op.batch_alter_table("joueurs", schema=None) as batch_op:
        if "personne_id" not in joueur_columns:
            batch_op.add_column(sa.Column("personne_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key("fk_joueurs_personne_id", "personnes", ["personne_id"], ["id"])

    officiel_columns = {column["name"] for column in inspector.get_columns("officiels_match")}
    with op.batch_alter_table("officiels_match", schema=None) as batch_op:
        if "personne_id" not in officiel_columns:
            batch_op.add_column(sa.Column("personne_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key("fk_officiels_match_personne_id", "personnes", ["personne_id"], ["id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    officiel_columns = {column["name"] for column in inspector.get_columns("officiels_match")}
    with op.batch_alter_table("officiels_match", schema=None) as batch_op:
        if "personne_id" in officiel_columns:
            try:
                batch_op.drop_constraint("fk_officiels_match_personne_id", type_="foreignkey")
            except Exception:
                pass
            batch_op.drop_column("personne_id")

    joueur_columns = {column["name"] for column in inspector.get_columns("joueurs")}
    with op.batch_alter_table("joueurs", schema=None) as batch_op:
        if "personne_id" in joueur_columns:
            try:
                batch_op.drop_constraint("fk_joueurs_personne_id", type_="foreignkey")
            except Exception:
                pass
            batch_op.drop_column("personne_id")

    if "personnes" in set(inspector.get_table_names()):
        personnes_indexes = {index["name"] for index in inspector.get_indexes("personnes")}
        if "ix_personnes_nom_prenom" in personnes_indexes:
            op.drop_index("ix_personnes_nom_prenom", table_name="personnes")
        if "ix_personnes_nom" in personnes_indexes:
            op.drop_index("ix_personnes_nom", table_name="personnes")
        if "ix_personnes_licence" in personnes_indexes:
            op.drop_index("ix_personnes_licence", table_name="personnes")
        op.drop_table("personnes")
