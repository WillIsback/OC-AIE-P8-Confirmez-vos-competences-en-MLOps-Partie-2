"""Échantillon de référence de la dérive (#17) : train de P6 → dataset Hugging Face privé.

    uv run python scripts/export_drift_reference.py --train <P6>/data/processed/train_fs.csv \\
        [--n 20000] [--seed 42] [--dry-run]

Tirage stratifié sur `TARGET` (8 % de défauts conservés), `TARGET` retirée : les
122 features brutes, au format de l'API, plus `prob_default`, le score du modèle servi sur
chaque ligne (référence de la dérive des scores). Le Parquet part dans le dataset **privé**
`WillIsback/credit-scoring-drift-reference` : jamais dans Git ni dans l'image (données
Kaggle). Variables : `HF_TOKEN` (écriture), `MODEL_DIR` (artefacts, `artifacts/` sinon).
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from credit_scoring.api.features_schema import FEATURE_ORDER  # noqa: E402
from credit_scoring.model import ScoringModel, load_model, model_dir  # noqa: E402

REPO_ID = "WillIsback/credit-scoring-drift-reference"
REFERENCE_FILE = "reference.parquet"
TARGET = "TARGET"


def sample(train_csv: Path, model: ScoringModel, n: int = 20_000, seed: int = 42) -> pd.DataFrame:
    """Tirage stratifié de `n` lignes (répartition de `TARGET` respectée), score ajouté."""
    train = pd.read_csv(train_csv, usecols=[*FEATURE_ORDER, TARGET])
    rng = np.random.default_rng(seed)
    shares = train[TARGET].value_counts(normalize=True).sort_index()
    sizes = (shares * n).round().astype(int)
    sizes.iloc[-1] = n - int(sizes.iloc[:-1].sum())  # total exact
    picked = [
        rng.choice(train.index[train[TARGET] == label].to_numpy(), size=size, replace=False)
        for label, size in sizes.items()
    ]
    rows = train.loc[np.sort(np.concatenate(picked)), list(FEATURE_ORDER)].copy()
    return rows.assign(prob_default=model.predict(rows)["prob_default"].to_numpy())


def publish(reference: pd.DataFrame, api: Any, repo_id: str, model_version: str) -> None:
    """Envoie la référence en Parquet dans un dataset privé (créé au besoin)."""
    buffer = io.BytesIO()
    reference.to_parquet(buffer, index=False)
    buffer.seek(0)
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True)
    api.upload_file(
        path_or_fileobj=buffer,
        path_in_repo=REFERENCE_FILE,
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=f"Référence de dérive : {len(reference)} lignes, scores de {model_version}",
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - envoi réseau réel
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--n", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repo", default=REPO_ID)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    model = load_model(model_dir())
    reference = sample(args.train, model, args.n, args.seed)
    print(f"{len(reference)} lignes, {reference.shape[1]} colonnes, scores de {model.version}.")
    if args.dry_run:
        return 0
    from huggingface_hub import HfApi

    publish(reference, HfApi(), args.repo, model.version)
    print(f"Référence publiée dans le dataset privé {args.repo}.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
