"""Fixtures communes : artefacts de modèle miniatures, construits sans réseau."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pytest

# Ordre d'entrée (comme la signature P6) différent de l'ordre vu par le modèle
# (catégorielles d'abord, puis le reste) : c'est le piège que le module doit gérer.
INPUT_FEATURES = ["AMT_CREDIT", "CODE_GENDER", "DAYS_REGISTRATION"]
CATEGORIES = {"CODE_GENDER": ["F", "M", "XNA"]}
MODEL_COLUMNS = ["CODE_GENDER", "AMT_CREDIT", "DAYS_REGISTRATION"]
THRESHOLD = 0.5


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="session")
def tiny_artifacts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Dossier d'artefacts au format de production, avec un LightGBM entraîné en 1 s."""
    out = tmp_path_factory.mktemp("artifacts")
    rng = np.random.default_rng(0)
    n = 400
    gender = rng.integers(0, 3, n).astype(float)
    credit = rng.uniform(1e5, 1e6, n)
    days = rng.uniform(-10_000, 0, n)
    x = np.column_stack([gender, credit, days])
    y = (credit > 5e5).astype(int)
    booster = lgb.train(
        {"objective": "binary", "verbose": -1, "num_leaves": 4, "seed": 0},
        lgb.Dataset(x, y),
        num_boost_round=10,
    )
    booster.save_model(str(out / "model.txt"))
    (out / "features.json").write_text(
        json.dumps(
            {
                "input_features": INPUT_FEATURES,
                "categories": CATEGORIES,
                "model_columns": MODEL_COLUMNS,
                "numeric_bounds": {
                    "AMT_CREDIT": {"min": 1e5, "max": 1e6},
                    "DAYS_REGISTRATION": {"min": -10_000.0, "max": 0.0},
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "model_name": "test-model",
        "model_version": "1",
        "threshold": THRESHOLD,
        "files": {name: _sha256(out / name) for name in ("model.txt", "features.json")},
    }
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return out


# --- API : modèle synthétique sur les 122 vraies features -----------------------------

API_KEY = "cle-de-test"  # valeur factice des tests
DEMO_VALID_ID = 100001
DEMO_NULLABLE_ID = 100002
DEMO_INVALID_ID = 100003


@pytest.fixture(scope="session")
def api_artifacts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Artefacts au contrat réel (122 features), modèle entraîné sur des données synthétiques.

    Les données tournent autour du client d'exemple synthétique ; la cible ne dépend que de
    `AMT_CREDIT` (crédit au-dessus de la médiane → défaut), pour tester les deux décisions.
    `sample_clients.csv` contient un client valide, un avec des NaN sur des features
    nullables et un qui viole une règle métier.
    """
    import pandas as pd
    from pydantic import BaseModel

    from credit_scoring.api.features_schema import (
        EXAMPLE_CLIENT,
        FEATURE_ORDER,
        NULLABLE_FEATURES,
        GeneratedFeatures,
    )

    def literal_values(cls: type[BaseModel], name: str) -> list[str]:
        from typing import get_args

        return [str(v) for v in get_args(cls.model_fields[name].annotation)]

    out = tmp_path_factory.mktemp("api_artifacts")
    categories = {
        c: literal_values(GeneratedFeatures, c)
        for c in FEATURE_ORDER
        if isinstance(EXAMPLE_CLIENT[c], str)
    }
    numeric = [c for c in FEATURE_ORDER if c not in categories]
    model_columns = [*categories, *numeric]

    rng = np.random.default_rng(0)
    n = 400
    columns: list[np.ndarray] = []
    data: dict[str, np.ndarray] = {}
    for c in categories:
        columns.append(rng.integers(0, len(categories[c]), n).astype(float))
    for c in numeric:
        centre = float(EXAMPLE_CLIENT[c])
        data[c] = centre + rng.normal(0, max(abs(centre) * 0.5, 1.0), n)
        columns.append(data[c])
    y = (data["AMT_CREDIT"] > float(EXAMPLE_CLIENT["AMT_CREDIT"])).astype(int)
    booster = lgb.train(
        {"objective": "binary", "verbose": -1, "num_leaves": 4, "seed": 0},
        lgb.Dataset(np.column_stack(columns), y),
        num_boost_round=20,
    )
    booster.save_model(str(out / "model.txt"))

    bounds = {
        c: {
            "min": min(float(data[c].min()), float(EXAMPLE_CLIENT[c])),
            "max": max(float(data[c].max()), float(EXAMPLE_CLIENT[c])),
        }
        for c in numeric
    }
    bounds["AMT_CREDIT"] = {"min": 45_000.0, "max": 4_050_000.0}
    (out / "features.json").write_text(
        json.dumps(
            {
                "input_features": list(FEATURE_ORDER),
                "categories": categories,
                "model_columns": model_columns,
                "numeric_bounds": bounds,
            }
        ),
        encoding="utf-8",
    )

    valid = dict(EXAMPLE_CLIENT)
    with_nan = {**EXAMPLE_CLIENT, **dict.fromkeys(sorted(NULLABLE_FEATURES)[:3], np.nan)}
    invalid = {**EXAMPLE_CLIENT, "CNT_FAM_MEMBERS": 0.0}
    sample = pd.DataFrame([valid, with_nan, invalid], columns=list(FEATURE_ORDER))
    sample.insert(0, "SK_ID_CURR", [DEMO_VALID_ID, DEMO_NULLABLE_ID, DEMO_INVALID_ID])
    sample.to_csv(out / "sample_clients.csv", index=False)

    files = ("model.txt", "features.json", "sample_clients.csv")
    manifest = {
        "model_name": "test-model",
        "model_version": "1",
        "threshold": THRESHOLD,
        "files": {name: _sha256(out / name) for name in files},
    }
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return out
