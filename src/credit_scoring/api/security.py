"""Clé d'API (ADR-003) : en-tête `X-API-Key`, comparée en temps constant."""

from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

API_KEY_ENV = "API_KEY"
UNAUTHORIZED = "Clé d'API absente ou invalide (en-tête X-API-Key)."

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def configured_api_key() -> str:
    """Clé attendue, lue au démarrage. Sans clé, le service refuse de démarrer."""
    key = os.environ.get(API_KEY_ENV, "")
    if not key:
        raise RuntimeError(f"Variable d'environnement {API_KEY_ENV} absente ou vide")
    return key


def require_api_key(request: Request, key: str | None = Security(api_key_header)) -> None:
    """401 si la clé est absente ou fausse, comparée en temps constant (`compare_digest`)."""
    expected: str = request.app.state.api_key
    if not key or not secrets.compare_digest(key.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UNAUTHORIZED,
            headers={"WWW-Authenticate": "ApiKey"},
        )
