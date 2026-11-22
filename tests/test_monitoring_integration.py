"""Neon réel : écriture et relecture dans un schéma temporaire, jamais dans la vraie table.

Marqué `integration` : lancé par la gate de la release (environnement ml-models) ou en local
avec `DATABASE_URL`. Le pooler Neon refuse le paramètre `options` (search_path) : le schéma
est imposé par `schema_translate_map`.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from credit_scoring.monitoring import db
from credit_scoring.monitoring.schema import metadata, prediction_logs
from credit_scoring.monitoring.writer import ProductionLogWriter

pytestmark = pytest.mark.integration


def test_ecriture_et_relecture_sur_neon() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL absent")
    schema_name = f"ci_{uuid.uuid4().hex[:12]}"
    base = db.make_engine(url)
    engine = base.execution_options(schema_translate_map={None: schema_name})
    with base.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema_name}"'))
    try:
        metadata.create_all(engine)
        request_id = uuid.uuid4()
        writer = ProductionLogWriter(engine)
        writer.start()
        writer.submit(
            {
                "request_id": request_id,
                "created_at": datetime.now(UTC),
                "source": "ci",
                "path": "/predict",
                "api_version": "test",
                "model_version": "home-credit-serving v2",
                "client_ref": None,
                "features": {"AMT_CREDIT": 514777.5, "OWN_CAR_AGE": None},
                "prob_default": 0.46,
                "decision": "accordé",
                "threshold": 0.5348,
                "warnings": [],
                "n_warnings": 0,
                "latency_ms": 12.0,
                "inference_ms": 10.0,
                "status_code": 200,
                "error_type": None,
                "error_detail": None,
            }
        )
        writer.stop()
        assert writer.dropped == 0
        with engine.connect() as conn:
            row = conn.execute(
                sa.select(prediction_logs).where(prediction_logs.c.request_id == request_id)
            ).one()
        assert row.features["AMT_CREDIT"] == 514777.5
        assert row.source == "ci"
    finally:
        with base.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        base.dispose()
