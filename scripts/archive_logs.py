"""Archive les journaux de production expirés, puis les purge (fenêtre glissante, #16).

    uv run --group archive python scripts/archive_logs.py --older-than 30d [--dry-run]

Lignes `prediction_logs` plus anciennes que `--older-than` → un fichier Parquet → dataset
Hugging Face **privé** (`archive/AAAA-MM-JJTHHMM.parquet`) → suppression des mêmes lignes,
**seulement après** l'envoi réussi. Mécanisme démonstratif (décision de William) : les
archives ne sont pas conservées au-delà du projet.

Variables : `DATABASE_URL` (base de production), `HF_TOKEN` (écriture sur le dataset).
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from credit_scoring.monitoring.db import database_url, make_engine  # noqa: E402
from credit_scoring.monitoring.schema import prediction_logs  # noqa: E402

REPO_ID = "WillisBack/credit-scoring-logs-archive"
JSON_COLUMNS = ("features", "warnings", "error_detail")
_AGE = re.compile(r"(\d+)([dh])")
CHUNK = 10_000  # Postgres : 65 535 paramètres au plus par requête


def parse_age(text: str) -> timedelta:
    """`30d` → 30 jours, `12h` → 12 heures."""
    match = _AGE.fullmatch(text)
    if not match:
        raise ValueError(f"durée {text!r} invalide : attendu <n>d ou <n>h (ex. 30d, 1h)")
    n, unit = int(match.group(1)), match.group(2)
    if n == 0:  # 0h viderait toute la table à la main
        raise ValueError(f"durée {text!r} invalide : au moins 1 (ex. 1h)")
    return timedelta(days=n) if unit == "d" else timedelta(hours=n)


def _to_parquet(rows: list[dict[str, Any]]) -> io.BytesIO:
    """JSON en texte (schéma Parquet stable quelle que soit la forme du contenu)."""
    flat = [
        {
            **row,
            "request_id": str(row["request_id"]),
            **{c: None if row[c] is None else json.dumps(row[c]) for c in JSON_COLUMNS},
        }
        for row in rows
    ]
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(flat), buffer)
    buffer.seek(0)
    return buffer


def archive(
    engine: sa.Engine,
    api: Any,
    repo_id: str,
    older_than: timedelta,
    now: datetime,
    dry_run: bool = False,
    chunk: int = CHUNK,
) -> int:
    """Archive puis supprime les lignes antérieures à `now - older_than` ; renvoie leur nombre."""
    cutoff = now - older_than
    with engine.connect() as conn:
        rows = [
            dict(r._mapping)
            for r in conn.execute(
                sa.select(prediction_logs).where(prediction_logs.c.created_at < cutoff)
            )
        ]
    if not rows or dry_run:
        return len(rows)
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True)
    api.upload_file(
        path_or_fileobj=_to_parquet(rows),
        path_in_repo=f"archive/{now:%Y-%m-%dT%H%M%S}.parquet",
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=f"Archive des journaux antérieurs au {cutoff:%Y-%m-%d %H:%M} UTC",
    )
    # Suppression seulement après l'envoi : un échec du Hub ne perd aucune ligne.
    ids = [row["id"] for row in rows]
    with engine.begin() as conn:
        for start in range(0, len(ids), chunk):
            batch = ids[start : start + chunk]
            conn.execute(sa.delete(prediction_logs).where(prediction_logs.c.id.in_(batch)))
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--older-than", default="30d", help="âge minimal (ex. 30d, 1h)")
    parser.add_argument("--repo", default=REPO_ID)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    older_than = parse_age(args.older_than)
    url = database_url()
    if not url:
        raise SystemExit("DATABASE_URL absente : aucune base à archiver")
    from huggingface_hub import HfApi

    engine = make_engine(url)
    try:
        n = archive(engine, HfApi(), args.repo, older_than, datetime.now(UTC), args.dry_run)
    finally:
        engine.dispose()
    verbe = "à archiver (dry-run)" if args.dry_run else "archivées puis supprimées"
    print(f"{n} lignes {verbe} (plus anciennes que {args.older_than}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
