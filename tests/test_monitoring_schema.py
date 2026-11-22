"""Schéma `prediction_logs`, connexion et migrations Alembic (#16)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa

from credit_scoring.monitoring import db, schema


def migrate(url: str, revision: str = "head", *, down: bool = False) -> None:
    db.run_migrations(url, revision, downgrade=down)


def columns(url: str) -> set[str]:
    engine = db.make_engine(url)
    try:
        inspector = sa.inspect(engine)
        if not inspector.has_table("prediction_logs"):
            return set()
        return {c["name"] for c in inspector.get_columns("prediction_logs")}
    finally:
        engine.dispose()


def expected() -> set[str]:
    return {c.name for c in schema.prediction_logs.columns}


def test_colonnes_couvrent_la_spec() -> None:
    attendues = {
        "request_id", "created_at", "source", "path", "api_version", "model_version",
        "client_ref", "features", "prob_default", "decision", "threshold", "warnings",
        "n_warnings", "latency_ms", "inference_ms", "status_code", "error_type",
        "error_detail",
    }  # fmt: skip
    assert attendues <= expected()


def test_migration_sqlite_aller_retour(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'logs.db'}"
    migrate(url)
    assert columns(url) == expected()
    migrate(url, "base", down=True)
    assert columns(url) == set()


@pytest.mark.postgres
def test_migration_postgres_aller_retour() -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL absent")
    migrate(url)
    try:
        assert columns(url) == expected()
    finally:
        migrate(url, "base", down=True)
    assert columns(url) == set()


@pytest.mark.parametrize(
    ("url", "driver"),
    [
        ("postgresql://u:p@h/db?sslmode=require", "postgresql+psycopg"),
        ("postgres://u:p@h/db", "postgresql+psycopg"),
        ("sqlite:///x.db", "sqlite"),
    ],
)
def test_make_engine_choisit_psycopg(url: str, driver: str) -> None:
    engine = db.make_engine(url)
    assert engine.url.drivername == driver
    engine.dispose()


def test_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    assert db.database_url() is None
    monkeypatch.delenv("DATABASE_URL")
    assert db.database_url() is None
    monkeypatch.setenv("DATABASE_URL", "sqlite:///x.db")
    assert db.database_url() == "sqlite:///x.db"


def test_migration_depuis_l_environnement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite:///{tmp_path / 'env.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    db.main()
    assert columns(url) == expected()


def test_migration_sans_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        db.main()
