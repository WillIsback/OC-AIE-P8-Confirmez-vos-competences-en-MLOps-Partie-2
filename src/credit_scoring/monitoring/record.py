"""Construction d'un enregistrement `prediction_logs` à partir d'un appel (spec #16, §4)."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Any

SOURCES = frozenset({"api", "ui-demo", "ci"})
MAX_BODY_BYTES = 65_536
ERROR_TYPES = {401: "unauthorized", 404: "not_found", 422: "validation"}


def source(header: str | None) -> str:
    """Valeur de `X-Client` si elle est connue, `api` sinon (simple tri, pas une auth)."""
    return header if header in SOURCES else "api"


def client_ref(api_key: str, sk_id_curr: int) -> str:
    """Pseudonyme stable de `SK_ID_CURR` (HMAC-SHA256) ; l'identifiant brut n'est jamais stocké."""
    key = b"client_ref:" + api_key.encode()
    return hmac.new(key, str(sk_id_curr).encode(), hashlib.sha256).hexdigest()


def error_type(status_code: int) -> str | None:
    if status_code >= 500:
        return "internal"
    return ERROR_TYPES.get(status_code, "client_error" if status_code >= 400 else None)


def _sanitize(value: Any) -> Any:
    """Caractère nul remplacé (refusé par JSONB dans les chaînes)."""
    if isinstance(value, str):
        return value.replace("\x00", "�")
    if isinstance(value, dict):
        return {_sanitize(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def received_body(body: bytes) -> Any:
    """Corps reçu tel qu'il sera stocké pour une requête invalide (422)."""
    if len(body) > MAX_BODY_BYTES:
        return {"_raw": f"<tronqué, {len(body)} octets>"}
    try:
        return _sanitize(json.loads(body))
    except ValueError:
        return {"_raw": f"<non-JSON, {len(body)} octets>"}


def build(
    *,
    request_id: uuid.UUID,
    created_at: datetime,
    source: str,
    path: str,
    api_version: str,
    model_version: str | None,
    status_code: int,
    latency_ms: float,
    state: dict[str, Any],
    body: bytes,
    response_body: bytes,
) -> dict[str, Any]:
    """Enregistrement complet ; `state` vient des routes (features, prédiction, temps)."""
    prediction = state.get("prediction")
    features = state.get("features")
    error_detail = None
    if status_code == 422:
        features = received_body(body)
        try:
            error_detail = json.loads(response_body).get("detail")
        except (ValueError, AttributeError):
            error_detail = None
    warnings = (
        [
            {"feature": w.feature, "value": w.value, "importance_rank": w.importance_rank}
            for w in prediction.warnings
        ]
        if prediction is not None
        else None
    )
    return {
        "request_id": request_id,
        "created_at": created_at,
        "source": source,
        "path": path,
        "api_version": api_version,
        "model_version": model_version,
        "client_ref": state.get("client_ref"),
        "features": features if status_code != 401 else None,
        "prob_default": prediction.prob_default if prediction is not None else None,
        "decision": prediction.decision if prediction is not None else None,
        "threshold": prediction.threshold if prediction is not None else None,
        "warnings": warnings,
        "n_warnings": len(warnings) if warnings is not None else None,
        "latency_ms": latency_ms,
        "inference_ms": state.get("inference_ms"),
        "status_code": status_code,
        "error_type": error_type(status_code),
        "error_detail": error_detail,
    }
