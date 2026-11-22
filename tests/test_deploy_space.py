"""Déploiement sur le Space Hugging Face (#15) — faux client Hub, aucun appel réseau."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import deploy_space as ds

SPACE = "WillisBack/credit-scoring-api"


class FakeApi:
    def __init__(
        self,
        stages: list[str],
        host: str = "https://willisback-credit.hf.space",
        hardware: str = "cpu-basic",
    ):
        self.stages = stages
        self.host = host
        self.hardware = hardware
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
        return SimpleNamespace(stage=stage, requested_hardware=self.hardware)

    def request_space_hardware(self, repo_id: str, hardware: str) -> None:
        self.calls.append(("hardware", getattr(hardware, "value", hardware)))

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
    assert "from credit_scoring.api.app import app" in files["app.py"].decode()
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
    ds.deploy(api, SPACE, files, {"API_KEY": "k", "HF_TOKEN": "t", "DATABASE_URL": "pg"})
    kinds = [c[0] for c in api.calls]
    assert kinds == ["create_repo", "secret", "secret", "secret", "commit"]  # avant le build
    assert api.calls[0][1]["space_sdk"] == "gradio"
    assert {c[1] for c in api.calls if c[0] == "secret"} == {"API_KEY", "HF_TOKEN", "DATABASE_URL"}
    assert set(api.calls[4][1]) == set(files)


def test_materiel_du_space_jamais_modifie() -> None:
    # ZeroGPU est le choix de William ; le rétrograder exige PRO (402, #38)
    api = FakeApi(["RUNNING"], hardware="zero-a10g")
    ds.deploy(api, SPACE, ds.space_files("v0.2.5", REQS, REV), {"API_KEY": "k", "HF_TOKEN": "t"})
    assert "hardware" not in [c[0] for c in api.calls]


def test_app_annonce_l_api_a_zerogpu() -> None:
    # spaces importé avant l'app : il remplace gr.mount_gradio_app, qui ajoute alors
    # ZeroGPUMiddleware (startup report) ; l'envelopper à la main l'enverrait deux fois.
    app_py = ds.space_files("v0.3.0", REQS, REV)["app.py"].decode()
    assert app_py.index("import spaces") < app_py.index("credit_scoring")
    assert "@spaces.GPU\ndef " in app_py
    assert "ZeroGPUMiddleware(app)" not in app_py
    assert "from spaces.zero import" not in app_py
    assert "access_log=False" in app_py  # logs d'accès : chemin réel /predict/<SK_ID_CURR>
    compile(app_py, "app.py", "exec")


def test_export_avec_extra_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        seen.append(cmd)
        return SimpleNamespace(stdout="gradio==6.32.0\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert ds.locked_requirements() == "gradio==6.32.0\n"
    cmd = seen[0]
    assert cmd[cmd.index("--extra") + 1] == "ui"


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
    assert predict_headers["X-Client"] == "ci"  # trafic de CI distingué (#16, A1)


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


def test_secrets_du_space(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {"API_KEY": "k", "SPACE_HF_TOKEN": "t", "DATABASE_URL": "pg"}.items():
        monkeypatch.setenv(key, value)
    assert ds.space_secrets() == {"API_KEY": "k", "HF_TOKEN": "t", "DATABASE_URL": "pg"}
