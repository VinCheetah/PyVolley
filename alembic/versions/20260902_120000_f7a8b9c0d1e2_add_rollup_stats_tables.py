"""
add_rollup_stats_tables

Create stats_joueur_saison, stats_joueur_carriere, and stats_equipe_saison tables.

Revision ID: f7a8b9c0d1e2
Revises: d0e1f2a3b4c5
Create Date: 2026-09-02 12:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. stats_joueur_saison
    if "stats_joueur_saison" not in existing_tables:
        op.create_table(
            "stats_joueur_saison",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("joueur_id", sa.Integer(), sa.ForeignKey("joueurs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("saison_id", sa.Integer(), sa.ForeignKey("saisons.id", ondelete="CASCADE"), nullable=False),
            sa.Column("competition_id", sa.Integer(), sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=True),
            sa.Column("equipe_id", sa.Integer(), sa.ForeignKey("equipes.id", ondelete="CASCADE"), nullable=True),
            sa.Column("matchs_joues", sa.Integer(), server_default="0", nullable=False),
            sa.Column("matchs_titulaire", sa.Integer(), server_default="0", nullable=False),
            sa.Column("victoires", sa.Integer(), server_default="0", nullable=False),
            sa.Column("defaites", sa.Integer(), server_default="0", nullable=False),
            sa.Column("sets_joues", sa.Integer(), server_default="0", nullable=False),
            sa.Column("sets_titulaire", sa.Integer(), server_default="0", nullable=False),
            sa.Column("points_gagnes", sa.Integer(), server_default="0", nullable=False),
            sa.Column("points_perdus", sa.Integer(), server_default="0", nullable=False),
            sa.Column("points_joues", sa.Integer(), server_default="0", nullable=False),
            sa.Column("points_service", sa.Integer(), server_default="0", nullable=False),
            sa.Column("points_sideout", sa.Integer(), server_default="0", nullable=False),
            sa.Column("services", sa.Integer(), server_default="0", nullable=False),
            sa.Column("series", sa.Integer(), server_default="0", nullable=False),
            sa.Column("max_serie", sa.Integer(), server_default="0", nullable=False),
            sa.Column("moyenne_services_par_serie", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("ratio_points_gagnes", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("role_principal", sa.String(length=30), nullable=True),
            sa.Column("roles_frequence", sa.JSON(), nullable=True),
            sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("joueur_id", "saison_id", "competition_id", "equipe_id", name="uq_stats_joueur_saison_comp_eq"),
        )
        op.create_index("ix_sjs_saison_competition", "stats_joueur_saison", ["saison_id", "competition_id"])
        op.create_index("ix_sjs_joueur_saison", "stats_joueur_saison", ["joueur_id", "saison_id"])
        op.create_index("ix_sjs_points_gagnes", "stats_joueur_saison", ["points_gagnes"])
        op.create_index("ix_sjs_services", "stats_joueur_saison", ["services"])

    # 2. stats_joueur_carriere
    if "stats_joueur_carriere" not in existing_tables:
        op.create_table(
            "stats_joueur_carriere",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("joueur_id", sa.Integer(), sa.ForeignKey("joueurs.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("total_matchs", sa.Integer(), server_default="0", nullable=False),
            sa.Column("total_victoires", sa.Integer(), server_default="0", nullable=False),
            sa.Column("total_defaites", sa.Integer(), server_default="0", nullable=False),
            sa.Column("total_sets", sa.Integer(), server_default="0", nullable=False),
            sa.Column("total_points_gagnes", sa.Integer(), server_default="0", nullable=False),
            sa.Column("total_points_joues", sa.Integer(), server_default="0", nullable=False),
            sa.Column("total_services", sa.Integer(), server_default="0", nullable=False),
            sa.Column("total_series", sa.Integer(), server_default="0", nullable=False),
            sa.Column("max_serie_carriere", sa.Integer(), server_default="0", nullable=False),
            sa.Column("max_points_match", sa.Integer(), server_default="0", nullable=False),
            sa.Column("clubs_frequentes_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("saisons_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("premier_match_date", sa.Date(), nullable=True),
            sa.Column("dernier_match_date", sa.Date(), nullable=True),
            sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_sjc_total_matchs", "stats_joueur_carriere", ["total_matchs"])
        op.create_index("ix_sjc_total_points", "stats_joueur_carriere", ["total_points_gagnes"])

    # 3. stats_equipe_saison
    if "stats_equipe_saison" not in existing_tables:
        op.create_table(
            "stats_equipe_saison",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("equipe_id", sa.Integer(), sa.ForeignKey("equipes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("saison_id", sa.Integer(), sa.ForeignKey("saisons.id", ondelete="CASCADE"), nullable=False),
            sa.Column("competition_id", sa.Integer(), sa.ForeignKey("competitions.id", ondelete="CASCADE"), nullable=True),
            sa.Column("poule_id", sa.Integer(), sa.ForeignKey("poules.id", ondelete="CASCADE"), nullable=True),
            sa.Column("matchs_joues", sa.Integer(), server_default="0", nullable=False),
            sa.Column("victoires", sa.Integer(), server_default="0", nullable=False),
            sa.Column("defaites", sa.Integer(), server_default="0", nullable=False),
            sa.Column("victoires_domicile", sa.Integer(), server_default="0", nullable=False),
            sa.Column("victoires_exterieur", sa.Integer(), server_default="0", nullable=False),
            sa.Column("victoires_3_0", sa.Integer(), server_default="0", nullable=False),
            sa.Column("victoires_3_1", sa.Integer(), server_default="0", nullable=False),
            sa.Column("victoires_3_2", sa.Integer(), server_default="0", nullable=False),
            sa.Column("defaites_2_3", sa.Integer(), server_default="0", nullable=False),
            sa.Column("defaites_1_3", sa.Integer(), server_default="0", nullable=False),
            sa.Column("defaites_0_3", sa.Integer(), server_default="0", nullable=False),
            sa.Column("forfaits", sa.Integer(), server_default="0", nullable=False),
            sa.Column("sets_pour", sa.Integer(), server_default="0", nullable=False),
            sa.Column("sets_contre", sa.Integer(), server_default="0", nullable=False),
            sa.Column("ratio_sets", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("points_pour", sa.Integer(), server_default="0", nullable=False),
            sa.Column("points_contre", sa.Integer(), server_default="0", nullable=False),
            sa.Column("ratio_points", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("serie_victoires_max", sa.Integer(), server_default="0", nullable=False),
            sa.Column("serie_en_cours", sa.Integer(), server_default="0", nullable=False),
            sa.Column("computed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("equipe_id", "saison_id", "competition_id", name="uq_stats_equipe_saison_comp"),
        )
        op.create_index("ix_ses_saison_competition", "stats_equipe_saison", ["saison_id", "competition_id"])
        op.create_index("ix_ses_victoires", "stats_equipe_saison", ["victoires"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "stats_equipe_saison" in existing_tables:
        op.drop_table("stats_equipe_saison")
    if "stats_joueur_carriere" in existing_tables:
        op.drop_table("stats_joueur_carriere")
    if "stats_joueur_saison" in existing_tables:
        op.drop_table("stats_joueur_saison")
