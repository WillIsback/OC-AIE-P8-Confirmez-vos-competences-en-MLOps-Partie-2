"""Latence locale de l'API (p50/p95/p99), avec la machine en métadonnées.

    uv run python scripts/bench_latency.py [--n 1000] [--warmup 50]

Mesure en processus (TestClient : ASGI + validation + modèle, sans réseau) sur les vrais
artefacts (`artifacts/`), en séparant la latence totale d'une requête `/predict` et le temps
d'inférence seul (`ScoringModel.predict`). Le résultat sert de référence avant/après
optimisation (rapport v0.4.0) : ne comparer que des mesures faites sur la même machine.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from credit_scoring.api.app import app  # noqa: E402
from credit_scoring.api.features_schema import EXAMPLE_CLIENT, FEATURE_ORDER  # noqa: E402
from credit_scoring.model import get_model  # noqa: E402

KEY = "bench"


def percentiles(samples_ms: list[float]) -> dict[str, float]:
    arr = np.asarray(samples_ms)
    return {
        "p50": round(float(np.percentile(arr, 50)), 3),
        "p95": round(float(np.percentile(arr, 95)), 3),
        "p99": round(float(np.percentile(arr, 99)), 3),
        "mean": round(statistics.fmean(samples_ms), 3),
    }


def machine() -> dict[str, object]:
    cpu = platform.processor() or platform.machine()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    return {
        "cpu": cpu,
        "cpu_count": os.cpu_count(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "lightgbm": lgb.__version__,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=50)
    args = parser.parse_args()
    os.environ.setdefault("MODEL_DIR", str(ROOT / "artifacts"))
    os.environ["API_KEY"] = KEY

    with TestClient(app) as client:
        headers = {"X-API-Key": KEY}
        for _ in range(args.warmup):
            client.post("/predict", json=EXAMPLE_CLIENT, headers=headers)
        total: list[float] = []
        for _ in range(args.n):
            start = time.perf_counter()
            response = client.post("/predict", json=EXAMPLE_CLIENT, headers=headers)
            total.append((time.perf_counter() - start) * 1000)
            if response.status_code != 200:
                raise SystemExit(f"Requête refusée : {response.text}")

        model = get_model()
        frame = pd.DataFrame([EXAMPLE_CLIENT], columns=list(FEATURE_ORDER))
        inference: list[float] = []
        for _ in range(args.n):
            start = time.perf_counter()
            model.predict(frame)
            inference.append((time.perf_counter() - start) * 1000)

    result = {
        "requests": args.n,
        "latency_ms": percentiles(total),
        "inference_ms": percentiles(inference),
        "machine": machine(),
        "model": model.version,
    }
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
