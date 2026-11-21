"""Extrait les artefacts du modèle servi en P6 (`home-credit-serving` v2) vers `artifacts/`.

À lancer dans l'environnement de P6, qui contient MLflow et le Registry :

    uv run --project <P6> python scripts/export_p6_artifacts.py --p6 <P6> --out artifacts

Étapes :
1. lit la version du Registry dans `mlflow.db` (run id, identifiant du modèle) ;
2. charge le wrapper pyfunc de P6 (`python_model.pkl`) ;
3. écrit le booster au format texte LightGBM, le contrat d'entrée (`features.json`, avec les
   bornes du jeu d'entraînement), un échantillon de 1 000 clients du jeu de test et leurs
   scores de référence calculés par P6 ;
4. recharge les artefacts avec `credit_scoring.model` et compare ses scores à ceux de P6
   sur les 48 744 clients du jeu de test : l'export échoue au-delà de 1e-9 ;
5. écrit `manifest.json` (traçabilité, empreintes SHA-256, résultat de la validation).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import cloudpickle
import lightgbm as lgb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from credit_scoring.model import load_model, sha256_file  # noqa: E402

REGISTRY_NAME = "home-credit-serving"
REGISTRY_VERSION = 2
SAMPLE_SIZE = 1_000
SAMPLE_SEED = 42
TOLERANCE = 1e-9


def registry_entry(p6: Path) -> dict[str, Any]:
    with sqlite3.connect(p6 / "mlflow.db") as db:
        source, run_id = db.execute(
            "SELECT source, run_id FROM model_versions WHERE name = ? AND version = ?",
            (REGISTRY_NAME, REGISTRY_VERSION),
        ).fetchone()
        params = dict(
            db.execute("SELECT key, value FROM params WHERE run_uuid = ?", (run_id,)).fetchall()
        )
    return {"source": source, "run_id": run_id, "params": params}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--p6", type=Path, required=True, help="racine du projet P6")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts")
    args = parser.parse_args()
    p6: Path = args.p6.resolve()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    entry = registry_entry(p6)
    model_id = entry["source"].removeprefix("models:/")
    pkl = p6 / "mlflow-artifacts/1/models" / model_id / "artifacts/python_model.pkl"
    with pkl.open("rb") as f:
        scorer = cloudpickle.load(f)  # artefact local produit par P6
    print(f"{REGISTRY_NAME} v{REGISTRY_VERSION} : run {entry['run_id']}, {model_id}")

    # 1. booster au format texte natif
    scorer.model.booster_.save_model(str(out / "model.txt"))

    # 2. contrat d'entrée
    encoder = scorer.encoder
    cat_cols = list(encoder.transformers_[0][2])
    rest_cols = list(encoder.transformers_[1][2])
    categories = encoder.named_transformers_["cat"].categories_
    numeric = [c for c in scorer.feature_names if c not in cat_cols]
    train = pd.read_csv(p6 / "data/processed/train_fs.csv", usecols=numeric)
    bounds = {c: {"min": float(train[c].min()), "max": float(train[c].max())} for c in numeric}
    features = {
        "input_features": list(scorer.feature_names),
        "categories": {
            c: [str(v) for v in cats] for c, cats in zip(cat_cols, categories, strict=True)
        },
        "model_columns": cat_cols + rest_cols,
        "numeric_bounds": bounds,
    }
    (out / "features.json").write_text(
        json.dumps(features, indent=1, ensure_ascii=False), encoding="utf-8"
    )

    # 3. clients du jeu de test, scores de référence P6
    with sqlite3.connect(p6 / "data/inference/clients.db") as db:
        clients = pd.read_sql("SELECT * FROM clients", db)
    reference = scorer.predict(None, clients[scorer.feature_names])
    reference.insert(0, "SK_ID_CURR", clients["SK_ID_CURR"].to_numpy())
    sample_idx = clients.sample(SAMPLE_SIZE, random_state=SAMPLE_SEED).index
    clients.loc[sample_idx, ["SK_ID_CURR", *scorer.feature_names]].to_csv(
        out / "sample_clients.csv", index=False
    )
    reference.loc[sample_idx, ["SK_ID_CURR", "prob_default", "decision"]].to_csv(
        out / "reference_predictions.csv", index=False
    )

    # 4. manifeste, puis validation par le module de P8 sur tout le jeu de test
    files = ["model.txt", "features.json", "sample_clients.csv", "reference_predictions.csv"]
    manifest: dict[str, Any] = {
        "model_name": REGISTRY_NAME,
        "model_version": str(REGISTRY_VERSION),
        "mlflow_model_id": model_id,
        "mlflow_run_id": entry["run_id"],
        "base_model": entry["params"].get("base_model"),
        "threshold": float(scorer.threshold),
        "fn_cost": float(entry["params"].get("fn_cost", "nan")),
        "fp_cost": float(entry["params"].get("fp_cost", "nan")),
        "lightgbm_version": lgb.__version__,
        "exported_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "sample": {"size": SAMPLE_SIZE, "seed": SAMPLE_SEED, "source": "clients.db (test)"},
        "files": {name: sha256_file(out / name) for name in files},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    ported = load_model(out).predict(clients)
    max_diff = float((ported["prob_default"] - reference["prob_default"]).abs().max())
    same_decisions = bool((ported["decision"] == reference["decision"]).all())
    manifest["validation"] = {
        "rows": len(clients),
        "max_abs_diff_prob_default": max_diff,
        "same_decisions": same_decisions,
        "tolerance": TOLERANCE,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(
        f"validation : {len(clients)} clients, écart max {max_diff:.3e}, "
        f"décisions identiques : {same_decisions}"
    )
    if max_diff > TOLERANCE or not same_decisions:
        print("❌ Le module de P8 ne reproduit pas les scores de P6.")
        return 1
    print(f"✅ Artefacts écrits dans {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
