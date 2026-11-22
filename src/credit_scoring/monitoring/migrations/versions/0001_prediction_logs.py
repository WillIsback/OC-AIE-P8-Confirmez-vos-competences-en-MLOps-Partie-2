"""Table prediction_logs (#16).

Revision ID: 0001
Revises:

Écrite à la main et figée : une évolution du schéma passe par une nouvelle révision.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None

Json = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "prediction_logs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("path", sa.String(64), nullable=False),
        sa.Column("api_version", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(64)),
        sa.Column("client_ref", sa.String(64)),
        sa.Column("features", Json),
        sa.Column("prob_default", sa.Float()),
        sa.Column("decision", sa.String(16)),
        sa.Column("threshold", sa.Float()),
        sa.Column("warnings", Json),
        sa.Column("n_warnings", sa.SmallInteger()),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("inference_ms", sa.Float()),
        sa.Column("status_code", sa.SmallInteger(), nullable=False),
        sa.Column("error_type", sa.String(16)),
        sa.Column("error_detail", Json),
    )
    op.create_index("ix_prediction_logs_created_at", "prediction_logs", ["created_at"])
    op.create_index(
        "ix_prediction_logs_source_created_at", "prediction_logs", ["source", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("prediction_logs")
