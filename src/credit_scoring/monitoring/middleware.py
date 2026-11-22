"""Middleware ASGI : un enregistrement par appel `POST /predict…` (spec #16, §5)."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from credit_scoring import __version__
from credit_scoring.monitoring import record

DEMO_PATH = "/predict/{sk_id_curr}"
_errors = logging.getLogger(__name__)


def logged_path(scope: Scope) -> str | None:
    """Gabarit de la route journalisée, ou `None` si l'appel n'est pas une prédiction."""
    if scope["type"] != "http" or scope["method"] != "POST":
        return None
    path = str(scope["path"]).rstrip("/")
    if path == "/predict":
        return path
    if path.startswith("/predict/") and path.count("/") == 2:
        return DEMO_PATH
    return None


async def _buffer(receive: Receive) -> tuple[bytes, Receive]:
    """Lit tout le corps, puis rejoue les messages à l'application."""
    messages: list[Message] = []
    chunks: list[bytes] = []  # join final : linéaire (`body += chunk` serait quadratique)
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    body = b"".join(chunks)
    pending = iter(messages)

    async def replay() -> Message:
        try:
            return next(pending)
        except StopIteration:
            return await receive()

    return body, replay


class PredictionLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = logged_path(scope)
        writer = getattr(scope["app"].state, "log_writer", None) if "app" in scope else None
        if path is None or writer is None:
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        created_at = datetime.now(UTC)
        request_id = uuid.uuid4()
        body, replay = await _buffer(receive)
        state: dict[str, Any] = scope.setdefault("state", {})
        status_code = 500
        response_body = b""

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_body
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = str(request_id)
            elif message["type"] == "http.response.body" and status_code == 422:
                response_body += message.get("body", b"")
            await send(message)

        try:
            await self.app(scope, replay, send_wrapper)
        finally:
            try:
                model = getattr(scope["app"].state, "model", None)
                entry = record.build(
                    request_id=request_id,
                    created_at=created_at,
                    source=record.source(Headers(scope=scope).get("x-client")),
                    path=path,
                    api_version=__version__,
                    model_version=getattr(model, "version", None),
                    status_code=status_code,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    state=state,
                    body=body,
                    response_body=response_body,
                )
                writer.submit(entry)
            except Exception as exc:  # la journalisation n'atteint jamais la réponse
                _errors.warning("Journalisation impossible (%s)", type(exc).__name__)
