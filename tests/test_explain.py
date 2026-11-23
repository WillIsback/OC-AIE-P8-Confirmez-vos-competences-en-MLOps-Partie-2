"""Explication locale du score : contributions SHAP exactes, politique et route (#44)."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from credit_scoring.api import fairness
from credit_scoring.api.app import app
from credit_scoring.api.features_schema import EXAMPLE_CLIENT, FEATURE_ORDER, NULLABLE_FEATURES
from credit_scoring.api.schemas import ClientFeatures
from credit_scoring.api.scoring import explain
from credit_scoring.model import get_model, load_model
from credit_scoring.monitoring import db
from credit_scoring.monitoring.middleware import logged_path
from credit_scoring.monitoring.schema import prediction_logs
from tests.conftest import API_KEY

AUTH = {"X-API-Key": API_KEY}
REAL_ARTIFACTS = Path("artifacts")


def logit(p: float) -> float:
    return math.log(p / (1 - p))


@pytest.fixture
def client(api_artifacts: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MODEL_DIR", str(api_artifacts))
    monkeypatch.setenv("API_KEY", API_KEY)
    get_model.cache_clear()
    with TestClient(app) as c:
        yield c
    get_model.cache_clear()


def with_nulls() -> dict[str, Any]:
    return {**EXAMPLE_CLIENT, **dict.fromkeys(sorted(NULLABLE_FEATURES)[:3])}


# --- modèle ---------------------------------------------------------------------------


def test_contributions_base_plus_somme_egale_logit(api_artifacts: Path) -> None:
    model = load_model(api_artifacts)
    frame = pd.DataFrame([EXAMPLE_CLIENT], columns=list(FEATURE_ORDER))
    _, base, contributions = model.explain_row(frame)
    assert contributions.shape == (len(model.features.model_columns),)
    prob = float(model.predict(frame)["prob_default"].iloc[0])
    assert base + contributions.sum() == pytest.approx(logit(prob), abs=1e-6)


# --- explain --------------------------------------------------------------------------


def test_explain_top_trie_et_reste_dans_others(api_artifacts: Path) -> None:
    model = load_model(api_artifacts)
    result = explain(model, ClientFeatures.model_validate(EXAMPLE_CLIENT), top_n=10)
    top = result.explanation.top
    assert len(top) == 10
    sizes = [abs(c.contribution) for c in top]
    assert sizes == sorted(sizes, reverse=True)
    total = result.explanation.base_value + sum(c.contribution for c in top)
    total += result.explanation.others
    assert total == pytest.approx(logit(result.prob_default), abs=1e-6)


def test_explain_drapeaux_sensible_et_derive(api_artifacts: Path) -> None:
    model = load_model(api_artifacts)
    n = len(model.features.model_columns)
    result = explain(model, ClientFeatures.model_validate(EXAMPLE_CLIENT), top_n=n)
    by_name = {c.feature: c for c in result.explanation.top}
    assert result.explanation.others == 0
    assert by_name["CODE_GENDER"].sensitive and not by_name["CODE_GENDER"].derived
    autofe = [c for c in by_name.values() if c.feature.startswith("autoFE_")]
    assert autofe and all(c.derived and not c.sensitive for c in autofe)
    assert by_name["CODE_GENDER"].value == EXAMPLE_CLIENT["CODE_GENDER"]


def test_explain_valeurs_nulles_sans_erreur(api_artifacts: Path) -> None:
    model = load_model(api_artifacts)
    client = ClientFeatures.model_validate(with_nulls())
    n = len(model.features.model_columns)
    result = explain(model, client, top_n=n)
    by_name = {c.feature: c for c in result.explanation.top}
    for name in sorted(NULLABLE_FEATURES)[:3]:
        assert by_name[name].value is None
    total = result.explanation.base_value + sum(c.contribution for c in result.explanation.top)
    assert total == pytest.approx(logit(result.prob_default), abs=1e-6)


def test_explain_mesure_le_temps_d_inference(api_artifacts: Path) -> None:
    model = load_model(api_artifacts)
    timings: dict[str, float] = {}
    explain(model, ClientFeatures.model_validate(EXAMPLE_CLIENT), timings=timings)
    assert timings["inference_ms"] > 0


# --- politique ------------------------------------------------------------------------


def test_attributs_sensibles_existent_dans_features_json(api_artifacts: Path) -> None:
    source = REAL_ARTIFACTS if (REAL_ARTIFACTS / "features.json").is_file() else api_artifacts
    spec = json.loads((source / "features.json").read_text(encoding="utf-8"))
    assert fairness.SENSITIVE_FEATURES
    for name, reason in fairness.SENSITIVE_FEATURES.items():
        assert name in spec["model_columns"]
        assert reason


# --- route ----------------------------------------------------------------------------


def test_route_explain_renvoie_score_et_explication(client: TestClient) -> None:
    response = client.post("/predict/explain", json=EXAMPLE_CLIENT, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    plain = client.post("/predict", json=EXAMPLE_CLIENT, headers=AUTH).json()
    assert body["prob_default"] == pytest.approx(plain["prob_default"])
    assert body["sk_id_curr"] is None
    assert len(body["explanation"]["top"]) == 10
    assert {"base_value", "top", "others"} <= body["explanation"].keys()


def test_route_explain_exige_la_cle(client: TestClient) -> None:
    assert client.post("/predict/explain", json=EXAMPLE_CLIENT).status_code == 401


def test_route_explain_meme_validation(client: TestClient) -> None:
    response = client.post(
        "/predict/explain", json={**EXAMPLE_CLIENT, "CNT_FAM_MEMBERS": 0}, headers=AUTH
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "CNT_FAM_MEMBERS"


def test_route_explain_avec_valeurs_nulles(client: TestClient) -> None:
    response = client.post("/predict/explain", json=with_nulls(), headers=AUTH)
    assert response.status_code == 200


def test_route_demo_toujours_disponible(client: TestClient) -> None:
    from tests.conftest import DEMO_VALID_ID

    assert client.post(f"/predict/{DEMO_VALID_ID}", headers=AUTH).status_code == 200


# --- journalisation -------------------------------------------------------------------


def test_logged_path_reconnait_explain() -> None:
    scope = {"type": "http", "method": "POST", "path": "/predict/explain"}
    assert logged_path(scope) == "/predict/explain"
    assert logged_path({**scope, "path": "/predict/explain/"}) is None  # 404 : non journalisé


def test_appel_explain_journalise(
    api_artifacts: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'logs.db'}"
    db.run_migrations(url)
    monkeypatch.setenv("MODEL_DIR", str(api_artifacts))
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.setenv("DATABASE_URL", url)
    get_model.cache_clear()
    with TestClient(app) as c:
        c.post("/predict/explain", json=EXAMPLE_CLIENT, headers=AUTH)
    get_model.cache_clear()
    engine = db.make_engine(url)
    with engine.connect() as conn:
        (row,) = list(conn.execute(sa.select(prediction_logs)))
    engine.dispose()
    assert row.path == "/predict/explain"
    assert row.status_code == 200
    assert row.features == EXAMPLE_CLIENT
    assert row.prob_default is not None
    assert row.inference_ms is not None and row.inference_ms > 0


def test_explain_encode_le_client_une_seule_fois(
    api_artifacts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from credit_scoring.model import ScoringModel

    calls: list[int] = []
    original = ScoringModel.encode

    def counting(self: ScoringModel, frame: pd.DataFrame) -> Any:
        calls.append(1)
        return original(self, frame)

    monkeypatch.setattr(ScoringModel, "encode", counting)
    model = load_model(api_artifacts)
    explain(model, ClientFeatures.model_validate(EXAMPLE_CLIENT))
    assert len(calls) == 1
