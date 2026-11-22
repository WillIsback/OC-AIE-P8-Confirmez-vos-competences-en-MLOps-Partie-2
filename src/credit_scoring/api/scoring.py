"""Du client validé à la réponse : avertissements de bornes, prédiction, échantillon de démo."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from credit_scoring.api.features_schema import FEATURE_ORDER
from credit_scoring.api.schemas import ClientFeatures, FeatureWarning, PredictionResponse
from credit_scoring.model import ScoringModel

SAMPLE_FILE = "sample_clients.csv"


def out_of_bounds(
    values: dict[str, Any], bounds: dict[str, dict[str, float]]
) -> list[FeatureWarning]:
    """Features numériques hors des bornes [min ; max] du jeu d'entraînement (bornes incluses)."""
    warnings: list[FeatureWarning] = []
    for feature in FEATURE_ORDER:
        value = values.get(feature)
        limits = bounds.get(feature)
        if limits is None or not isinstance(value, int | float):
            continue
        low, high = limits["min"], limits["max"]
        if not low <= value <= high:
            warnings.append(
                FeatureWarning(
                    feature=feature,
                    value=float(value),
                    min=low,
                    max=high,
                    message=f"{feature} = {float(value)} hors des bornes du jeu "
                    f"d'entraînement [{low} ; {high}]",
                )
            )
    return warnings


def score(
    model: ScoringModel, client: ClientFeatures, sk_id_curr: int | None = None
) -> PredictionResponse:
    """Prédit pour un client déjà validé."""
    values = client.model_dump()
    frame = pd.DataFrame([values], columns=list(FEATURE_ORDER))
    row = model.predict(frame).iloc[0]
    return PredictionResponse(
        sk_id_curr=sk_id_curr,
        prob_default=float(row["prob_default"]),
        decision="refusé" if int(row["decision"]) == 1 else "accordé",
        threshold=model.threshold,
        model_version=model.version,
        warnings=out_of_bounds(values, model.features.numeric_bounds),
    )


def load_demo_clients(model_dir: Path) -> dict[int, dict[str, Any]]:
    """Clients de démo (non validés) indexés par SK_ID_CURR ; NaN → None."""
    frame = pd.read_csv(model_dir / SAMPLE_FILE)
    clients: dict[int, dict[str, Any]] = {}
    for record in frame.to_dict(orient="records"):
        sk_id = int(record.pop("SK_ID_CURR"))
        clients[sk_id] = {
            str(k): None if isinstance(v, float) and math.isnan(v) else v for k, v in record.items()
        }
    return clients
