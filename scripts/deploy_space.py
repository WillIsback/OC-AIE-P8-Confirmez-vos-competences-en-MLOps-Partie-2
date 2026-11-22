"""Déploie une version taguée sur le Space Hugging Face (SDK Gradio), puis la vérifie.

    uv run python scripts/deploy_space.py --version v0.2.1

Variables d'environnement : `HF_TOKEN` (écriture sur le Space) ; `API_KEY`,
`SPACE_HF_TOKEN` (lecture du dépôt modèle privé) et `DATABASE_URL` (journaux de production,
#16), poussés comme secrets du Space.

Étapes :
1. crée le Space s'il n'existe pas (son matériel, ZeroGPU, n'est jamais modifié) ;
2. pousse les secrets **avant** les fichiers, pour que le build qui suit les trouve ;
3. pousse les fichiers du Space : le SDK Docker étant payant, le Space est en SDK Gradio
   et son `app.py` lance l'API FastAPI et son interface Gradio (uvicorn, port 7860) ; le
   montage de l'interface, après `import spaces`, ajoute le middleware qui envoie à ZeroGPU
   le « startup report » sans lequel il arrête le Space (#38, #40).
   `requirements.txt` reprend les versions exactes de `uv.lock` et installe le paquet
   **depuis le tag** : même code et mêmes versions que la release, environnement
   reconstruit par le Space (#29) ;
4. attend que le Space soit `RUNNING` (échec immédiat sur une erreur de build ou
   d'exécution) ;
5. test de fumée sur l'URL publique : `/health` doit annoncer la version déployée, et une
   prédiction authentifiée doit répondre 200.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from credit_scoring.api.features_schema import EXAMPLE_CLIENT  # noqa: E402

SPACE_ID = "WillisBack/credit-scoring-api"
GIT_URL = "https://github.com/WillIsback/OC-AIE-P8-Confirmez-vos-competences-en-MLOps-Partie-2"
GRADIO_VERSION = "6.32.0"  # le Space installe gradio[oauth,mcp] : pydantic <= 2.12.5 (#31)
_TAG = re.compile(r"v\d+\.\d+\.\d+")
ERROR_STAGES = {"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE"}

README = """---
title: Credit Scoring API
emoji: 🏦
colorFrom: blue
colorTo: gray
sdk: gradio
sdk_version: {gradio}
python_version: "3.12"
app_file: app.py
pinned: false
short_description: API de scoring crédit Home Credit (OC AI Engineer P8)
---

Déployé automatiquement par la CI/CD de {git_url} (version {version}).

Documentation interactive : `/docs` ; les routes `/predict` exigent l'en-tête `X-API-Key`.
"""

APP_PY = '''"""Point d'entrée du Space (SDK Gradio, matériel ZeroGPU) : API FastAPI + interface.

ZeroGPU arrête le Space s'il ne reçoit pas de « startup report » au démarrage. `spaces`,
importé en premier, remplace `gr.mount_gradio_app` : le montage de l'interface à « / »
(#40) ajoute alors `ZeroGPUMiddleware`, qui envoie ce rapport au démarrage du lifespan.
Le scoring (LightGBM) reste sur CPU : aucun quota GPU n'est consommé.
"""

import os

import spaces  # en premier : active le mode ZeroGPU et remplace gr.mount_gradio_app
import uvicorn

from credit_scoring.api.app import app


@spaces.GPU
def gpu_declaree() -> None:
    """Fonction GPU déclarée comme l'exige ZeroGPU ; jamais appelée (scoring sur CPU)."""


uvicorn.run(
    app,
    host="0.0.0.0",
    port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
    # Les logs d'accès montreraient le chemin réel /predict/<SK_ID_CURR> ; la ligne JSON
    # pseudonymisée de chaque appel (#16) les remplace.
    access_log=False,
)
'''

Fetch = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, Any]]]


def locked_requirements() -> str:
    """Dépendances d'exécution aux versions exactes de uv.lock (sans le projet)."""
    return subprocess.run(
        [  # noqa: S607 - uv fourni par la CI (setup-uv)
            "uv",
            "export",
            "--no-dev",
            "--no-hashes",
            "--no-emit-project",
            "--extra",
            "ui",  # interface Gradio (#40)
            "--quiet",
            "--format",
            "requirements-txt",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout


def space_files(version: str, requirements: str, revision: str) -> dict[str, bytes]:
    """Fichiers du Space Gradio pour une version taguée."""
    if not _TAG.fullmatch(version):
        raise ValueError(f"version {version!r} : attendu un tag vX.Y.Z")
    lines = [
        x.strip() for x in requirements.splitlines() if x.strip() and not x.strip().startswith("#")
    ]
    lines.append(f"credit-scoring @ git+{GIT_URL}@{version}")
    readme = README.format(gradio=GRADIO_VERSION, git_url=GIT_URL, version=version)
    return {
        "README.md": readme.encode(),
        "app.py": APP_PY.encode(),
        "requirements.txt": ("\n".join(lines) + "\n").encode(),
        "packages.txt": b"libgomp1\n",
        "model_revision.txt": (revision.strip() + "\n").encode(),
    }


def deploy(api: Any, repo_id: str, files: dict[str, bytes], secrets: dict[str, str]) -> None:
    """Crée le Space si besoin, pousse les secrets puis les fichiers (déclenche le build)."""
    from huggingface_hub import CommitOperationAdd

    empty = [k for k, v in secrets.items() if not v]
    if empty:
        raise ValueError(f"Secrets vides : {', '.join(empty)}")
    api.create_repo(repo_id=repo_id, repo_type="space", space_sdk="gradio", exist_ok=True)
    for key, value in secrets.items():
        api.add_space_secret(repo_id, key, value)
    api.create_commit(
        repo_id=repo_id,
        repo_type="space",
        operations=[CommitOperationAdd(path, content) for path, content in files.items()],
        commit_message="Déploiement automatique (CI/CD)",
    )


def wait_running(
    api: Any,
    repo_id: str,
    timeout: float = 900,
    poll: float = 15,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Attend l'état RUNNING ; lève dès une erreur de build ou d'exécution."""
    start = clock()
    while True:
        stage = str(api.get_space_runtime(repo_id).stage)
        print(f"   Space : {stage}")
        if stage == "RUNNING":
            return
        if stage in ERROR_STAGES:
            raise RuntimeError(f"Le Space est en échec : {stage}")
        if clock() - start > timeout:
            raise TimeoutError(f"Space toujours en {stage} après {timeout:.0f} s")
        sleep(poll)


def _urllib_fetch(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.status, _json_or_raw(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _json_or_raw(exc.read())


def _json_or_raw(body: bytes) -> dict[str, Any]:
    """Corps JSON, ou début du texte : juste après RUNNING, le proxy du Space peut servir
    une page HTML d'attente ou d'erreur ; l'essai échoue alors proprement et sera rejoué."""
    try:
        parsed = json.loads(body or b"{}")
    except ValueError:
        return {"_non_json": body[:200].decode("utf-8", "replace")}
    return parsed if isinstance(parsed, dict) else {"_json": parsed}


def smoke_payload() -> bytes:
    return json.dumps(EXAMPLE_CLIENT).encode()


def smoke(url: str, api_key: str, version: str, fetch: Fetch = _urllib_fetch) -> None:
    """Vérifie que l'URL publique sert la bonne version et prédit avec la clé."""
    status, health = fetch("GET", f"{url}/health", {}, None)
    expected = version.removeprefix("v")
    if status != 200 or health.get("version") != expected:
        raise RuntimeError(f"/health : {status} {health} (version attendue {expected})")
    # X-Client: ci : le trafic du test de fumée est exclu des analyses de production (#16).
    headers = {"X-API-Key": api_key, "Content-Type": "application/json", "X-Client": "ci"}
    status, prediction = fetch("POST", f"{url}/predict", headers, smoke_payload())
    if status != 200:
        raise RuntimeError(f"/predict : {status} {prediction}")
    print(f"✅ {url} : v{expected}, prédiction « {prediction.get('decision')} »")


def space_secrets() -> dict[str, str]:
    """Secrets poussés au Space (noms côté Space ; valeurs lues dans l'environnement)."""
    return {
        "API_KEY": os.environ.get("API_KEY", ""),
        "HF_TOKEN": os.environ.get("SPACE_HF_TOKEN", ""),
        "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
    }


def main() -> int:
    from huggingface_hub import HfApi

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True, help="tag déployé (vX.Y.Z)")
    parser.add_argument("--space", default=SPACE_ID)
    args = parser.parse_args()
    api = HfApi()  # HF_TOKEN
    secrets = space_secrets()
    revision = (ROOT / "model_revision.txt").read_text(encoding="utf-8")
    files = space_files(args.version, locked_requirements(), revision)
    deploy(api, args.space, files, secrets)
    time.sleep(20)  # laisse le Space passer en BUILDING avant de le sonder
    wait_running(api, args.space)
    url = str(getattr(api.space_info(args.space), "host", "") or "").rstrip("/")
    if not url:
        owner, name = args.space.lower().split("/")
        url = f"https://{owner}-{name}.hf.space"
    for attempt in range(1, 7):  # le proxy du Space peut répondre 503 juste après RUNNING
        try:
            smoke(url, secrets["API_KEY"], args.version)
            return 0
        except RuntimeError as exc:
            print(f"   test de fumée, essai {attempt}/6 : {exc}")
            time.sleep(10)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
