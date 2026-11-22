"""Simulation de trafic à partir des clients du jeu de test de P6 (#16)."""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from scripts import simulate_traffic as st

from credit_scoring.api.features_schema import EXAMPLE_CLIENT, FEATURE_ORDER


@pytest.fixture
def clients_db(tmp_path: Path) -> Path:
    path = tmp_path / "clients.db"
    columns = ["SK_ID_CURR", "COLONNE_EN_TROP", *FEATURE_ORDER]
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TABLE clients ({', '.join(repr(c) for c in columns)})")
        for i in range(3):
            row: dict[str, Any] = {**EXAMPLE_CLIENT, "SK_ID_CURR": 100 + i, "COLONNE_EN_TROP": 1}
            if i == 1:
                row["OWN_CAR_AGE"] = None
            conn.execute(
                f"INSERT INTO clients VALUES ({', '.join('?' for _ in columns)})",  # noqa: S608
                [row[c] for c in columns],
            )
    return path


def test_chargement_des_122_features(clients_db: Path) -> None:
    clients = st.load_clients(clients_db, n=3, seed=0)
    assert len(clients) == 3
    assert all(list(c) == list(FEATURE_ORDER) for c in clients)
    assert any(c["OWN_CAR_AGE"] is None for c in clients)  # NULL → None (JSON null)


def test_echantillon_borne(clients_db: Path) -> None:
    assert len(st.load_clients(clients_db, n=2, seed=0)) == 2
    assert len(st.load_clients(clients_db, n=10, seed=0)) == 3


def test_plan_respecte_les_parts() -> None:
    clients = [dict(EXAMPLE_CLIENT) for _ in range(1000)]
    plan = st.plan_requests(
        clients, invalid_share=0.1, unauthorized_share=0.05, rng=random.Random(0)
    )
    statuts = [r.expected_status for r in plan]
    assert len(plan) == 1000
    assert 60 <= statuts.count(422) <= 140
    assert 20 <= statuts.count(401) <= 80
    for r in plan:
        assert r.path == "/predict"
        assert r.authenticated is (r.expected_status != 401)
        if r.expected_status == 422:
            assert r.body["CNT_FAM_MEMBERS"] == 0  # règle métier violée
        else:
            assert r.body == EXAMPLE_CLIENT


def test_requete_construite(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, dict[str, str]]] = []

    def fake_fetch(url: str, headers: dict[str, str], body: bytes) -> int:
        sent.append((url, headers))
        return 200

    req = st.Request("/predict", dict(EXAMPLE_CLIENT), authenticated=True, expected_status=200)
    assert st.send("https://x.hf.space", "k", req, fetch=fake_fetch) == 200
    url, headers = sent[0]
    assert url == "https://x.hf.space/predict"
    assert headers["X-API-Key"] == "k"
    assert "X-Client" not in headers  # trafic simulé = production (source api)
    req401 = st.Request("/predict", {}, authenticated=False, expected_status=401)
    st.send("https://x.hf.space", "k", req401, fetch=fake_fetch)
    assert "X-API-Key" not in sent[1][1]
