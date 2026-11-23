"""Table drift_reports (#17).

Revision ID: 0002
Revises: 0001

Écrite à la main et figée : une évolution du schéma passe par une nouvelle révision.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"

Json = sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def upgrade() -> None:
    op.create_table(
        "drift_reports",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("n_reference", sa.Integer(), nullable=False),
        sa.Column("n_current", sa.Integer(), nullable=False),
        sa.Column("share_drifted", sa.Float()),
        sa.Column("n_drifted", sa.Integer()),
        sa.Column("score_drift_stat", sa.Float()),
        sa.Column("score_drifted", sa.Boolean()),
        sa.Column("insufficient", sa.Boolean(), nullable=False),
        sa.Column("model_version", sa.String(64)),
        sa.Column("details", Json),
    )
    op.create_index("ix_drift_reports_created_at", "drift_reports", ["created_at"])


def downgrade() -> None:
    op.drop_table("drift_reports")
