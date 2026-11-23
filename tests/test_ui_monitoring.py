"""Onglet « Monitoring » (#18) : gestionnaire appelé directement, sans lancer Gradio."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import sqlalchemy as sa

from credit_scoring.monitoring import db
from credit_scoring.monitoring.schema import drift_reports, prediction_logs
from credit_scoring.monitoring.thresholds import THRESHOLDS
from credit_scoring.ui import monitoring as mon

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    url = f"sqlite:///{tmp_path / 'logs.db'}"
    db.run_migrations(url)
    eng = db.make_engine(url)
    yield eng
    eng.dispose()


def log(minutes_ago: float, status: int = 200, **kw: Any) -> dict[str, Any]:
    return {
        "request_id": uuid.uuid4(),
        "created_at": NOW - timedelta(minutes=minutes_ago),
        "source": kw.get("source", "api"),
        "path": "/predict",
        "api_version": "0.4.0",
        "prob_default": kw.get("prob", 0.3) if status == 200 else None,
        "decision": kw.get("decision", "accordé") if status == 200 else None,
        "latency_ms": kw.get("latency", 12.0),
        "inference_ms": 8.0 if status == 200 else None,
        "status_code": status,
        "error_type": kw.get("error_type"),
    }


def insert(engine: Any, table: sa.Table, *rows: dict[str, Any]) -> None:
    with engine.begin() as conn:
        conn.execute(table.insert(), list(rows))


def drift_row(**kw: Any) -> dict[str, Any]:
    features = [
        {"name": "autoFE_f_7", "method": "Wasserstein distance (normed)", "stat": 0.58,
         "threshold": 0.1, "drifted": True},
        {"name": "<b>AMT</b>", "method": "Wasserstein distance (normed)", "stat": 0.2,
         "threshold": 0.1, "drifted": True},
        {"name": "FLAG_EMAIL", "method": "Jensen-Shannon distance", "stat": 0.01,
         "threshold": 0.1, "drifted": False},
    ]  # fmt: skip
    return {
        "created_at": NOW - timedelta(hours=8),
        "window_start": NOW - timedelta(days=7, hours=8),
        "window_end": NOW - timedelta(hours=8),
        "n_reference": 20_000,
        "n_current": 1374,
        "share_drifted": kw.get("share", 0.139),
        "n_drifted": 17,
        "score_drift_stat": 0.08,
        "score_drifted": False,
        "insufficient": kw.get("insufficient", False),
        "model_version": "home-credit-serving v2",
        "details": {"features": features, "score_drift": {"stat": 0.08, "drifted": False}},
    }


def refresh(engine: Any, window: str = "24 heures", source: str = mon.DEFAULT_SOURCE) -> Any:
    return mon.on_refresh(engine, window, source, now=NOW)


def test_indicateurs_de_la_fenetre(engine: Any) -> None:
    insert(
        engine,
        prediction_logs,
        log(5, prob=0.1),
        log(10, prob=0.9, decision="refusé"),
        log(15, status=422, error_type="validation"),
        log(20, source="ui-demo"),
    )
    tiles, hist, hourly, errors, drift_html, message = refresh(engine)
    assert message == ""
    assert "3" in tiles  # appels de production seulement
    assert "50,0" in tiles  # taux d'acceptation
    assert isinstance(hist, pd.DataFrame) and hist["count"].sum() == 2
    assert list(errors["error_type"]) == ["validation"]
    assert not hourly.empty
    assert "Aucune analyse" in drift_html


def test_source_tout(engine: Any) -> None:
    insert(engine, prediction_logs, log(5), log(20, source="ui-demo"))
    _, hist, *_ = refresh(engine, source="Tout")
    assert hist["count"].sum() == 2


def test_fenetre_vide_sans_nan(engine: Any) -> None:
    tiles, hist, hourly, errors, _, message = refresh(engine)
    assert "nan" not in tiles.lower()
    assert "—" in tiles
    assert hist["count"].sum() == 0 and hourly.empty and errors.empty
    assert message == ""


def test_alerte_taux_d_erreur(engine: Any) -> None:
    rows = [log(i) for i in range(1, 10)] + [log(30, status=500, error_type="internal")]
    insert(engine, prediction_logs, *rows)
    tiles, *_ = refresh(engine)
    assert THRESHOLDS["error_rate_alert"] < 0.1
    assert "tile-alert" in tiles


def test_bloc_derive_alerte_et_echappement(engine: Any) -> None:
    insert(engine, drift_reports, drift_row(share=0.45))
    *_, drift_html, _ = refresh(engine)
    assert "45,0" in drift_html
    assert "tile-alert" in drift_html  # 45 % > seuil
    assert "autoFE_f_7" in drift_html
    assert "<b>AMT</b>" not in drift_html and "&lt;b&gt;" in drift_html
    assert "FLAG_EMAIL" not in drift_html  # seules les features en dérive sont listées


def test_bloc_derive_sous_le_seuil(engine: Any) -> None:
    insert(engine, drift_reports, drift_row(share=0.139))
    *_, drift_html, _ = refresh(engine)
    assert "13,9" in drift_html and "tile-alert" not in drift_html


def test_bloc_derive_echantillon_insuffisant(engine: Any) -> None:
    row = drift_row(insufficient=True)
    row.update(share_drifted=None, n_drifted=None, score_drift_stat=None, score_drifted=None)
    row["details"] = {"features": [], "score_drift": None}
    insert(engine, drift_reports, row)
    *_, drift_html, _ = refresh(engine)
    assert "insuffisant" in drift_html


def test_base_absente() -> None:
    tiles, hist, hourly, errors, drift_html, message = refresh(None)
    assert "non configurée" in message
    assert tiles == "" and drift_html == ""
    assert hist.empty and hourly.empty and errors.empty


class Broken:
    def connect(self) -> Any:
        raise sa.exc.OperationalError("SELECT 1", {}, Exception("injoignable"))


def test_base_injoignable() -> None:
    *_, message = refresh(Broken())
    assert "injoignable" in message.lower()


def test_fenetres_proposees() -> None:
    assert list(mon.WINDOWS) == ["24 heures", "7 jours", "30 jours"]
    assert mon.SOURCES[mon.DEFAULT_SOURCE] == "api"
