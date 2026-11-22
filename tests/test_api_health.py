from fastapi.testclient import TestClient

from credit_scoring import __version__
from credit_scoring.api.app import app


def test_health_retourne_ok_et_version() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "logging": {"database": False, "dropped": 0},  # sans lifespan : pas de writer
    }


def test_racine_publique_repond_200_avec_lien_vers_la_doc() -> None:
    # Sonde de vivacité des Spaces Hugging Face : la racine doit répondre 200.
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'href="/docs"' in response.text
    assert __version__ in response.text
