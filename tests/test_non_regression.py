"""Non-régression contre P6 : le test le plus important du projet (ADR-002).

Compare, sur 1 000 clients figés du jeu de test, les scores du module de P8 aux scores
calculés par le modèle `home-credit-serving` v2 de P6 (fichier de référence produit par
`scripts/export_p6_artifacts.py`). Nécessite les artefacts réels dans `MODEL_DIR`
(`artifacts/` par défaut, téléchargés par `scripts/fetch_model.py`).
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from credit_scoring.model import load_model

pytestmark = pytest.mark.integration

TOLERANCE = 1e-9


@pytest.fixture(scope="module")
def model_dir() -> Path:
    path = Path(os.environ.get("MODEL_DIR", "artifacts"))
    if not (path / "manifest.json").is_file():
        pytest.fail(f"Artefacts réels absents de {path} : lancer scripts/fetch_model.py")
    return path


def test_scores_identiques_a_p6(model_dir: Path) -> None:
    model = load_model(model_dir)
    cat_dtypes = dict.fromkeys(model.features.categories, "string")
    # pandas 3 relit les flottants à l'identique (aller-retour exact)
    clients = pd.read_csv(model_dir / "sample_clients.csv", dtype=cat_dtypes)
    reference = pd.read_csv(model_dir / "reference_predictions.csv")
    assert len(clients) == len(reference) == 1_000
    assert (clients["SK_ID_CURR"] == reference["SK_ID_CURR"]).all()

    predicted = model.predict(clients)

    ecart = (predicted["prob_default"] - reference["prob_default"]).abs().max()
    assert ecart <= TOLERANCE, f"écart max {ecart:.3e} > {TOLERANCE}"
    assert (predicted["decision"] == reference["decision"]).all()


def test_seuil_et_tracabilite(model_dir: Path) -> None:
    model = load_model(model_dir)
    assert model.version == "home-credit-serving v2"
    assert model.threshold == pytest.approx(0.5348, abs=1e-4)
    assert model.manifest["fn_cost"] == 10 * model.manifest["fp_cost"]
    assert model.manifest["validation"]["same_decisions"] is True
    assert len(model.features.input_features) == 122
