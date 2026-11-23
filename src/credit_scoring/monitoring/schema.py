"""Table `prediction_logs` : un enregistrement par appel de scoring (spec #16, §4)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()

# JSONB sur Postgres (requêtes et index), JSON ailleurs (tests sur SQLite).
# none_as_null : une valeur absente est un NULL SQL (« IS NULL »), pas le JSON `null`.
Json = sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")

prediction_logs = sa.Table(
    "prediction_logs",
    metadata,
    sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
    # Traçabilité
    sa.Column("request_id", sa.Uuid(), nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("path", sa.String(64), nullable=False),
    sa.Column("api_version", sa.String(64), nullable=False),
    sa.Column("model_version", sa.String(64)),
    # Identité pseudonymisée (HMAC de SK_ID_CURR, route de démo uniquement)
    sa.Column("client_ref", sa.String(64)),
    # Entrées
    sa.Column("features", Json),
    # Sorties
    sa.Column("prob_default", sa.Float()),
    sa.Column("decision", sa.String(16)),
    sa.Column("threshold", sa.Float()),
    sa.Column("warnings", Json),
    sa.Column("n_warnings", sa.SmallInteger()),
    # Performance
    sa.Column("latency_ms", sa.Float(), nullable=False),
    sa.Column("inference_ms", sa.Float()),
    # Erreurs
    sa.Column("status_code", sa.SmallInteger(), nullable=False),
    sa.Column("error_type", sa.String(16)),
    sa.Column("error_detail", Json),
    sa.Index("ix_prediction_logs_created_at", "created_at"),
    sa.Index("ix_prediction_logs_source_created_at", "source", "created_at"),
)

# Un rapport de dérive par analyse planifiée (#17) : résumé lu par l'onglet Monitoring.
drift_reports = sa.Table(
    "drift_reports",
    metadata,
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
    sa.Index("ix_drift_reports_created_at", "created_at"),
)
