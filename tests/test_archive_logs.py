"""Archivage quotidien des journaux expirés : Parquet vers un dataset privé, puis purge (#16)."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
import sqlalchemy as sa
from scripts import archive_logs as al

from credit_scoring.monitoring import db
from credit_scoring.monitoring.schema import prediction_logs

NOW = datetime(2026, 12, 31, 3, 0, tzinfo=UTC)
REPO = "WillisBack/credit-scoring-logs-archive"


class FakeApi:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.repos: list[dict[str, Any]] = []
        self.uploads: list[tuple[str, bytes]] = []

    def create_repo(self, **kwargs: Any) -> None:
        self.repos.append(kwargs)

    def upload_file(self, *, path_or_fileobj: Any, path_in_repo: str, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("Hub indisponible")
        self.uploads.append((path_in_repo, path_or_fileobj.getvalue()))


@pytest.fixture
def engine(tmp_path: Path) -> sa.Engine:
    url = f"sqlite:///{tmp_path / 'logs.db'}"
    db.run_migrations(url)
    engine = db.make_engine(url)
    with engine.begin() as conn:
        for age_days in (40, 31, 29, 1):
            conn.execute(
                sa.insert(prediction_logs),
                {
                    "request_id": uuid.uuid4(),
                    "created_at": NOW - timedelta(days=age_days),
                    "source": "api",
                    "path": "/predict",
                    "api_version": "0.3.0",
                    "features": {"AMT_CREDIT": float(age_days)},
                    "latency_ms": 10.0,
                    "status_code": 200,
                },
            )
    return engine


def count(engine: sa.Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(sa.select(sa.func.count()).select_from(prediction_logs)).scalar_one()


def test_seules_les_lignes_expirees_partent(engine: sa.Engine) -> None:
    api = FakeApi()
    n = al.archive(engine, api, REPO, timedelta(days=30), NOW)
    assert n == 2
    assert count(engine) == 2
    assert api.repos == [
        {"repo_id": REPO, "repo_type": "dataset", "private": True, "exist_ok": True}
    ]
    (path, data), = api.uploads  # fmt: skip
    assert path == "archive/2026-12-31T030000.parquet"  # à la seconde (#45, M4)
    table = pq.read_table(io.BytesIO(data))
    assert table.num_rows == 2
    assert sorted(table.column("features").to_pylist()) == [
        '{"AMT_CREDIT": 31.0}',
        '{"AMT_CREDIT": 40.0}',
    ]


def test_envoi_en_echec_rien_supprime(engine: sa.Engine) -> None:
    with pytest.raises(RuntimeError):
        al.archive(engine, FakeApi(fail=True), REPO, timedelta(days=30), NOW)
    assert count(engine) == 4


def test_dry_run(engine: sa.Engine) -> None:
    api = FakeApi()
    assert al.archive(engine, api, REPO, timedelta(days=30), NOW, dry_run=True) == 2
    assert api.uploads == []
    assert count(engine) == 4


def test_rien_a_archiver(engine: sa.Engine) -> None:
    api = FakeApi()
    assert al.archive(engine, api, REPO, timedelta(days=60), NOW) == 0
    assert api.uploads == []


@pytest.mark.parametrize(
    ("text", "delta"),
    [("30d", timedelta(days=30)), ("12h", timedelta(hours=12)), ("1h", timedelta(hours=1))],
)
def test_parse_age(text: str, delta: timedelta) -> None:
    assert al.parse_age(text) == delta


def test_suppression_par_paquets(engine: sa.Engine) -> None:
    # Postgres limite une requête à 65 535 paramètres : on supprime par paquets (#45, M3).
    n = al.archive(engine, FakeApi(), REPO, timedelta(days=0, hours=1), NOW, chunk=1)
    assert n == 4
    assert count(engine) == 0


@pytest.mark.parametrize("text", ["30", "d", "-1d", "2w", "", "0h", "0d"])
def test_parse_age_invalide(text: str) -> None:
    with pytest.raises(ValueError, match="durée"):
        al.parse_age(text)


def test_main_sans_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        al.main(["--older-than", "30d"])
