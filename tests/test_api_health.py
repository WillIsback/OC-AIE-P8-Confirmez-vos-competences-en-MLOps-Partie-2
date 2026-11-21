from fastapi.testclient import TestClient

from credit_scoring import __version__
from credit_scoring.api.app import app


def test_health_retourne_ok_et_version() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
