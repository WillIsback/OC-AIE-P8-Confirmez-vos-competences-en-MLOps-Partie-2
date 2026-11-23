"""Indicateurs opérationnels lus dans `prediction_logs` (#18), sans Evidently.

Calculs en pandas (et non en SQL) : mêmes résultats sur Postgres (Neon) et SQLite (tests).
Les quantiles sont linéaires, comme `percentile_cont`. Compatible pandas 2 et 3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import sqlalchemy as sa

from credit_scoring.monitoring.schema import drift_reports, prediction_logs

COLUMNS = (
    "created_at",
    "source",
    "path",
    "prob_default",
    "decision",
    "latency_ms",
    "inference_ms",
    "status_code",
    "error_type",
)


def load_logs(
    engine: sa.Engine,
    window: timedelta,
    source: str | None = "api",
    now: datetime | None = None,
) -> pd.DataFrame:
    """Appels de la fenêtre `[now - window, now]`, filtrés par source (`None` : toutes)."""
    end = now or datetime.now(UTC)
    query = sa.select(*(prediction_logs.c[name] for name in COLUMNS)).where(
        prediction_logs.c.created_at >= end - window, prediction_logs.c.created_at <= end
    )
    if source is not None:
        query = query.where(prediction_logs.c.source == source)
    with engine.connect() as conn:
        rows = conn.execute(query).all()
    logs = pd.DataFrame([tuple(r) for r in rows], columns=list(COLUMNS))
    logs["created_at"] = pd.to_datetime(logs["created_at"], utc=True)
    for name in ("prob_default", "latency_ms", "inference_ms"):
        logs[name] = pd.to_numeric(logs[name], errors="coerce").astype("float64")
    return logs


def _quantile(values: pd.Series, q: float) -> float | None:
    clean = values.dropna()
    return None if clean.empty else float(clean.quantile(q))


def _ok(logs: pd.DataFrame) -> pd.DataFrame:
    return logs[logs["status_code"] == 200]


def summary(logs: pd.DataFrame) -> dict[str, Any]:
    """Volume, taux d'acceptation et d'erreur, latence et inférence (p50/p95)."""
    if logs.empty:
        keys = ("acceptance_rate", "error_rate", "latency_p50", "latency_p95")
        return {"n": 0, **dict.fromkeys((*keys, "inference_p50", "inference_p95"))}
    ok = _ok(logs)
    return {
        "n": len(logs),
        "acceptance_rate": float((ok["decision"] == "accordé").mean()) if len(ok) else None,
        "error_rate": float((logs["status_code"] >= 400).mean()),
        "latency_p50": _quantile(ok["latency_ms"], 0.5),
        "latency_p95": _quantile(ok["latency_ms"], 0.95),
        "inference_p50": _quantile(ok["inference_ms"], 0.5),
        "inference_p95": _quantile(ok["inference_ms"], 0.95),
    }


def score_histogram(logs: pd.DataFrame, bins: int = 20) -> pd.DataFrame:
    """Distribution des scores des appels réussis : borne basse de chaque tranche, effectif."""
    scores = _ok(logs)["prob_default"].dropna().to_numpy()
    counts, edges = np.histogram(scores, bins=bins, range=(0.0, 1.0))
    return pd.DataFrame({"bin": edges[:-1].round(4), "count": counts.astype(int)})


def hourly(logs: pd.DataFrame) -> pd.DataFrame:
    """Par heure : nombre d'appels et latence p95 des appels réussis."""
    if logs.empty:
        return pd.DataFrame({"hour": [], "n": [], "latency_p95": []})
    frame = logs.assign(hour=logs["created_at"].dt.floor("h"))
    n = frame.groupby("hour").size().rename("n")
    p95 = _ok(frame).groupby("hour")["latency_ms"].quantile(0.95).rename("latency_p95")
    return pd.concat([n, p95], axis=1).reset_index()


def errors_by_type(logs: pd.DataFrame) -> pd.DataFrame:
    """Appels en erreur par type, du plus fréquent au moins fréquent."""
    errors = logs[logs["status_code"] >= 400]
    counts = errors["error_type"].fillna("inconnu").value_counts()
    return pd.DataFrame({"error_type": counts.index.astype(str), "count": counts.to_numpy()})


def latest_drift(engine: sa.Engine) -> dict[str, Any] | None:
    """Dernier rapport de dérive (job planifié), ou `None` s'il n'y en a pas encore."""
    query = sa.select(drift_reports).order_by(drift_reports.c.created_at.desc()).limit(1)
    with engine.connect() as conn:
        row = conn.execute(query).mappings().first()
    return dict(row) if row is not None else None
