"""Génère `src/credit_scoring/api/features_schema.py` à partir des artefacts et des données P6.

    uv run python scripts/generate_schema.py --p6 <P6> [--artifacts artifacts]

Le module généré contient :
- `FEATURE_ORDER` : les 122 features dans l'ordre d'entrée du modèle ;
- `NULLABLE_FEATURES` : celles qui ont des valeurs manquantes dans le train, la validation
  ou le test de P6 (LightGBM a appris une branche NaN pour elles) ;
- `EXAMPLE_CLIENT` : un client **synthétique** (médiane de chaque feature numérique et
  modalité la plus fréquente sur le train) pour Swagger et la doc — aucune ligne réelle des
  données Kaggle n'est versionnée ;
- `GeneratedFeatures` : le modèle Pydantic des types (catégories en `Literal`, numériques en
  `float`, `None` accepté seulement pour les nullables). Les règles métier sont écrites à la
  main dans `credit_scoring/api/schemas.py`.

À relancer seulement quand le modèle change (nouvel export).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src/credit_scoring/api/features_schema.py"

HEADER = '''"""GÉNÉRÉ par `scripts/generate_schema.py` — ne pas modifier à la main.

Types des 122 features du modèle `home-credit-serving` v2. Les règles métier sont dans
`credit_scoring/api/schemas.py`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
'''


def nullable_features(p6: Path, features: list[str]) -> set[str]:
    found: set[str] = set()
    for name in ("train_fs.csv", "val_fs.csv"):
        frame = pd.read_csv(p6 / "data/processed" / name, usecols=features)
        found |= set(frame.columns[frame.isna().any()])
    with sqlite3.connect(p6 / "data/inference/clients.db") as db:
        frame = pd.read_sql("SELECT * FROM clients", db)[features]
    found |= set(frame.columns[frame.isna().any()])
    return found


def example_client(p6: Path, features: list[str], categorical: set[str]) -> dict[str, object]:
    train = pd.read_csv(p6 / "data/processed/train_fs.csv", usecols=features)
    example: dict[str, object] = {}
    for col in features:
        if col in categorical:
            example[col] = str(train[col].mode().iloc[0])
        else:
            example[col] = round(float(train[col].median()), 6)
    return example


def render(spec: dict[str, object], nullable: set[str], example: dict[str, object]) -> str:
    features: list[str] = spec["input_features"]  # type: ignore[assignment]
    categories: dict[str, list[str]] = spec["categories"]  # type: ignore[assignment]
    lines = [HEADER, ""]
    lines.append("FEATURE_ORDER: tuple[str, ...] = (")
    lines += [f'    "{c}",' for c in features]
    lines.append(")")
    lines.append("")
    lines.append("NULLABLE_FEATURES: frozenset[str] = frozenset(")
    lines.append("    {")
    lines += [f'        "{c}",' for c in features if c in nullable]
    lines.append("    }")
    lines.append(")")
    lines.append("")
    lines.append("# Client synthétique : médianes et modalités les plus fréquentes du train.")
    lines.append("EXAMPLE_CLIENT: dict[str, Any] = {")
    lines += [f'    "{c}": {example[c]!r},' for c in features]
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("class GeneratedFeatures(BaseModel):")
    lines.append('    """Les 122 features : toutes obligatoires, `null` seulement si nullable."""')
    lines.append("")
    lines.append(
        '    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, '
        'json_schema_extra={"examples": [EXAMPLE_CLIENT]})'
    )
    lines.append("")
    for col in features:
        if col in categories:
            values = ", ".join(f'"{v}"' for v in categories[col])
            annotation = f"Literal[{values}]"
        else:
            annotation = "float | None" if col in nullable else "float"
        lines.append(f"    {col}: {annotation}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--p6", type=Path, required=True, help="racine du projet P6")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "artifacts")
    args = parser.parse_args()
    spec = json.loads((args.artifacts / "features.json").read_text(encoding="utf-8"))
    features: list[str] = spec["input_features"]
    nullable = nullable_features(args.p6, features)
    example = example_client(args.p6, features, set(spec["categories"]))
    OUT.write_text(render(spec, nullable, example), encoding="utf-8")
    subprocess.run(["ruff", "format", "-q", str(OUT)], check=True)  # noqa: S603, S607
    subprocess.run(["ruff", "check", "--fix", "-q", str(OUT)], check=True)  # noqa: S603, S607
    print(f"✅ {OUT.relative_to(ROOT)} : {len(features)} features, {len(nullable)} nullables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
