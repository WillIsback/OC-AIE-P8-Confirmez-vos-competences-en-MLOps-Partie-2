"""Indicateurs opérationnels et table `drift_reports` (#17, #18)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from credit_scoring.monitoring import db, metrics, thresholds
from credit_scoring.monitoring.schema import drift_reports, prediction_logs

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    url = f"sqlite:///{tmp_path / 'logs.db'}"
    db.run_migrations(url)
    eng = db.make_engine(url)
    yield eng
    eng.dispose()


def log(
    minutes_ago: float,
    *,
    source: str = "api",
    status: int = 200,
    prob: float | None = 0.2,
    decision: str | None = "accordé",
    latency: float = 10.0,
    inference: float | None = 5.0,
    error_type: str | None = None,
    path: str = "/predict",
) -> dict[str, Any]:
    return {
        "request_id": uuid.uuid4(),
        "created_at": NOW - timedelta(minutes=minutes_ago),
        "source": source,
        "path": path,
        "api_version": "0.4.0",
        "prob_default": prob if status == 200 else None,
        "decision": decision if status == 200 else None,
        "latency_ms": latency,
        "inference_ms": inference if status == 200 else None,
        "status_code": status,
        "error_type": error_type,
    }


def insert(engine: Any, *rows: dict[str, Any]) -> None:
    with engine.begin() as conn:
        conn.execute(prediction_logs.insert(), list(rows))


def test_fenetre_et_source_filtrees(engine: Any) -> None:
    insert(
        engine,
        log(10),
        log(60 * 30),  # 30 h : hors fenêtre de 24 h
        log(5, source="ui-demo"),
    )
    assert len(metrics.load_logs(engine, timedelta(hours=24), now=NOW)) == 1
    assert len(metrics.load_logs(engine, timedelta(hours=24), source=None, now=NOW)) == 2
    assert len(metrics.load_logs(engine, timedelta(days=7), now=NOW)) == 2


def test_resume_quantiles_et_taux(engine: Any) -> None:
    rows = [log(i, latency=float(i), inference=float(i) / 10) for i in range(1, 101)]
    rows[0]["decision"] = "refusé"
    rows.append(log(1, status=422, error_type="validation"))
    rows.append(log(1, status=401, error_type="unauthorized"))
    insert(engine, *rows)
    s = metrics.summary(metrics.load_logs(engine, timedelta(days=1), now=NOW))
    assert s["n"] == 102
    assert s["error_rate"] == pytest.approx(2 / 102)
    assert s["acceptance_rate"] == pytest.approx(99 / 100)
    assert s["latency_p50"] == pytest.approx(50.5)
    assert s["latency_p95"] == pytest.approx(95.05)
    assert s["inference_p95"] == pytest.approx(9.505)


def test_resume_vide(engine: Any) -> None:
    s = metrics.summary(metrics.load_logs(engine, timedelta(days=1), now=NOW))
    assert s["n"] == 0
    assert all(s[k] is None for k in s if k != "n")


def test_histogramme_des_scores(engine: Any) -> None:
    insert(engine, log(1, prob=0.01), log(2, prob=0.99), log(3, prob=0.99), log(4, status=500))
    hist = metrics.score_histogram(metrics.load_logs(engine, timedelta(days=1), now=NOW), bins=10)
    assert list(hist.columns) == ["bin", "count"]
    assert len(hist) == 10
    assert hist["count"].sum() == 3
    assert hist.iloc[0]["count"] == 1 and hist.iloc[-1]["count"] == 2


def test_serie_horaire(engine: Any) -> None:
    insert(engine, log(5, latency=10), log(10, latency=30), log(90, latency=50))
    hourly = metrics.hourly(metrics.load_logs(engine, timedelta(days=1), now=NOW))
    assert list(hourly.columns) == ["hour", "n", "latency_p95"]
    assert hourly["n"].tolist() == [1, 2]


def test_erreurs_par_type(engine: Any) -> None:
    insert(
        engine,
        log(1, status=422, error_type="validation"),
        log(2, status=422, error_type="validation"),
        log(3, status=401, error_type="unauthorized"),
        log(4),
    )
    errors = metrics.errors_by_type(metrics.load_logs(engine, timedelta(days=1), now=NOW))
    assert errors.to_dict("records") == [
        {"error_type": "validation", "count": 2},
        {"error_type": "unauthorized", "count": 1},
    ]


def test_indicateurs_sur_fenetre_vide(engine: Any) -> None:
    logs = metrics.load_logs(engine, timedelta(days=1), now=NOW)
    assert metrics.score_histogram(logs)["count"].sum() == 0
    assert metrics.hourly(logs).empty
    assert metrics.errors_by_type(logs).empty


def report(created_at: datetime, share: float) -> dict[str, Any]:
    return {
        "created_at": created_at,
        "window_start": created_at - timedelta(days=7),
        "window_end": created_at,
        "n_reference": 20_000,
        "n_current": 500,
        "share_drifted": share,
        "n_drifted": int(share * 122),
        "score_drift_stat": 0.05,
        "score_drifted": False,
        "insufficient": False,
        "model_version": "home-credit-serving v2",
        "details": [{"name": "AMT_CREDIT", "drifted": True}],
    }


def test_dernier_rapport_de_derive(engine: Any) -> None:
    assert metrics.latest_drift(engine) is None
    with engine.begin() as conn:
        conn.execute(drift_reports.insert(), [report(NOW - timedelta(days=1), 0.1)])
        conn.execute(drift_reports.insert(), [report(NOW, 0.4)])
    latest = metrics.latest_drift(engine)
    assert latest is not None
    assert latest["share_drifted"] == pytest.approx(0.4)
    assert latest["details"] == [{"name": "AMT_CREDIT", "drifted": True}]


def test_migration_0002_reversible(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    db.run_migrations(url)
    eng = db.make_engine(url)
    assert sa.inspect(eng).has_table("drift_reports")
    db.run_migrations(url, "0001", downgrade=True)
    assert not sa.inspect(eng).has_table("drift_reports")
    assert sa.inspect(eng).has_table("prediction_logs")
    eng.dispose()


def test_seuils_declares() -> None:
    assert set(thresholds.THRESHOLDS) == {
        "drift_share_alert",
        "score_drift_alert",
        "error_rate_alert",
        "latency_p95_ms_alert",
    }
