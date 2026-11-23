"""Échantillon de référence de la dérive, tiré du train de P6 (#17)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from scripts import export_drift_reference as edr

from credit_scoring.api.features_schema import FEATURE_ORDER
from credit_scoring.model import load_model
from tests.synthetic import clients


@pytest.fixture
def train_csv(api_artifacts: Path, tmp_path: Path) -> Path:
    model = load_model(api_artifacts)
    frame = clients(1000, model.features.categories)
    frame["TARGET"] = (np.arange(1000) < 80).astype(int)  # 8 % de défauts, comme Home Credit
    path = tmp_path / "train_fs.csv"
    frame.to_csv(path, index=False)
    return path


def test_echantillon_stratifie_sans_cible(api_artifacts: Path, train_csv: Path) -> None:
    model = load_model(api_artifacts)
    sample = edr.sample(train_csv, model, n=200, seed=42)
    assert len(sample) == 200
    assert list(sample.columns) == [*FEATURE_ORDER, "prob_default"]
    assert "TARGET" not in sample.columns
    full = pd.read_csv(train_csv)
    picked = full.loc[sample.index, "TARGET"]
    assert picked.sum() == 16  # 8 % de 200 : stratification exacte


def test_score_de_reference_du_meme_modele(api_artifacts: Path, train_csv: Path) -> None:
    model = load_model(api_artifacts)
    sample = edr.sample(train_csv, model, n=100, seed=1)
    expected = model.predict(sample[list(FEATURE_ORDER)])["prob_default"]
    np.testing.assert_allclose(sample["prob_default"], expected)


def test_tirage_reproductible(api_artifacts: Path, train_csv: Path) -> None:
    model = load_model(api_artifacts)
    a = edr.sample(train_csv, model, n=100, seed=7)
    b = edr.sample(train_csv, model, n=100, seed=7)
    assert a.index.tolist() == b.index.tolist()


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def create_repo(self, **kw: Any) -> None:
        self.calls.append(("create_repo", kw))

    def upload_file(self, **kw: Any) -> None:
        self.calls.append(("upload_file", kw))


def test_envoi_dans_un_dataset_prive(api_artifacts: Path, train_csv: Path) -> None:
    model = load_model(api_artifacts)
    api = FakeApi()
    edr.publish(edr.sample(train_csv, model, n=100), api, "moi/ref", model.version)
    (name, create), (name2, upload) = api.calls
    assert name == "create_repo" and create["private"] is True
    assert create["repo_type"] == "dataset"
    assert name2 == "upload_file" and upload["path_in_repo"] == edr.REFERENCE_FILE
    table = pd.read_parquet(upload["path_or_fileobj"])
    assert len(table) == 100
