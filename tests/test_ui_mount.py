"""Montage de l'interface à la racine de l'API, et repli sans Gradio (image Docker) (#40)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from credit_scoring import __version__
from credit_scoring.api.app import app, install_home
from credit_scoring.api.features_schema import EXAMPLE_CLIENT
from credit_scoring.model import get_model
from tests.conftest import API_KEY


def test_racine_sert_gradio() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "gradio" in response.text.lower()


def test_api_intacte_avec_gradio(api_artifacts: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_DIR", str(api_artifacts))
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_model.cache_clear()
    with TestClient(app) as client:  # le lifespan de l'API tourne malgré le montage
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 200
        assert "/predict" in client.get("/openapi.json").json()["paths"]
        response = client.post("/predict", json=EXAMPLE_CLIENT, headers={"X-API-Key": API_KEY})
        assert response.status_code == 200
    get_model.cache_clear()


def test_sans_gradio_page_html(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "gradio", None)  # import gradio → ImportError
    for name in [
        m for m in sys.modules if m == "credit_scoring.ui" or m.startswith("credit_scoring.ui.")
    ]:
        monkeypatch.delitem(sys.modules, name)
    bare = FastAPI()
    install_home(bare)
    response = TestClient(bare).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'href="/docs"' in response.text
    assert __version__ in response.text


def test_gradio_casse_n_est_pas_masque(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gradio installé mais en erreur : l'échec doit être visible, pas un repli silencieux
    # (sur le Space, le repli supprimerait aussi le middleware ZeroGPU).
    import builtins

    real_import = builtins.__import__

    def broken(name: str, *args: object, **kwargs: object) -> object:
        if name == "credit_scoring.ui":
            raise ModuleNotFoundError("No module named 'gradio.x'", name="gradio.x")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", broken)
    with pytest.raises(ImportError):
        install_home(FastAPI())


def test_pas_de_serveur_node_meme_si_le_space_active_le_ssr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sur un Space, GRADIO_SSR_MODE=true : un serveur Node lancé au montage prendrait le
    # port 7860 avant uvicorn (Errno 98, #42).
    import gradio.routes

    from credit_scoring.ui import mount_ui
    from credit_scoring.ui.app import MOUNT_OPTIONS

    def interdit(*args: object, **kwargs: object) -> object:
        raise AssertionError("serveur Node SSR démarré")

    monkeypatch.setenv("GRADIO_SSR_MODE", "true")
    monkeypatch.setattr(gradio.routes, "start_node_server", interdit)
    assert MOUNT_OPTIONS.get("ssr_mode") is False
    mount_ui(FastAPI())
