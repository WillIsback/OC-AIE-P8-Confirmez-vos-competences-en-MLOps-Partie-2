"""Client HTTP interne : l'interface appelle la vraie route `/predict/explain`.

Transport ASGI, sans réseau : chaque score traverse la validation, le middleware de
journalisation (source `ui-demo`, #16) et la route, comme un appel extérieur. La clé d'API
reste côté serveur (lue dans `app.state` à chaque appel) et n'atteint jamais le navigateur.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from fastapi import FastAPI

CLIENT_HEADER = {"X-Client": "ui-demo"}


class ApiError(Exception):
    """Réponse non 200 de l'API : statut et détail (liste d'erreurs pour un 422)."""

    def __init__(self, status: int, details: list[dict[str, Any]] | str) -> None:
        super().__init__(f"{status}: {details}")
        self.status = status
        self.details = details


class ApiClient:
    def __init__(self, http: httpx.AsyncClient, api_key: Callable[[], str]) -> None:
        self.http = http
        self.api_key = api_key

    async def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"X-API-Key": self.api_key(), **CLIENT_HEADER}
        response = await self.http.post(path, json=body, headers=headers)
        if response.status_code == 200:
            result: dict[str, Any] = response.json()
            return result
        try:
            details = response.json().get("detail", response.text)
        except ValueError:
            details = response.text
        raise ApiError(response.status_code, details)

    async def explain(self, features: dict[str, Any]) -> dict[str, Any]:
        """Score et explication locale (`POST /predict/explain`)."""
        return await self._post("/predict/explain", features)


def internal_client(app: FastAPI) -> ApiClient:
    """Client de l'application elle-même (transport ASGI, aucun réseau)."""
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://ui.internal", timeout=30
    )
    return ApiClient(http, lambda: str(app.state.api_key))
