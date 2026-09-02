"""
refactor_joueur_match_stats_and_drop_joueur_cache

Drop obsolete joueur_stats_cache table and refactor joueur_match_stats
to use direct structured SQL columns instead of a JSON blob.

Revision ID: c4d5e6f7a8b9
Revises: f7a8b9c0d1e2
Create Date: 2026-09-02 13:00:00+00:00
"""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. Drop obsolete joueur_stats_cache table
    if "joueur_stats_cache" in existing_tables:
        op.drop_table("joueur_stats_cache")

    # 2. Refactor joueur_match_stats columns
    if "joueur_match_stats" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("joueur_match_stats")}

        with op.batch_alter_table("joueur_match_stats") as batch_op:
            if "numero" not in cols:
                batch_op.add_column(sa.Column("numero", sa.String(5), nullable=True))
            if "side" not in cols:
                batch_op.add_column(sa.Column("side", sa.String(1), nullable=True))
            if "est_capitaine" not in cols:
                batch_op.add_column(sa.Column("est_capitaine", sa.Boolean(), server_default="0", nullable=False))
            if "est_libero" not in cols:
                batch_op.add_column(sa.Column("est_libero", sa.Boolean(), server_default="0", nullable=False))
            if "victoire" not in cols:
                batch_op.add_column(sa.Column("victoire", sa.Boolean(), nullable=True))
            if "score_match" not in cols:
                batch_op.add_column(sa.Column("score_match", sa.String(10), nullable=True))
            if "points_gagnes_sideout" not in cols:
                batch_op.add_column(sa.Column("points_gagnes_sideout", sa.Integer(), server_default="0", nullable=False))
            if "break_point_ratio" not in cols:
                batch_op.add_column(sa.Column("break_point_ratio", sa.Float(), server_default="0.0", nullable=False))
            if "sideout_contribution_ratio" not in cols:
                batch_op.add_column(sa.Column("sideout_contribution_ratio", sa.Float(), server_default="0.0", nullable=False))
            if "temps_morts_provoques" not in cols:
                batch_op.add_column(sa.Column("temps_morts_provoques", sa.Integer(), server_default="0", nullable=False))
            if "sets_joues" not in cols:
                batch_op.add_column(sa.Column("sets_joues", sa.Integer(), server_default="0", nullable=False))
            if "sets_titulaire" not in cols:
                batch_op.add_column(sa.Column("sets_titulaire", sa.Integer(), server_default="0", nullable=False))
            if "temps_jeu_estime" not in cols:
                batch_op.add_column(sa.Column("temps_jeu_estime", sa.Float(), nullable=True))
            if "nb_entrees" not in cols:
                batch_op.add_column(sa.Column("nb_entrees", sa.Integer(), server_default="0", nullable=False))
            if "nb_sorties" not in cols:
                batch_op.add_column(sa.Column("nb_sorties", sa.Integer(), server_default="0", nullable=False))
            if "role_principal" not in cols:
                batch_op.add_column(sa.Column("role_principal", sa.String(30), nullable=True))
            if "role_confiance" not in cols:
                batch_op.add_column(sa.Column("role_confiance", sa.Float(), server_default="0.0", nullable=False))
            if "roles_possibles" not in cols:
                batch_op.add_column(sa.Column("roles_possibles", sa.JSON(), nullable=True))
            if "role_scores" not in cols:
                batch_op.add_column(sa.Column("role_scores", sa.JSON(), nullable=True))
            if "indices_roles" not in cols:
                batch_op.add_column(sa.Column("indices_roles", sa.JSON(), nullable=True))
            if "detail_services_par_set" not in cols:
                batch_op.add_column(sa.Column("detail_services_par_set", sa.JSON(), nullable=True))
            if "presence_par_set" not in cols:
                batch_op.add_column(sa.Column("presence_par_set", sa.JSON(), nullable=True))
            if "temps_jeu_par_set" not in cols:
                batch_op.add_column(sa.Column("temps_jeu_par_set", sa.JSON(), nullable=True))

        # Backfill structured columns from stats_data if present
        if "stats_data" in cols:
            rows = bind.execute(sa.text("SELECT id, stats_data FROM joueur_match_stats WHERE stats_data IS NOT NULL")).fetchall()
            for r_id, raw_data in rows:
                if not raw_data:
                    continue
                d = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                if not isinstance(d, dict):
                    continue

                bind.execute(
                    sa.text("""
                        UPDATE joueur_match_stats
                        SET numero = :numero,
                            side = :side,
                            est_capitaine = :est_capitaine,
                            est_libero = :est_libero,
                            victoire = :victoire,
                            score_match = :score_match,
                            points_gagnes_sideout = :points_gagnes_sideout,
                            break_point_ratio = :break_point_ratio,
                            sideout_contribution_ratio = :sideout_contribution_ratio,
                            temps_morts_provoques = :temps_morts_provoques,
                            sets_joues = :sets_joues,
                            sets_titulaire = :sets_titulaire,
                            temps_jeu_estime = :temps_jeu_estime,
                            nb_entrees = :nb_entrees,
                            nb_sorties = :nb_sorties,
                            role_principal = :role_principal,
                            role_confiance = :role_confiance,
                            roles_possibles = :roles_possibles,
                            role_scores = :role_scores,
                            indices_roles = :indices_roles,
                            detail_services_par_set = :detail_services_par_set,
                            presence_par_set = :presence_par_set,
                            temps_jeu_par_set = :temps_jeu_par_set
                        WHERE id = :id
                    """),
                    {
                        "id": r_id,
                        "numero": str(d.get("numero") or "").strip() or None,
                        "side": str(d.get("side") or "").strip() or None,
                        "est_capitaine": bool(d.get("est_capitaine")),
                        "est_libero": bool(d.get("est_libero")),
                        "victoire": d.get("victoire"),
                        "score_match": d.get("score_match"),
                        "points_gagnes_sideout": int(d.get("points_gagnes_sideout") or 0),
                        "break_point_ratio": float(d.get("break_point_ratio") or 0.0),
                        "sideout_contribution_ratio": float(d.get("sideout_contribution_ratio") or 0.0),
                        "temps_morts_provoques": int(d.get("temps_morts_provoques") or 0),
                        "sets_joues": int(d.get("sets_joues") or 0),
                        "sets_titulaire": int(d.get("sets_titulaire") or 0),
                        "temps_jeu_estime": float(d["temps_jeu_estime"]) if d.get("temps_jeu_estime") is not None else None,
                        "nb_entrees": int(d.get("nb_entrees") or 0),
                        "nb_sorties": int(d.get("nb_sorties") or 0),
                        "role_principal": d.get("role_principal"),
                        "role_confiance": float(d.get("role_confiance") or 0.0),
                        "roles_possibles": json.dumps(d.get("roles_possibles") or []),
                        "role_scores": json.dumps(d.get("role_scores") or {}),
                        "indices_roles": json.dumps(d.get("indices_roles") or []),
                        "detail_services_par_set": json.dumps(d.get("detail_services_par_set") or []),
                        "presence_par_set": json.dumps(d.get("presence_par_set") or []),
                        "temps_jeu_par_set": json.dumps(d.get("temps_jeu_par_set") or {}),
                    },
                )

            # Drop stats_data column
            with op.batch_alter_table("joueur_match_stats") as batch_op:
                batch_op.drop_column("stats_data")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "joueur_match_stats" in existing_tables:
        with op.batch_alter_table("joueur_match_stats") as batch_op:
            batch_op.add_column(sa.Column("stats_data", sa.JSON(), nullable=True))
