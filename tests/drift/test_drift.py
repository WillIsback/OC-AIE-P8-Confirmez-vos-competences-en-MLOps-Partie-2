"""Module de dérive Evidently (#17) : tourne dans l'environnement analysis/ (pandas 2.3).

    uv run --project analysis pytest tests/drift -o addopts="" -m drift

Dans l'environnement racine (pandas 3, sans Evidently), ces tests sont sautés.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("evidently")

from credit_scoring.monitoring import db, drift, metrics
from credit_scoring.monitoring.schema import prediction_logs

pytestmark = pytest.mark.drift
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
NUM, CAT = ["a", "c"], ["b"]


def frame(n: int, shift: float = 0.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "a": rng.normal(shift, 1, n),
            "b": rng.choice(["x", "y"], n),
            "c": rng.normal(0, 1, n),
            "prob_default": rng.uniform(0, 0.6, n),
        }
    )


def by_name(result: drift.DriftResult) -> dict[str, dict[str, Any]]:
    return {f["name"]: f for f in result.summary["features"]}


def test_derive_detectee_sur_colonne_decalee() -> None:
    result = drift.analyse(frame(4000), frame(2000, shift=1.0, seed=1), NUM, CAT)
    features = by_name(result)
    assert features["a"]["drifted"] is True
    assert features["c"]["drifted"] is False
    assert result.summary["n_drifted"] == 1
    assert result.summary["share_drifted"] == pytest.approx(1 / 3)
    assert result.summary["insufficient"] is False
    assert result.summary["score_drift"]["drifted"] is False
    assert result.html and "<html" in result.html.lower()


def test_categorie_inconnue_et_valeurs_nulles_tolerees() -> None:
    current = frame(1200, seed=2)
    current.loc[:300, "a"] = np.nan
    current.loc[:50, "b"] = "inconnue"
    result = drift.analyse(frame(2000), current, NUM, CAT)
    assert set(by_name(result)) == {"a", "b", "c"}


def test_colonne_vide_ecartee_et_signalee() -> None:
    current = frame(1200, seed=3)
    current["c"] = np.nan
    result = drift.analyse(frame(2000), current, NUM, CAT)
    c = by_name(result)["c"]
    assert c["drifted"] is None and c["method"] == "vide"
    assert result.summary["share_drifted"] == pytest.approx(result.summary["n_drifted"] / 2)


def test_echantillon_insuffisant_sans_evidently(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Evidently ne doit pas tourner")

    monkeypatch.setattr(drift, "_run_report", boom)
    result = drift.analyse(frame(2000), frame(drift.MIN_CURRENT - 1), NUM, CAT)
    assert result.summary["insufficient"] is True
    assert result.summary["share_drifted"] is None
    assert result.html is None


def log(minutes_ago: float, features: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return {
        "request_id": uuid.uuid4(),
        "created_at": NOW - timedelta(minutes=minutes_ago),
        "source": kw.get("source", "api"),
        "path": "/predict",
        "api_version": "0.4.0",
        "features": features,
        "prob_default": kw.get("prob", 0.3),
        "latency_ms": 10.0,
        "status_code": kw.get("status", 200),
    }


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    url = f"sqlite:///{tmp_path / 'logs.db'}"
    db.run_migrations(url)
    eng = db.make_engine(url)
    yield eng
    eng.dispose()


def test_production_frame_appels_reussis_de_l_api(engine: Any) -> None:
    rows = [
        log(10, {"a": 1.0, "b": "x", "c": None}, prob=0.2),
        log(20, {"a": 2.0, "b": "y", "c": 0.5}, source="ui-demo"),
        log(30, {"a": 3.0}, status=422),
        log(60 * 24 * 8, {"a": 4.0, "b": "x", "c": 1.0}),
    ]
    with engine.begin() as conn:
        conn.execute(prediction_logs.insert(), rows)
    current = drift.production_frame(engine, timedelta(days=7), now=NOW)
    assert len(current) == 1
    assert current.iloc[0]["a"] == 1.0 and current.iloc[0]["prob_default"] == 0.2
    assert pd.isna(current.iloc[0]["c"])


def test_production_frame_vide(engine: Any) -> None:
    assert drift.production_frame(engine, timedelta(days=7), now=NOW).empty


def test_sauvegarde_relue_par_le_dashboard(engine: Any) -> None:
    result = drift.analyse(frame(4000), frame(2000, shift=1.0, seed=1), NUM, CAT)
    drift.save(engine, result, NOW - timedelta(days=7), NOW, "test-model v1", now=NOW)
    latest = metrics.latest_drift(engine)
    assert latest is not None
    assert latest["n_drifted"] == 1 and latest["insufficient"] is False
    assert latest["model_version"] == "test-model v1"
    assert latest["details"]["features"][0]["name"] in {"a", "b", "c"}
    assert latest["details"]["score_drift"]["method"]


def test_plancher_mesure_sans_faux_positifs() -> None:
    # Mesure (revue finale) : référence contre elle-même, 16 à 26 % de « dérive » à 200
    # appels, 1 feature à 400, aucune à 1 000. En dessous, le rapport dit « insuffisant ».
    assert drift.MIN_CURRENT == 1000
