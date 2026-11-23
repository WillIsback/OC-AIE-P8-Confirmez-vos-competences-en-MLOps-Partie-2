"""Job planifié d'analyse de dérive (#17), sur SQLite avec trafic synthétique."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("evidently")

from scripts import drift_job

from credit_scoring.model import load_model
from credit_scoring.monitoring import db, metrics
from credit_scoring.monitoring.schema import prediction_logs
from tests.synthetic import clients

pytestmark = pytest.mark.drift
NOW = datetime(2026, 11, 23, 4, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    url = f"sqlite:///{tmp_path / 'logs.db'}"
    db.run_migrations(url)
    eng = db.make_engine(url)
    yield eng
    eng.dispose()


def traffic(engine: Any, model: Any, n: int, shift: float) -> None:
    frame = clients(n, model.features.categories, seed=5, shift=shift)
    probs = model.predict(frame)["prob_default"].tolist()
    rows = [
        {
            "request_id": uuid.uuid4(),
            "created_at": NOW - timedelta(hours=1 + i % 100),
            "source": "api",
            "path": "/predict",
            "api_version": "0.4.0",
            "features": record,
            "prob_default": prob,
            "latency_ms": 12.0,
            "status_code": 200,
        }
        for i, (record, prob) in enumerate(zip(frame.to_dict("records"), probs, strict=True))
    ]
    with engine.begin() as conn:
        conn.execute(prediction_logs.insert(), rows)


def reference(model: Any) -> Any:
    frame = clients(1500, model.features.categories, seed=0)
    frame["prob_default"] = model.predict(frame)["prob_default"]
    return frame


def test_job_ecrit_un_rapport(engine: Any, api_artifacts: Path) -> None:
    model = load_model(api_artifacts)
    traffic(engine, model, 300, shift=1.0)
    result = drift_job.run(engine, reference(model), model, timedelta(days=7), now=NOW)
    assert result.summary["n_current"] == 300
    assert result.summary["n_drifted"] > 0
    latest = metrics.latest_drift(engine)
    assert latest is not None and latest["model_version"] == model.version
    assert latest["n_current"] == 300


def test_job_echantillon_insuffisant(engine: Any, api_artifacts: Path) -> None:
    model = load_model(api_artifacts)
    traffic(engine, model, 50, shift=0.0)
    result = drift_job.run(engine, reference(model), model, timedelta(days=7), now=NOW)
    assert result.summary["insufficient"] is True
    latest = metrics.latest_drift(engine)
    assert latest is not None and latest["insufficient"] is True
