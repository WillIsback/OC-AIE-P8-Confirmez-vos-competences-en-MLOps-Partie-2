"""Écriture des journaux en tâche de fond : jamais bloquante, jamais d'exception (#16)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from credit_scoring.monitoring import db
from credit_scoring.monitoring.schema import prediction_logs
from credit_scoring.monitoring.writer import LOGGER_NAME, ProductionLogWriter


def record(**overrides: Any) -> dict[str, Any]:
    return {
        "request_id": uuid.uuid4(),
        "created_at": datetime.now(UTC),
        "source": "api",
        "path": "/predict",
        "api_version": "0.3.0",
        "model_version": "home-credit-serving v2",
        "features": {"AMT_CREDIT": 514777.5},
        "prob_default": 0.46,
        "decision": "accordé",
        "threshold": 0.5348,
        "warnings": [],
        "n_warnings": 0,
        "latency_ms": 12.3,
        "inference_ms": 10.1,
        "status_code": 200,
        **overrides,
    }


@pytest.fixture
def engine(tmp_path: Path) -> sa.Engine:
    url = f"sqlite:///{tmp_path / 'logs.db'}"
    db.run_migrations(url)
    return db.make_engine(url)


def rows(engine: sa.Engine) -> list[sa.Row[Any]]:
    with engine.connect() as conn:
        return list(conn.execute(sa.select(prediction_logs)))


def test_enregistrements_inseres_apres_arret(engine: sa.Engine) -> None:
    writer = ProductionLogWriter(engine, batch=2)
    writer.start()
    for _ in range(5):
        writer.submit(record())
    writer.stop()
    stored = rows(engine)
    assert len(stored) == 5
    assert stored[0].features == {"AMT_CREDIT": 514777.5}
    assert writer.database is True
    assert writer.dropped == 0


def test_chaque_enregistrement_ecrit_une_ligne_json(
    engine: sa.Engine, caplog: pytest.LogCaptureFixture
) -> None:
    writer = ProductionLogWriter(engine)
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        writer.submit(record(source="ui-demo"))
    line = json.loads(caplog.records[-1].getMessage())
    assert line["source"] == "ui-demo"
    assert line["status_code"] == 200


def test_sans_base_stdout_seulement(caplog: pytest.LogCaptureFixture) -> None:
    writer = ProductionLogWriter(None)
    writer.start()
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        writer.submit(record())
    writer.stop()
    assert writer.database is False
    assert writer.dropped == 0
    assert caplog.records


class BrokenEngine:
    """Moteur dont chaque connexion échoue, avec une URL secrète dans le message."""

    def begin(self) -> Any:
        raise sa.exc.OperationalError("INSERT", {}, Exception("postgresql://u:secret@h/db"))


def test_base_en_panne_compte_sans_lever(caplog: pytest.LogCaptureFixture) -> None:
    writer = ProductionLogWriter(BrokenEngine())  # type: ignore[arg-type]
    writer.start()
    writer.submit(record())
    writer.submit(record())
    writer.stop()
    assert writer.dropped == 2
    assert "secret" not in caplog.text


def test_file_pleine_abandonne(engine: sa.Engine) -> None:
    writer = ProductionLogWriter(engine, maxsize=1)  # thread non démarré : file jamais vidée
    writer.submit(record())
    writer.submit(record())
    assert writer.dropped == 1


def test_arret_sans_demarrage_est_sans_effet(engine: sa.Engine) -> None:
    writer = ProductionLogWriter(engine)
    writer.stop()
    assert rows(engine) == []


def test_lot_partiel_ecrit_sans_attendre_l_arret(engine: sa.Engine) -> None:
    import time

    writer = ProductionLogWriter(engine, batch=10)
    writer.start()
    writer.submit(record())  # lot incomplet : écrit dès que la file est vide
    deadline = time.monotonic() + 5
    while not rows(engine) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(rows(engine)) == 1
    writer.stop()


def test_arret_recu_au_milieu_d_un_lot(engine: sa.Engine) -> None:
    writer = ProductionLogWriter(engine, batch=10)
    for _ in range(3):  # en file avant le démarrage, suivis de l'ordre d'arrêt
        writer.submit(record())
    writer.start()
    writer.stop()
    assert len(rows(engine)) == 3
