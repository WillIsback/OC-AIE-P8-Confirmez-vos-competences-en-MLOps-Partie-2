"""Journalisation de chaque appel de scoring, de bout en bout sur l'app (#16)."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from credit_scoring.api import app as app_module
from credit_scoring.api.app import app
from credit_scoring.api.features_schema import EXAMPLE_CLIENT
from credit_scoring.model import get_model
from credit_scoring.monitoring import db
from credit_scoring.monitoring.schema import prediction_logs
from tests.conftest import API_KEY, DEMO_VALID_ID

AUTH = {"X-API-Key": API_KEY}


@pytest.fixture
def env(api_artifacts: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    url = f"sqlite:///{tmp_path / 'logs.db'}"
    db.run_migrations(url)
    monkeypatch.setenv("MODEL_DIR", str(api_artifacts))
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.setenv("DATABASE_URL", url)
    get_model.cache_clear()
    yield url
    get_model.cache_clear()


def logs(url: str) -> list[Any]:
    engine = db.make_engine(url)
    with engine.connect() as conn:
        result = list(conn.execute(sa.select(prediction_logs).order_by(prediction_logs.c.id)))
    engine.dispose()
    return result


def call(url: str, *requests: tuple[str, dict[str, Any]]) -> list[Any]:
    """Envoie les requêtes, arrête l'app (vidage de la file), renvoie les lignes."""
    with TestClient(app, raise_server_exceptions=False) as client:
        for path, kwargs in requests:
            client.post(path, **kwargs)
    return logs(url)


def test_prediction_valide_journalisee(env: str) -> None:
    (row,) = call(env, ("/predict", {"json": EXAMPLE_CLIENT, "headers": AUTH}))
    assert row.status_code == 200
    assert row.source == "api"
    assert row.path == "/predict"
    assert row.features == EXAMPLE_CLIENT
    assert row.decision in {"accordé", "refusé"}
    assert 0 <= row.prob_default <= 1
    assert row.inference_ms > 0
    assert row.latency_ms >= row.inference_ms
    assert row.client_ref is None
    assert row.error_type is None
    assert row.model_version
    assert row.n_warnings == 0


def test_route_de_demo_pseudonymise_l_identifiant(env: str) -> None:
    (row,) = call(env, (f"/predict/{DEMO_VALID_ID}", {"headers": AUTH}))
    attendu = hmac.new(
        b"client_ref:" + API_KEY.encode(), str(DEMO_VALID_ID).encode(), hashlib.sha256
    ).hexdigest()
    assert row.client_ref == attendu
    assert row.path == "/predict/{sk_id_curr}"
    assert str(DEMO_VALID_ID) not in str(row._mapping.values())


@pytest.mark.parametrize(
    ("header", "source"), [("ui-demo", "ui-demo"), ("ci", "ci"), ("autre", "api")]
)
def test_source(env: str, header: str, source: str) -> None:
    headers = {**AUTH, "X-Client": header}
    (row,) = call(env, ("/predict", {"json": EXAMPLE_CLIENT, "headers": headers}))
    assert row.source == source


def test_avertissements_journalises(env: str) -> None:
    body = {**EXAMPLE_CLIENT, "AMT_CREDIT": 5_000_000.0}
    (row,) = call(env, ("/predict", {"json": body, "headers": AUTH}))
    assert row.n_warnings == 1
    assert row.warnings[0]["feature"] == "AMT_CREDIT"


def test_401_sans_corps(env: str) -> None:
    (row,) = call(env, ("/predict", {"json": EXAMPLE_CLIENT}))
    assert row.status_code == 401
    assert row.error_type == "unauthorized"
    assert row.features is None


def test_404(env: str) -> None:
    (row,) = call(env, ("/predict/999", {"headers": AUTH}))
    assert (row.status_code, row.error_type) == (404, "not_found")


def test_422_corps_et_detail(env: str) -> None:
    body = {**EXAMPLE_CLIENT, "CNT_FAM_MEMBERS": 0}
    (row,) = call(env, ("/predict", {"json": body, "headers": AUTH}))
    assert (row.status_code, row.error_type) == (422, "validation")
    assert row.features["CNT_FAM_MEMBERS"] == 0
    assert row.error_detail[0]["loc"][-1] == "CNT_FAM_MEMBERS"
    assert row.prob_default is None


def test_422_corps_non_json(env: str) -> None:
    headers = {**AUTH, "Content-Type": "application/json"}
    (row,) = call(env, ("/predict", {"content": b"\x00pas du json", "headers": headers}))
    assert row.status_code == 422
    assert row.features == {"_raw": "<non-JSON, 12 octets>"}


def test_422_corps_trop_gros(env: str) -> None:
    body = {**EXAMPLE_CLIENT, "inconnu": "x" * 70_000}
    (row,) = call(env, ("/predict", {"json": body, "headers": AUTH}))
    assert row.status_code == 422
    assert row.features["_raw"].startswith("<tronqué")


def test_erreur_interne_journalisee(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("panne")

    monkeypatch.setattr(app_module, "score", boom)
    (row,) = call(env, ("/predict", {"json": EXAMPLE_CLIENT, "headers": AUTH}))
    assert (row.status_code, row.error_type) == (500, "internal")
    assert row.features == EXAMPLE_CLIENT


def test_routes_hors_scoring_non_journalisees(env: str) -> None:
    with TestClient(app) as client:
        client.get("/health")
        client.get("/docs")
        client.get("/predict")  # GET : pas une prédiction (405)
    assert logs(env) == []


def test_request_id_renvoye(env: str) -> None:
    with TestClient(app) as client:
        response = client.post("/predict", json=EXAMPLE_CLIENT, headers=AUTH)
    (row,) = logs(env)
    assert response.headers["X-Request-ID"] == str(row.request_id)


def test_base_en_panne_prediction_intacte(
    tmp_path: Path, env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'sans-table.db'}")
    with TestClient(app) as client:
        response = client.post("/predict", json=EXAMPLE_CLIENT, headers=AUTH)
        assert response.status_code == 200
        deadline = time.monotonic() + 5
        while client.get("/health").json()["logging"]["dropped"] < 1:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert client.get("/health").json()["logging"]["database"] is True


def test_sans_base_stdout_seulement(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    with TestClient(app) as client:
        assert client.post("/predict", json=EXAMPLE_CLIENT, headers=AUTH).status_code == 200
        assert client.get("/health").json()["logging"] == {"database": False, "dropped": 0}


def test_score_sans_mesure_du_temps(env: str) -> None:
    from credit_scoring.api.schemas import ClientFeatures
    from credit_scoring.api.scoring import score

    prediction = score(get_model(), ClientFeatures.model_validate(EXAMPLE_CLIENT))
    assert prediction.decision in {"accordé", "refusé"}
