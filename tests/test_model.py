"""Module de chargement et de prédiction, sur des artefacts miniatures."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from credit_scoring import model as model_mod
from credit_scoring.model import ArtifactError, ScoringModel, get_model, load_model


def _frame(**overrides: object) -> pd.DataFrame:
    row: dict[str, object] = {
        "AMT_CREDIT": 700_000.0,
        "CODE_GENDER": "M",
        "DAYS_REGISTRATION": -2_000.0,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_encode_ordre_du_modele_et_codes_categoriels(tiny_artifacts: Path) -> None:
    m = load_model(tiny_artifacts)
    x = m.encode(_frame())
    # Colonnes réordonnées : CODE_GENDER (M -> 1), AMT_CREDIT, DAYS_REGISTRATION
    np.testing.assert_array_equal(x, np.array([[1.0, 700_000.0, -2_000.0]]))


def test_encode_categorie_inconnue_ou_manquante_vaut_moins_un(tiny_artifacts: Path) -> None:
    m = load_model(tiny_artifacts)
    x = m.encode(pd.concat([_frame(CODE_GENDER="Z"), _frame(CODE_GENDER=None)]))
    np.testing.assert_array_equal(x[:, 0], [-1.0, -1.0])


def test_encode_numerique_manquant_reste_nan(tiny_artifacts: Path) -> None:
    m = load_model(tiny_artifacts)
    x = m.encode(_frame(AMT_CREDIT=None))
    assert np.isnan(x[0, 1])


def test_encode_colonne_absente_refusee(tiny_artifacts: Path) -> None:
    m = load_model(tiny_artifacts)
    with pytest.raises(ValueError, match="DAYS_REGISTRATION"):
        m.encode(_frame().drop(columns=["DAYS_REGISTRATION"]))


def test_predict_score_decision_seuil(tiny_artifacts: Path) -> None:
    m = load_model(tiny_artifacts)
    out = m.predict(pd.concat([_frame(AMT_CREDIT=900_000.0), _frame(AMT_CREDIT=150_000.0)]))
    assert list(out.columns) == ["prob_default", "decision", "threshold"]
    assert out["prob_default"].between(0, 1).all()
    assert out["decision"].tolist() == [1, 0]
    assert (out["threshold"] == m.threshold).all()


def test_predict_decision_au_seuil_exact_est_un_refus(tiny_artifacts: Path) -> None:
    m = load_model(tiny_artifacts)
    proba = float(m.predict(_frame())["prob_default"].iloc[0])
    au_seuil = ScoringModel(m.booster, m.features, proba, m.manifest)
    assert int(au_seuil.predict(_frame())["decision"].iloc[0]) == 1


def test_manifeste_expose_version_et_seuil(tiny_artifacts: Path) -> None:
    m = load_model(tiny_artifacts)
    assert m.version == "test-model v1"
    assert m.threshold == 0.5


def test_empreinte_modifiee_refusee(tiny_artifacts: Path, tmp_path: Path) -> None:
    altered = tmp_path / "artifacts"
    shutil.copytree(tiny_artifacts, altered)
    with (altered / "features.json").open("a", encoding="utf-8") as f:
        f.write(" ")
    with pytest.raises(ArtifactError, match=r"features\.json"):
        load_model(altered)


def test_fichier_manquant_refuse(tiny_artifacts: Path, tmp_path: Path) -> None:
    altered = tmp_path / "artifacts"
    shutil.copytree(tiny_artifacts, altered)
    (altered / "model.txt").unlink()
    with pytest.raises(ArtifactError, match=r"model\.txt"):
        load_model(altered)


def test_dossier_sans_manifeste_refuse(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match=r"manifest\.json"):
        load_model(tmp_path)


def test_manifeste_sans_liste_de_fichiers_refuse(tiny_artifacts: Path, tmp_path: Path) -> None:
    altered = tmp_path / "artifacts"
    shutil.copytree(tiny_artifacts, altered)
    manifest = json.loads((altered / "manifest.json").read_text(encoding="utf-8"))
    del manifest["files"]
    (altered / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactError, match="files"):
        load_model(altered)


def test_get_model_charge_une_seule_fois(
    tiny_artifacts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_model.cache_clear()
    appels: list[Path] = []
    original = model_mod.load_model

    def compteur(model_dir: Path) -> ScoringModel:
        appels.append(model_dir)
        return original(model_dir)

    monkeypatch.setattr(model_mod, "load_model", compteur)
    monkeypatch.setenv("MODEL_DIR", str(tiny_artifacts))
    premier = get_model()
    second = get_model()
    assert premier is second
    assert len(appels) == 1
    get_model.cache_clear()
