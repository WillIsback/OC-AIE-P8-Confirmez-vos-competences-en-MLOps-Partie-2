"""Client HTTP interne de l'interface : la vraie route /predict, sans réseau (#40)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from credit_scoring.api.app import app
from credit_scoring.api.features_schema import EXAMPLE_CLIENT
from credit_scoring.model import get_model
from credit_scoring.ui.client import CLIENT_HEADER, ApiClient, ApiError, internal_client
from tests.conftest import API_KEY, DEMO_VALID_ID


@pytest.fixture
def client(api_artifacts: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiClient]:
    monkeypatch.setenv("MODEL_DIR", str(api_artifacts))
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_model.cache_clear()
    with TestClient(app):  # lifespan : modèle, clé et clients de démo chargés
        yield internal_client(app)
    get_model.cache_clear()


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_client_demo_valide(client: ApiClient) -> None:
    prediction = run(client.predict_demo(DEMO_VALID_ID))
    assert prediction["decision"] in {"accordé", "refusé"}
    assert prediction["sk_id_curr"] == DEMO_VALID_ID


def test_client_inconnu_404(client: ApiClient) -> None:
    with pytest.raises(ApiError) as err:
        run(client.predict_demo(999))
    assert err.value.status == 404


def test_regle_violee_422_restituee(client: ApiClient) -> None:
    with pytest.raises(ApiError) as err:
        run(client.predict({**EXAMPLE_CLIENT, "CNT_FAM_MEMBERS": 0}))
    assert err.value.status == 422
    assert isinstance(err.value.details, list)
    assert err.value.details[0]["loc"][-1] == "CNT_FAM_MEMBERS"


def test_hors_bornes_avertissement(client: ApiClient) -> None:
    prediction = run(client.predict({**EXAMPLE_CLIENT, "AMT_CREDIT": 5_000_000.0}))
    assert [w["feature"] for w in prediction["warnings"]] == ["AMT_CREDIT"]


def mock_client(handler: Any) -> ApiClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ui.internal")
    return ApiClient(http, lambda: "cle-fournie")


def test_cle_et_source_envoyees() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"decision": "accordé"})

    run(mock_client(handler).predict(EXAMPLE_CLIENT))
    assert seen[0].headers["X-API-Key"] == "cle-fournie"
    assert seen[0].headers["X-Client"] == CLIENT_HEADER["X-Client"] == "ui-demo"
    assert seen[0].url.path == "/predict"


def test_statut_inattendu_texte_brut() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    with pytest.raises(ApiError) as err:
        run(mock_client(handler).predict_demo(1))
    assert (err.value.status, err.value.details) == (500, "Internal Server Error")


def test_statut_inattendu_detail_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "indisponible"})

    with pytest.raises(ApiError) as err:
        run(mock_client(handler).predict_demo(1))
    assert err.value.details == "indisponible"
