"""Artefacts du modèle sur le Hub Hugging Face, téléchargés au démarrage (ADR-002, option A).

L'image Docker est publique et ne contient aucune donnée : au premier démarrage, le service
télécharge le dépôt modèle **privé** à la révision figée (`model_revision.txt`, un SHA de
commit, jamais `main`), avec le secret `HF_TOKEN`. `load_model` vérifie ensuite les
empreintes SHA-256 du manifeste : un téléchargement incomplet ou altéré empêche le
démarrage.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from huggingface_hub import snapshot_download

from credit_scoring.model import MANIFEST_FILE

REPO_ID = "WillIsback/home-credit-scoring"
DEFAULT_REVISION_FILE = Path("model_revision.txt")
_SHA = re.compile(r"[0-9a-f]{40}")


def revision_file() -> Path:
    """Fichier de révision : `MODEL_REVISION_FILE`, `model_revision.txt` sinon."""
    return Path(os.environ.get("MODEL_REVISION_FILE", str(DEFAULT_REVISION_FILE)))


def pinned_revision(path: Path) -> str:
    """SHA de commit complet du dépôt modèle ; refuse une branche ou un SHA abrégé."""
    revision = path.read_text(encoding="utf-8").strip()
    if not _SHA.fullmatch(revision):
        raise ValueError(f"{path.name} doit contenir un SHA de commit complet (40 caractères)")
    return revision


def ensure_artifacts(model_dir: Path, revision: str | None = None) -> bool:
    """Télécharge les artefacts s'ils sont absents. Renvoie True si un téléchargement a eu lieu."""
    if (model_dir / MANIFEST_FILE).is_file():
        return False
    snapshot_download(
        repo_id=REPO_ID,
        revision=revision or pinned_revision(revision_file()),
        local_dir=model_dir,
        repo_type="model",
    )
    return True
