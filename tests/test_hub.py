"""Téléchargement des artefacts au démarrage (ADR-002, option A) — sans réseau."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from credit_scoring import hub
from credit_scoring.hub import ensure_artifacts, pinned_revision

SHA = "7d1a4cbeddbf4301e0d6ede8ca0604197b8d7739"


def test_revision_figee_lue_depuis_le_fichier(tmp_path: Path) -> None:
    f = tmp_path / "model_revision.txt"
    f.write_text(SHA + "\n", encoding="utf-8")
    assert pinned_revision(f) == SHA


@pytest.mark.parametrize("contenu", ["main", "", "7d1a4cb", "z" * 40])
def test_revision_qui_n_est_pas_un_sha_complet_refusee(tmp_path: Path, contenu: str) -> None:
    f = tmp_path / "model_revision.txt"
    f.write_text(contenu, encoding="utf-8")
    with pytest.raises(ValueError, match="SHA"):
        pinned_revision(f)


def test_artefacts_deja_presents_pas_de_telechargement(
    tiny_artifacts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interdit(**_: Any) -> str:
        raise AssertionError("aucun téléchargement attendu")

    monkeypatch.setattr(hub, "snapshot_download", interdit)
    assert ensure_artifacts(tiny_artifacts, revision=SHA) is False


def test_artefacts_absents_telecharges_a_la_revision_figee(
    tiny_artifacts: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    appels: list[dict[str, Any]] = []

    def faux_hub(**kwargs: Any) -> str:
        appels.append(kwargs)
        shutil.copytree(tiny_artifacts, kwargs["local_dir"], dirs_exist_ok=True)
        return str(kwargs["local_dir"])

    monkeypatch.setattr(hub, "snapshot_download", faux_hub)
    dest = tmp_path / "artifacts"
    assert ensure_artifacts(dest, revision=SHA) is True
    assert appels == [
        {"repo_id": hub.REPO_ID, "revision": SHA, "local_dir": dest, "repo_type": "model"}
    ]
    assert (dest / "manifest.json").is_file()
