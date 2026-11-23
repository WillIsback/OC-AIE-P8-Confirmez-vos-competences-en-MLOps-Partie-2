"""`drift_reports` sur le vrai dialecte (JSONB, timestamptz) : écrit par le job, relu par
l'onglet Monitoring (#45). `drift.save` n'importe pas Evidently : testable à la racine."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from credit_scoring.monitoring import db, drift, metrics
from credit_scoring.monitoring.schema import drift_reports

pytestmark = pytest.mark.postgres


def test_rapport_ecrit_puis_relu_sur_postgres() -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL absent")
    db.run_migrations(url)
    engine = db.make_engine(url)
    now = datetime(2026, 11, 23, 4, 0, tzinfo=UTC)
    features = [
        {"name": "autoFE_f_7", "method": "Wasserstein distance (normed)", "stat": 0.58,
         "threshold": 0.1, "drifted": True},
        {"name": "OWN_CAR_AGE", "method": "vide", "stat": None, "threshold": None,
         "drifted": None},
    ]  # fmt: skip
    score = {"name": "prob_default", "method": "Wasserstein distance (normed)", "stat": 0.08,
             "threshold": 0.1, "drifted": False}  # fmt: skip
    summary = {"n_reference": 20_000, "n_current": 1374, "insufficient": False,
               "share_drifted": 1.0, "n_drifted": 1, "score_drift": score,
               "features": features}  # fmt: skip
    try:
        drift.save(engine, drift.DriftResult(summary, None), now - timedelta(days=7), now,
                   "test v1", now=now)  # fmt: skip
        latest = metrics.latest_drift(engine)
        assert latest is not None
        assert latest["created_at"] == now
        assert latest["details"]["features"][1]["stat"] is None
        assert latest["score_drifted"] is False
    finally:
        with engine.begin() as conn:
            conn.execute(sa.delete(drift_reports))
        engine.dispose()
