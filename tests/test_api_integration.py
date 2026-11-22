"""API sur les vrais artefacts : 1 000 clients réels validés, score P6 inchangé."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from credit_scoring.api.app import app
from credit_scoring.model import DEFAULT_MODEL_DIR, MANIFEST_FILE, get_model

pytestmark = pytest.mark.integration
KEY = "cle-integration"


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    if not (DEFAULT_MODEL_DIR / MANIFEST_FILE).is_file():
        pytest.fail("Artefacts absents : uv run python scripts/model_hub.py fetch")
    mp = pytest.MonkeyPatch()
    mp.setenv("MODEL_DIR", str(Path(DEFAULT_MODEL_DIR).resolve()))
    mp.setenv("API_KEY", KEY)
    get_model.cache_clear()
    with TestClient(app) as c:
        yield c
    get_model.cache_clear()
    mp.undo()


def test_clients_reels_valides_et_scores_identiques(client: TestClient) -> None:
    reference = pd.read_csv(DEFAULT_MODEL_DIR / "reference_predictions.csv")
    refus = {"refusé": 1, "accordé": 0}
    for row in reference.itertuples(index=False):
        r = client.post(f"/predict/{row.SK_ID_CURR}", headers={"X-API-Key": KEY})
        assert r.status_code == 200, r.json()
        body = r.json()
        assert body["prob_default"] == pytest.approx(row.prob_default, abs=1e-9)
        assert refus[body["decision"]] == row.decision
