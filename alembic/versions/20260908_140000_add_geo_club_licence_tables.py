"""
add_geo_club_licence_tables

Crée les tables stats_club, stats_geographiques et joueur_licence_history.

Revision ID: a1c2e3g4i5k6
Revises: f8a9b0c1d2e3
Create Date: 2026-09-08 14:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c2e3g4i5k6"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. stats_club
    if "stats_club" not in existing_tables:
        op.create_table(
            "stats_club",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("club_id", sa.Integer(), sa.ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("saison_id", sa.Integer(), sa.ForeignKey("saisons.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("nb_equipes_engagees", sa.Integer(), server_default="0", nullable=False),
            sa.Column("nb_matchs_joues", sa.Integer(), server_default="0", nullable=False),
            sa.Column("nb_victoires", sa.Integer(), server_default="0", nullable=False),
            sa.Column("nb_defaites", sa.Integer(), server_default="0", nullable=False),
            sa.Column("ratio_victoires", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("sets_pour", sa.Integer(), server_default="0", nullable=False),
            sa.Column("sets_contre", sa.Integer(), server_default="0", nullable=False),
            sa.Column("ratio_sets", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("points_pour", sa.Integer(), server_default="0", nullable=False),
            sa.Column("points_contre", sa.Integer(), server_default="0", nullable=False),
            sa.Column("ratio_points", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("nb_joueurs_distincts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("max_niveau_label", sa.String(50), nullable=True),
            sa.Column("max_niveau_rank", sa.Integer(), server_default="-1", nullable=False),
            sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("club_id", "saison_id", name="uq_stats_club_saison"),
        )
        op.create_index("ix_sc_saison_victoires", "stats_club", ["saison_id", "nb_victoires"])
        op.create_index("ix_sc_ratio_victoires", "stats_club", ["ratio_victoires"])

    # 2. stats_geographiques
    if "stats_geographiques" not in existing_tables:
        op.create_table(
            "stats_geographiques",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("saison_id", sa.Integer(), sa.ForeignKey("saisons.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("echelon", sa.String(20), nullable=False, index=True),
            sa.Column("code_territoire", sa.String(20), nullable=False, index=True),
            sa.Column("nom_territoire", sa.String(100), nullable=False),
            sa.Column("nb_clubs", sa.Integer(), server_default="0", nullable=False),
            sa.Column("nb_equipes", sa.Integer(), server_default="0", nullable=False),
            sa.Column("nb_joueurs_actifs", sa.Integer(), server_default="0", nullable=False),
            sa.Column("nb_matchs_joues", sa.Integer(), server_default="0", nullable=False),
            sa.Column("repartition_genre", sa.JSON(), nullable=True),
            sa.Column("repartition_categories", sa.JSON(), nullable=True),
            sa.Column("repartition_niveaux", sa.JSON(), nullable=True),
            sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("saison_id", "echelon", "code_territoire", name="uq_geo_stats_territoire"),
        )
        op.create_index("ix_geo_echelon_territoire", "stats_geographiques", ["echelon", "code_territoire"])

    # 3. joueur_licence_history
    if "joueur_licence_history" not in existing_tables:
        op.create_table(
            "joueur_licence_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("joueur_id", sa.Integer(), sa.ForeignKey("joueurs.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("saison_id", sa.Integer(), sa.ForeignKey("saisons.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("type_licence", sa.String(20), nullable=False, index=True),
            sa.Column("premiere_saison_id", sa.Integer(), sa.ForeignKey("saisons.id", ondelete="SET NULL"), nullable=True),
            sa.Column("nb_saisons_absence", sa.Integer(), server_default="0", nullable=False),
            sa.Column("genre_pratique", sa.String(10), nullable=True),
            sa.Column("categorie_pratique", sa.String(20), nullable=True),
            sa.Column("niveau_max_saison", sa.String(50), nullable=True),
            sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("joueur_id", "saison_id", name="uq_joueur_licence_saison"),
        )
        op.create_index("ix_jlh_saison_type", "joueur_licence_history", ["saison_id", "type_licence"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "joueur_licence_history" in existing_tables:
        op.drop_table("joueur_licence_history")
    if "stats_geographiques" in existing_tables:
        op.drop_table("stats_geographiques")
    if "stats_club" in existing_tables:
        op.drop_table("stats_club")
