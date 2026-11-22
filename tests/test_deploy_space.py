"""Déploiement sur le Space Hugging Face (#15) — faux client Hub, aucun appel réseau."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import deploy_space as ds

SPACE = "WillisBack/credit-scoring-api"


class FakeApi:
    def __init__(self, stages: list[str], host: str = "https://willisback-credit.hf.space"):
        self.stages = stages
        self.host = host
        self.calls: list[tuple[str, Any]] = []

    def create_repo(self, **kwargs: Any) -> None:
        self.calls.append(("create_repo", kwargs))

    def add_space_secret(self, repo_id: str, key: str, value: str) -> None:
        self.calls.append(("secret", key))

    def create_commit(self, **kwargs: Any) -> None:
        files = {op.path_in_repo: op.path_or_fileobj for op in kwargs["operations"]}
        self.calls.append(("commit", files))

    def get_space_runtime(self, repo_id: str) -> Any:
        stage = self.stages.pop(0) if len(self.stages) > 1 else self.stages[0]
        return SimpleNamespace(stage=stage)

    def space_info(self, repo_id: str) -> Any:
        return SimpleNamespace(host=self.host)


REQS = "# généré par uv\nfastapi==0.165.0\n    # via credit-scoring\nlightgbm==4.7.0\n"
REV = "7d1a4cbeddbf4301e0d6ede8ca0604197b8d7739"


def test_fichiers_du_space_gradio() -> None:
    files = ds.space_files("v0.2.1", REQS, REV)
    assert set(files) == {
        "README.md",
        "app.py",
        "requirements.txt",
        "packages.txt",
        "model_revision.txt",
    }
    readme = files["README.md"].decode()
    assert "sdk: gradio" in readme
    assert f"sdk_version: {ds.GRADIO_VERSION}" in readme
    assert "app_file: app.py" in readme
    assert 'python_version: "3.12"' in readme
    assert "credit_scoring.api.app:app" in files["app.py"].decode()
    assert files["packages.txt"].decode().split() == ["libgomp1"]
    assert files["model_revision.txt"].decode().strip() == REV


def test_paquet_installe_depuis_le_tag_avec_les_versions_du_verrou() -> None:
    reqs = ds.space_files("v0.2.1", REQS, REV)["requirements.txt"].decode().splitlines()
    assert reqs[:2] == ["fastapi==0.165.0", "lightgbm==4.7.0"]
    assert reqs[-1] == f"credit-scoring @ git+{ds.GIT_URL}@v0.2.1"


@pytest.mark.parametrize("version", ["0.2.1", "main", "v0.2", "latest"])
def test_version_qui_n_est_pas_un_tag_refusee(version: str) -> None:
    with pytest.raises(ValueError, match="tag"):
        ds.space_files(version, REQS, REV)


def test_deploiement_pousse_les_secrets_avant_les_fichiers() -> None:
    api = FakeApi(["RUNNING"])
    files = ds.space_files("v0.2.1", REQS, REV)
    ds.deploy(api, SPACE, files, {"API_KEY": "k", "HF_TOKEN": "t"})
    kinds = [c[0] for c in api.calls]
    assert kinds == ["create_repo", "secret", "secret", "commit"]  # secrets avant le build
    assert api.calls[0][1]["space_sdk"] == "gradio"
    assert {c[1] for c in api.calls if c[0] == "secret"} == {"API_KEY", "HF_TOKEN"}
    assert set(api.calls[3][1]) == set(files)


def test_secret_vide_refuse_avant_tout_appel() -> None:
    api = FakeApi(["RUNNING"])
    with pytest.raises(ValueError, match="API_KEY"):
        ds.deploy(api, SPACE, {}, {"API_KEY": "", "HF_TOKEN": "t"})
    assert api.calls == []


def test_attente_jusqu_a_running() -> None:
    api = FakeApi(["BUILDING", "APP_STARTING", "RUNNING"])
    ds.wait_running(api, SPACE, timeout=60, poll=0, sleep=lambda _: None)


@pytest.mark.parametrize("stage", ["BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"])
def test_echec_du_space_interrompt_l_attente(stage: str) -> None:
    api = FakeApi(["BUILDING", stage])
    with pytest.raises(RuntimeError, match=stage):
        ds.wait_running(api, SPACE, timeout=60, poll=0, sleep=lambda _: None)


def test_delai_depasse() -> None:
    api = FakeApi(["BUILDING"])
    temps = iter([0.0, 30.0, 61.0])
    with pytest.raises(TimeoutError):
        ds.wait_running(
            api, SPACE, timeout=60, poll=0, sleep=lambda _: None, clock=lambda: next(temps)
        )


def _http(responses: dict[str, tuple[int, dict[str, Any]]]) -> Any:
    seen: list[tuple[str, dict[str, str]]] = []

    def fetch(method: str, url: str, headers: dict[str, str], body: bytes | None) -> Any:
        seen.append((url, headers))
        status, payload = responses[url.rsplit("/", 1)[-1]]
        return status, payload

    fetch.seen = seen  # type: ignore[attr-defined]
    return fetch


def test_test_de_fumee_verifie_version_et_prediction() -> None:
    fetch = _http(
        {
            "health": (200, {"status": "ok", "version": "0.2.1"}),
            "predict": (200, {"decision": "accordé", "model_version": "home-credit-serving v2"}),
        }
    )
    ds.smoke("https://x.hf.space", api_key="k", version="v0.2.1", fetch=fetch)
    predict_headers = fetch.seen[1][1]
    assert predict_headers["X-API-Key"] == "k"


def test_test_de_fumee_refuse_une_ancienne_version() -> None:
    fetch = _http({"health": (200, {"status": "ok", "version": "0.1.0"})})
    with pytest.raises(RuntimeError, match=r"0\.1\.0"):
        ds.smoke("https://x.hf.space", api_key="k", version="v0.2.1", fetch=fetch)


def test_test_de_fumee_refuse_une_prediction_en_erreur() -> None:
    fetch = _http(
        {
            "health": (200, {"status": "ok", "version": "0.2.1"}),
            "predict": (401, {"detail": "Clé d'API absente ou invalide"}),
        }
    )
    with pytest.raises(RuntimeError, match="401"):
        ds.smoke("https://x.hf.space", api_key="k", version="v0.2.1", fetch=fetch)


def test_corps_de_la_prediction_est_le_client_synthetique() -> None:
    body = json.loads(ds.smoke_payload())
    assert len(body) == 122
