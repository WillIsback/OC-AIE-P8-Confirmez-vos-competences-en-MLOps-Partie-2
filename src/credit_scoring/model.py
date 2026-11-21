"""Chargement unique du modèle de scoring et prédiction, sans MLflow (ADR-002).

Les artefacts (dossier `MODEL_DIR`, `artifacts/` par défaut) sont extraits du modèle
`home-credit-serving` v2 de P6 par `scripts/export_p6_artifacts.py` :

- `model.txt` : booster LightGBM au format texte natif (pas de pickle) ;
- `features.json` : ordre d'entrée des 122 features, catégories de l'encodeur ordinal,
  ordre des colonnes vu par le modèle, bornes du jeu d'entraînement ;
- `manifest.json` : traçabilité (run MLflow, version du Registry, seuil) et empreintes
  SHA-256 vérifiées au chargement.

Le wrapper P6 faisait : réalignement par nom → `OrdinalEncoder` (catégorie inconnue ou
manquante → -1) en tête, puis les colonnes numériques telles quelles → `predict_proba`
→ décision = score ≥ seuil. Ce module reproduit exactement ce chemin ; le test de
non-régression le vérifie contre les scores de P6.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

MANIFEST_FILE = "manifest.json"
FEATURES_FILE = "features.json"
MODEL_FILE = "model.txt"
DEFAULT_MODEL_DIR = Path("artifacts")
UNKNOWN_CATEGORY = -1.0


class ArtifactError(RuntimeError):
    """Artefacts absents, incomplets ou altérés : le service ne doit pas démarrer."""


def sha256_file(path: Path) -> str:
    """Empreinte SHA-256 d'un fichier, lue par blocs."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class FeatureSpec:
    """Contrat d'entrée du modèle."""

    input_features: tuple[str, ...]
    categories: dict[str, dict[str, float]]
    model_columns: tuple[str, ...]
    numeric_bounds: dict[str, dict[str, float]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureSpec:
        return cls(
            input_features=tuple(data["input_features"]),
            categories={
                col: {value: float(code) for code, value in enumerate(values)}
                for col, values in data["categories"].items()
            },
            model_columns=tuple(data["model_columns"]),
            numeric_bounds=data.get("numeric_bounds", {}),
        )


@dataclass(frozen=True)
class ScoringModel:
    """Encodeur + booster + seuil métier, chargés une fois."""

    booster: lgb.Booster
    features: FeatureSpec
    threshold: float
    manifest: dict[str, Any]

    @property
    def version(self) -> str:
        return f"{self.manifest['model_name']} v{self.manifest['model_version']}"

    def encode(self, frame: pd.DataFrame) -> np.ndarray:
        """Matrice float64 dans l'ordre des colonnes du modèle."""
        missing = [c for c in self.features.model_columns if c not in frame.columns]
        if missing:
            raise ValueError(f"Features absentes : {', '.join(missing)}")
        columns: list[np.ndarray] = []
        for col in self.features.model_columns:
            mapping = self.features.categories.get(col)
            if mapping is None:
                values = pd.to_numeric(frame[col], errors="raise").astype("float64")
                columns.append(values.to_numpy())
            else:
                codes = frame[col].map(mapping).fillna(UNKNOWN_CATEGORY)
                columns.append(codes.astype("float64").to_numpy())
        return np.column_stack(columns)

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Score de défaut, décision (1 = refus) et seuil, comme le wrapper P6."""
        proba = np.asarray(self.booster.predict(self.encode(frame)), dtype="float64")
        return pd.DataFrame(
            {
                "prob_default": proba,
                "decision": (proba >= self.threshold).astype(int),
                "threshold": np.full(len(proba), self.threshold),
            },
            index=frame.index,
        )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ArtifactError(f"Fichier d'artefact manquant : {path}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def verify_files(model_dir: Path, manifest: dict[str, Any]) -> None:
    """Vérifie présence et empreinte de chaque fichier listé dans le manifeste."""
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ArtifactError("manifest.json : clé « files » absente ou vide")
    for name, expected in files.items():
        path = model_dir / name
        if not path.is_file():
            raise ArtifactError(f"Fichier d'artefact manquant : {name}")
        if sha256_file(path) != expected:
            raise ArtifactError(f"Empreinte SHA-256 inattendue : {name}")


def load_model(model_dir: Path) -> ScoringModel:
    """Charge et vérifie les artefacts. Lève `ArtifactError` s'ils sont invalides."""
    manifest = _read_json(model_dir / MANIFEST_FILE)
    verify_files(model_dir, manifest)
    features = FeatureSpec.from_dict(_read_json(model_dir / FEATURES_FILE))
    booster = lgb.Booster(model_file=str(model_dir / MODEL_FILE))
    return ScoringModel(booster, features, float(manifest["threshold"]), manifest)


@lru_cache(maxsize=1)
def get_model() -> ScoringModel:
    """Modèle du processus : chargé au premier appel, puis réutilisé."""
    return load_model(Path(os.environ.get("MODEL_DIR", str(DEFAULT_MODEL_DIR))))
