"""
add_level_and_speed_columns

Ajoute les colonnes de classification sportive (niveau_badge, niveau_rank, division, categorie, genre),
le côté d'équipe ('A'/'B') sur participations_match, le cache de classement sur poules,
les estimations d'âge/niveau sur stats_joueur_carriere et les points/rang sur stats_equipe_saison.

Revision ID: e7f8a9b0c1d2
Revises: c4d5e6f7a8b9
Create Date: 2026-09-02 15:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def col_names(tbl: str) -> set[str]:
        if tbl in inspector.get_table_names():
            return {c["name"] for c in inspector.get_columns(tbl)}
        return set()

    # 1. competitions
    if "competitions" in inspector.get_table_names():
        comp_cols = col_names("competitions")
        with op.batch_alter_table("competitions") as batch_op:
            if "niveau_badge" not in comp_cols:
                batch_op.add_column(sa.Column("niveau_badge", sa.String(50), nullable=True))
            if "niveau_rank" not in comp_cols:
                batch_op.add_column(sa.Column("niveau_rank", sa.Integer(), server_default="-1", nullable=False))

    # 2. poules
    if "poules" in inspector.get_table_names():
        poule_cols = col_names("poules")
        with op.batch_alter_table("poules") as batch_op:
            if "classement_cache" not in poule_cols:
                batch_op.add_column(sa.Column("classement_cache", sa.JSON(), nullable=True))
            if "classement_updated_at" not in poule_cols:
                batch_op.add_column(sa.Column("classement_updated_at", sa.DateTime(), nullable=True))

    # 3. equipes
    if "equipes" in inspector.get_table_names():
        eq_cols = col_names("equipes")
        with op.batch_alter_table("equipes") as batch_op:
            if "niveau_badge" not in eq_cols:
                batch_op.add_column(sa.Column("niveau_badge", sa.String(50), nullable=True))
            if "niveau_rank" not in eq_cols:
                batch_op.add_column(sa.Column("niveau_rank", sa.Integer(), server_default="-1", nullable=False))

    # 4. matchs
    if "matchs" in inspector.get_table_names():
        match_cols = col_names("matchs")
        with op.batch_alter_table("matchs") as batch_op:
            if "genre" not in match_cols:
                batch_op.add_column(sa.Column("genre", sa.String(20), nullable=True))
            if "categorie" not in match_cols:
                batch_op.add_column(sa.Column("categorie", sa.String(20), nullable=True))
            if "niveau" not in match_cols:
                batch_op.add_column(sa.Column("niveau", sa.String(50), nullable=True))
            if "division" not in match_cols:
                batch_op.add_column(sa.Column("division", sa.String(50), nullable=True))
            if "niveau_badge" not in match_cols:
                batch_op.add_column(sa.Column("niveau_badge", sa.String(50), nullable=True))
            if "niveau_rank" not in match_cols:
                batch_op.add_column(sa.Column("niveau_rank", sa.Integer(), server_default="-1", nullable=False))

            batch_op.create_index("ix_matchs_genre", ["genre"])
            batch_op.create_index("ix_matchs_categorie", ["categorie"])
            batch_op.create_index("ix_matchs_niveau_rank", ["niveau_rank"])

    # 5. participations_match
    if "participations_match" in inspector.get_table_names():
        part_cols = col_names("participations_match")
        with op.batch_alter_table("participations_match") as batch_op:
            if "side" not in part_cols:
                batch_op.add_column(sa.Column("side", sa.String(1), nullable=True))
            batch_op.create_index("ix_participation_match_side", ["match_id", "side"])

    # 6. stats_joueur_carriere
    if "stats_joueur_carriere" in inspector.get_table_names():
        sjc_cols = col_names("stats_joueur_carriere")
        with op.batch_alter_table("stats_joueur_carriere") as batch_op:
            if "estimated_birth_year_min" not in sjc_cols:
                batch_op.add_column(sa.Column("estimated_birth_year_min", sa.Integer(), nullable=True))
            if "estimated_max_age" not in sjc_cols:
                batch_op.add_column(sa.Column("estimated_max_age", sa.Integer(), nullable=True))
            if "best_category_label" not in sjc_cols:
                batch_op.add_column(sa.Column("best_category_label", sa.String(20), nullable=True))
            if "max_niveau_label" not in sjc_cols:
                batch_op.add_column(sa.Column("max_niveau_label", sa.String(50), nullable=True))
            if "max_niveau_rank" not in sjc_cols:
                batch_op.add_column(sa.Column("max_niveau_rank", sa.Integer(), server_default="-1", nullable=False))

    # 7. stats_equipe_saison
    if "stats_equipe_saison" in inspector.get_table_names():
        ses_cols = col_names("stats_equipe_saison")
        with op.batch_alter_table("stats_equipe_saison") as batch_op:
            if "points_ffvb" not in ses_cols:
                batch_op.add_column(sa.Column("points_ffvb", sa.Integer(), server_default="0", nullable=False))
            if "rang" not in ses_cols:
                batch_op.add_column(sa.Column("rang", sa.Integer(), nullable=True))


def downgrade() -> None:
    pass
