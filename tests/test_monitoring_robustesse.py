"""Robustesse de la journalisation face aux entrées hostiles et aux pannes (revue finale #16)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from credit_scoring.api import app as app_module
from credit_scoring.api.app import app
from credit_scoring.api.features_schema import EXAMPLE_CLIENT
from credit_scoring.monitoring import db, record
from credit_scoring.monitoring.middleware import _buffer
from credit_scoring.monitoring.schema import prediction_logs
from credit_scoring.monitoring.writer import ProductionLogWriter
from tests.conftest import API_KEY, DEMO_INVALID_ID
from tests.test_monitoring_api import AUTH, call, env, logs  # noqa: F401 (fixture)


def build_422(
    body: bytes, response: dict[str, Any] | bytes, path: str = "/predict"
) -> dict[str, Any]:
    raw = response if isinstance(response, bytes) else json.dumps(response).encode()
    return record.build(
        request_id=uuid.uuid4(),
        created_at=datetime.now(UTC),
        source="api",
        path=path,
        api_version="t",
        model_version=None,
        status_code=422,
        latency_ms=1.0,
        state={"client_ref": "abc"} if path != "/predict" else {},
        body=body,
        response_body=raw,
    )


# I1 : la troncature à 64 Kio vaut aussi pour le détail de l'erreur
def test_detail_d_erreur_tronque(env: str) -> None:  # noqa: F811
    body = {**EXAMPLE_CLIENT, "AMT_CREDIT": "x" * 500_000}
    (row,) = call(env, ("/predict", {"json": body, "headers": AUTH}))
    assert len(json.dumps(row.error_detail)) < 70_000


# I2 : valeurs refusées par JSONB (NaN, infini, surrogate isolé) neutralisées
def test_valeurs_hors_json_neutralisees() -> None:
    row = build_422(b'{"a": NaN, "b": Infinity, "c": "\\ud800x"}', {"detail": []})
    assert row["features"]["a"] is None
    assert row["features"]["b"] is None
    json.dumps(row["features"], allow_nan=False).encode("utf-8")  # strict : ne lève pas


# I2 : une ligne invalide ne fait pas perdre les autres lignes de son lot
def test_ligne_invalide_n_emporte_pas_le_lot(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'logs.db'}"
    db.run_migrations(url)
    engine = db.make_engine(url)
    dup = uuid.uuid4()
    base = {
        "created_at": datetime.now(UTC),
        "source": "api",
        "path": "/predict",
        "api_version": "t",
        "latency_ms": 1.0,
        "status_code": 200,
    }
    writer = ProductionLogWriter(engine, batch=10)
    for request_id in (dup, uuid.uuid4(), dup, uuid.uuid4()):  # 2e « dup » : contrainte unique
        writer.submit({**base, "request_id": request_id})
    writer.start()
    writer.stop()
    with engine.connect() as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(prediction_logs)).scalar_one()
    assert n == 3
    assert writer.dropped == 1


# I3 : l'arrêt est borné même si la base ne répond plus et que la file est pleine
class HangingEngine:
    def __init__(self) -> None:
        self.release = threading.Event()

    def begin(self) -> Any:
        self.release.wait(10)
        raise sa.exc.OperationalError("INSERT", {}, Exception("timeout"))


def test_arret_borne_base_bloquee() -> None:
    engine = HangingEngine()
    writer = ProductionLogWriter(engine, maxsize=2)  # type: ignore[arg-type]
    writer.start()
    for _ in range(5):
        writer.submit({"request_id": uuid.uuid4()})
    time.sleep(0.05)
    start = time.monotonic()
    writer.stop(timeout=0.3)
    assert time.monotonic() - start < 1.5  # l'arrêt n'attend pas la base bloquée
    engine.release.set()  # le lot en cours échoue à son tour
    deadline = time.monotonic() + 3
    while writer.dropped < 5 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert writer.dropped == 5  # aucune ligne perdue sans être comptée


def test_connexion_postgres_avec_delai(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_create_engine(url: str, **kwargs: Any) -> str:
        seen.update(kwargs)
        return url

    monkeypatch.setattr(sa, "create_engine", fake_create_engine)
    db.make_engine("postgresql://u:p@h/db")
    assert seen["connect_args"]["connect_timeout"] == 10


# I4 : un JSON très imbriqué ne fait pas lever le middleware, la ligne est écrite
def test_json_tres_imbrique(env: str) -> None:  # noqa: F811
    deep = b"[" * 3000 + b"]" * 3000
    headers = {**AUTH, "Content-Type": "application/json"}
    (row,) = call(env, ("/predict", {"content": deep, "headers": headers}))
    assert row.status_code == 422
    assert "_raw" in row.features


def test_echec_de_construction_sans_effet_sur_la_reponse(
    env: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**kwargs: Any) -> Any:
        raise ValueError("bug de journalisation")

    monkeypatch.setattr(record, "build", boom)
    with TestClient(app) as client:
        response = client.post("/predict", json=EXAMPLE_CLIENT, headers=AUTH)
    assert response.status_code == 200


# I5 : mise en tampon linéaire (pas de recopie du corps à chaque morceau)
def test_tampon_lineaire() -> None:
    chunk = b"x" * 4096
    n = 4000  # 16 Mo : quelques ms en linéaire, plusieurs secondes en quadratique

    async def scenario() -> float:
        count = 0

        async def receive() -> dict[str, Any]:
            nonlocal count
            count += 1
            return {"type": "http.request", "body": chunk, "more_body": count < n}

        start = time.perf_counter()
        body, _ = await _buffer(receive)
        assert len(body) == n * len(chunk)
        return time.perf_counter() - start

    assert asyncio.run(scenario()) < 1.0


# I6 : l'identifiant d'un client de démo invalide n'apparaît pas dans le détail stocké
def test_identifiant_de_demo_absent_du_detail(env: str) -> None:  # noqa: F811
    (row,) = call(env, (f"/predict/{DEMO_INVALID_ID}", {"headers": AUTH}))
    assert row.status_code == 422
    assert str(DEMO_INVALID_ID) not in json.dumps(row.error_detail)
    assert row.error_detail[0]["loc"][1] == row.client_ref


# M1 : une valeur absente est un NULL SQL (requêtes « IS NULL » du dashboard)
def test_absence_stockee_en_null_sql(env: str) -> None:  # noqa: F811
    call(env, ("/predict", {"json": EXAMPLE_CLIENT}))  # 401 : ni features ni détail
    engine = db.make_engine(env)
    with engine.connect() as conn:
        n = conn.execute(
            sa.select(sa.func.count())
            .select_from(prediction_logs)
            .where(prediction_logs.c.features.is_(None), prediction_logs.c.warnings.is_(None))
        ).scalar_one()
    engine.dispose()
    assert n == 1


def test_api_key_constante() -> None:
    assert API_KEY  # garde : la fixture partagée fournit bien une clé
    assert app_module.app is app


@pytest.mark.parametrize(
    ("detail", "attendu"),
    [("texte libre", "texte libre"), (["brut", {"loc": ["body"]}], ["brut", {"loc": ["body"]}])],
)
def test_detail_atypique_conserve(detail: Any, attendu: Any) -> None:
    assert build_422(b"{}", {"detail": detail})["error_detail"] == attendu


def test_file_pleine_au_moment_de_l_arret() -> None:
    engine = HangingEngine()
    writer = ProductionLogWriter(engine, maxsize=2)  # type: ignore[arg-type]
    writer.start()
    writer.submit({"request_id": 1})
    time.sleep(0.05)  # le thread est bloqué dans l'insertion de ce premier lot
    for i in range(3):  # deux remplissent la file, la troisième est refusée
        writer.submit({"request_id": i})
    writer.stop(timeout=0.2)
    assert writer.dropped == 3  # 1 refusée + 2 retirées de la file pleine
    engine.release.set()


class ExplodingEngine:
    def begin(self) -> Any:
        raise RuntimeError("bug inattendu")


def test_erreur_inattendue_comptee() -> None:
    writer = ProductionLogWriter(ExplodingEngine())  # type: ignore[arg-type]
    writer.start()
    writer.submit({"request_id": 1})
    writer.stop()
    assert writer.dropped == 1
