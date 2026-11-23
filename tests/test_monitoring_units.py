"""Briques du middleware et de l'enregistrement, hors application (#16)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from credit_scoring.monitoring import record
from credit_scoring.monitoring.middleware import _buffer, logged_path


@pytest.mark.parametrize(
    ("scope", "attendu"),
    [
        ({"type": "http", "method": "POST", "path": "/predict"}, "/predict"),
        # Barre finale : FastAPI répond 307 vers /predict, qui sera journalisé (#45, M2).
        ({"type": "http", "method": "POST", "path": "/predict/"}, None),
        ({"type": "http", "method": "POST", "path": "/predict/explain/"}, None),
        ({"type": "http", "method": "POST", "path": "/predict/42"}, "/predict/{sk_id_curr}"),
        ({"type": "http", "method": "POST", "path": "/predict/42/x"}, None),
        ({"type": "http", "method": "POST", "path": "/predictions"}, None),
        ({"type": "http", "method": "GET", "path": "/predict"}, None),
        ({"type": "websocket", "path": "/predict"}, None),
    ],
)
def test_routes_journalisees(scope: dict[str, Any], attendu: str | None) -> None:
    assert logged_path(scope) == attendu


def test_corps_en_plusieurs_morceaux_puis_rejeu() -> None:
    messages: list[dict[str, Any]] = [
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"cd", "more_body": False},
        {"type": "http.disconnect"},
    ]
    feed = iter(messages)

    async def receive() -> dict[str, Any]:
        return next(feed)

    async def scenario() -> tuple[bytes, list[Any]]:
        body, replay = await _buffer(receive)
        return body, [await replay(), await replay(), await replay()]

    body, replayed = asyncio.run(scenario())
    assert body == b"abcd"
    assert replayed == messages  # deux messages rejoués, puis le receive d'origine


def test_deconnexion_avant_la_fin_du_corps() -> None:
    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    body, _ = asyncio.run(_buffer(receive))
    assert body == b""


@pytest.mark.parametrize(
    ("status", "attendu"),
    [(200, None), (401, "unauthorized"), (404, "not_found"), (422, "validation"),
     (405, "client_error"), (500, "internal"), (503, "internal")],
)  # fmt: skip
def test_type_d_erreur(status: int, attendu: str | None) -> None:
    assert record.error_type(status) == attendu


def test_422_reponse_illisible() -> None:
    row = record.build(
        request_id=uuid.uuid4(),
        created_at=datetime.now(UTC),
        source="api",
        path="/predict",
        api_version="0",
        model_version=None,
        status_code=422,
        latency_ms=1.0,
        state={},
        body=b'{"a": ["x\\u0000"]}',
        response_body=b"<html>",
    )
    assert row["error_detail"] is None
    assert row["features"] == {"a": ["x\ufffd"]}  # caractère nul refusé par JSONB
