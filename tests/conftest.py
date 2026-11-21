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
