"""Simule du trafic de production à partir des clients du jeu de test de P6 (#16).

    API_KEY=… uv run python scripts/simulate_traffic.py --p6 <dossier P6> \\
        [--url <Space>] [--n 2000] [--rate 5] [--invalid-share 0.05] [--unauthorized-share 0.02]

Les clients viennent de `clients.db` de P6 (48 744 clients du jeu de test Kaggle, local,
jamais publié). Ils sont envoyés tels quels à `POST /predict` avec la clé (`API_KEY`) : leur
écart au jeu d'entraînement est une vraie dérive, analysée en v0.4.0. Une part de requêtes
viole une règle métier (422) ou n'a pas de clé (401), pour alimenter le taux d'erreur.
Sans en-tête `X-Client` : ce trafic représente la production (`source = api`).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from credit_scoring.api.features_schema import FEATURE_ORDER  # noqa: E402

DEFAULT_URL = "https://willisback-credit-scoring-api.hf.space"
Fetch = Callable[[str, dict[str, str], bytes], int]


@dataclass(frozen=True)
class Request:
    path: str
    body: dict[str, Any]
    authenticated: bool
    expected_status: int


def load_clients(db: Path, n: int, seed: int) -> list[dict[str, Any]]:
    """`n` clients tirés au hasard (graine fixe), 122 features dans l'ordre du modèle."""
    columns = ", ".join(f'"{c}"' for c in FEATURE_ORDER)
    with sqlite3.connect(db) as conn:
        rows = conn.execute(f"SELECT {columns} FROM clients").fetchall()  # noqa: S608
    sample = random.Random(seed).sample(rows, min(n, len(rows)))
    return [dict(zip(FEATURE_ORDER, row, strict=True)) for row in sample]


def plan_requests(
    clients: list[dict[str, Any]],
    invalid_share: float,
    unauthorized_share: float,
    rng: random.Random,
) -> list[Request]:
    """Une requête par client : valide, invalide (foyer de 0 personne) ou sans clé."""
    plan = []
    for client in clients:
        draw = rng.random()
        if draw < unauthorized_share:
            plan.append(Request("/predict", client, authenticated=False, expected_status=401))
        elif draw < unauthorized_share + invalid_share:
            body = {**client, "CNT_FAM_MEMBERS": 0}
            plan.append(Request("/predict", body, authenticated=True, expected_status=422))
        else:
            plan.append(Request("/predict", client, authenticated=True, expected_status=200))
    return plan


def _urllib_fetch(url: str, headers: dict[str, str], body: bytes) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return exc.code


def send(url: str, api_key: str, req: Request, fetch: Fetch = _urllib_fetch) -> int:
    headers = {"Content-Type": "application/json"}
    if req.authenticated:
        headers["X-API-Key"] = api_key
    return fetch(f"{url}{req.path}", headers, json.dumps(req.body).encode())


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - envoi réseau réel
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--p6", type=Path, required=True, help="dossier du projet P6")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--n", type=int, default=2000)
    parser.add_argument("--rate", type=float, default=5.0, help="requêtes par seconde")
    parser.add_argument("--invalid-share", type=float, default=0.05)
    parser.add_argument("--unauthorized-share", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    api_key = os.environ.get("API_KEY", "")
    if not api_key:
        raise SystemExit("API_KEY absente")
    clients = load_clients(args.p6 / "data/inference/clients.db", args.n, args.seed)
    plan = plan_requests(
        clients, args.invalid_share, args.unauthorized_share, random.Random(args.seed)
    )
    counts: Counter[str] = Counter()
    for i, req in enumerate(plan, 1):
        status = send(args.url.rstrip("/"), api_key, req)
        counts[f"{status} (attendu {req.expected_status})"] += 1
        if i % 100 == 0:
            print(f"{i}/{len(plan)} : {dict(counts)}", flush=True)
        time.sleep(1 / args.rate)
    print(f"Terminé : {dict(counts)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
