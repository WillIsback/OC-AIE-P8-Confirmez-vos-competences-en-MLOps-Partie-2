"""API de scoring : authentification, validation (ADR-001), prédiction, route de démo."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from credit_scoring.api.app import app
from credit_scoring.api.features_schema import EXAMPLE_CLIENT, NULLABLE_FEATURES
from credit_scoring.model import ArtifactError, get_model
from tests.conftest import (
    API_KEY,
    DEMO_INVALID_ID,
    DEMO_NULLABLE_ID,
    DEMO_VALID_ID,
    THRESHOLD,
)

AUTH = {"X-API-Key": API_KEY}


@pytest.fixture
def client(api_artifacts: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MODEL_DIR", str(api_artifacts))
    monkeypatch.setenv("API_KEY", API_KEY)
    get_model.cache_clear()
    with TestClient(app) as c:
        yield c
    get_model.cache_clear()


def payload(**overrides: Any) -> dict[str, Any]:
    return {**EXAMPLE_CLIENT, **overrides}


def errors(response: Any) -> list[tuple[str, str]]:
    """(champ, type d'erreur) de chaque erreur d'un 422."""
    return [(str(e["loc"][-1]), e["type"]) for e in response.json()["detail"]]


# --- prédiction ----------------------------------------------------------------------


def test_requete_valide_renvoie_score_decision_seuil(client: TestClient) -> None:
    r = client.post("/predict", json=payload(), headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["prob_default"] <= 1
    assert body["decision"] in {"accordé", "refusé"}
    assert body["threshold"] == THRESHOLD
    assert body["model_version"] == "test-model v1"
    assert body["warnings"] == []
    assert body["sk_id_curr"] is None


def test_decision_suit_le_score_et_le_seuil(client: TestClient) -> None:
    risque = client.post("/predict", json=payload(AMT_CREDIT=2_000_000.0), headers=AUTH)
    sur = client.post("/predict", json=payload(AMT_CREDIT=100_000.0), headers=AUTH)
    assert risque.json()["prob_default"] >= THRESHOLD
    assert risque.json()["decision"] == "refusé"
    assert sur.json()["prob_default"] < THRESHOLD
    assert sur.json()["decision"] == "accordé"


# --- authentification (ADR-003) --------------------------------------------------------


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "mauvaise-cle"}, {"X-API-Key": ""}])
def test_cle_absente_ou_fausse_refusee(client: TestClient, headers: dict[str, str]) -> None:
    r = client.post("/predict", json=payload(), headers=headers)
    assert r.status_code == 401
    assert r.json() == {"detail": "Clé d'API absente ou invalide (en-tête X-API-Key)."}


def test_authentification_verifiee_avant_la_validation(client: TestClient) -> None:
    r = client.post("/predict", json={"pas": "un client"})
    assert r.status_code == 401


@pytest.mark.parametrize("path", ["/health", "/docs", "/openapi.json"])
def test_routes_publiques_sans_cle(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


# --- validation : types et présence (ADR-001) ------------------------------------------


def test_champ_obligatoire_manquant(client: TestClient) -> None:
    body = payload()
    del body["AMT_CREDIT"]
    r = client.post("/predict", json=body, headers=AUTH)
    assert r.status_code == 422
    assert errors(r) == [("AMT_CREDIT", "missing")]


def test_mauvais_type(client: TestClient) -> None:
    r = client.post("/predict", json=payload(AMT_CREDIT="beaucoup"), headers=AUTH)
    assert r.status_code == 422
    assert errors(r) == [("AMT_CREDIT", "float_parsing")]


def test_null_refuse_sur_une_feature_non_nullable(client: TestClient) -> None:
    r = client.post("/predict", json=payload(AMT_CREDIT=None), headers=AUTH)
    assert r.status_code == 422
    assert errors(r)[0][0] == "AMT_CREDIT"


def test_null_accepte_sur_une_feature_nullable(client: TestClient) -> None:
    nullable = sorted(NULLABLE_FEATURES)[0]
    r = client.post("/predict", json=payload(**{nullable: None}), headers=AUTH)
    assert r.status_code == 200


def test_nan_refuse(client: TestClient) -> None:
    content = json.dumps(payload(AMT_CREDIT=float("nan")))  # json.dumps écrit NaN
    r = client.post(
        "/predict", content=content, headers={**AUTH, "Content-Type": "application/json"}
    )
    assert r.status_code == 422
    assert errors(r)[0][0] == "AMT_CREDIT"


def test_champ_inconnu_refuse(client: TestClient) -> None:
    r = client.post("/predict", json=payload(AMT_CREDTI=1.0), headers=AUTH)
    assert r.status_code == 422
    assert errors(r) == [("AMT_CREDTI", "extra_forbidden")]


def test_categorie_hors_liste_refusee(client: TestClient) -> None:
    r = client.post("/predict", json=payload(CODE_GENDER="m"), headers=AUTH)
    assert r.status_code == 422
    assert errors(r) == [("CODE_GENDER", "literal_error")]


# --- validation : règles métier ---------------------------------------------------------


@pytest.mark.parametrize(
    ("feature", "value"),
    [
        ("AMT_CREDIT", 0.0),
        ("AMT_CREDIT", -1.0),
        ("FLAG_EMAIL", 2),
        ("FLAG_DOCUMENT_3", 0.5),
        ("REG_CITY_NOT_WORK_CITY", -1),
        ("CNT_FAM_MEMBERS", 0),
        ("CNT_FAM_MEMBERS", 2.5),
        ("INST_COUNT", -1),
        ("DEF_30_CNT_SOCIAL_CIRCLE", -3),
        ("POS_CNT_INSTALMENT_FUTURE_MEAN", -0.1),
        ("PREV_DAYS_DECISION_MEAN", 5.0),
        ("BUR_DAYS_CREDIT_MIN", 1.0),
        ("DAYS_REGISTRATION", -1.0),
        ("OWN_CAR_AGE", -2.0),
        ("HOUR_APPR_PROCESS_START", 24),  # règle de William
        ("HOUR_APPR_PROCESS_START", -1),
        ("HOUR_APPR_PROCESS_START", 12.5),
    ],
)
def test_regle_metier_violee(client: TestClient, feature: str, value: float) -> None:
    r = client.post("/predict", json=payload(**{feature: value}), headers=AUTH)
    assert r.status_code == 422
    assert [field for field, _ in errors(r)] == [feature]
    assert r.json()["detail"][0]["msg"]  # message explicite


@pytest.mark.parametrize(
    ("feature", "value"),
    [
        ("AMT_CREDIT", 0.01),
        ("FLAG_EMAIL", 1),
        ("FLAG_EMAIL", 1.0),
        ("CNT_FAM_MEMBERS", 1),
        ("INST_COUNT", 0),
        ("PREV_DAYS_DECISION_MEAN", 0.0),
        ("DAYS_REGISTRATION", 0.0),
        ("OWN_CAR_AGE", 0.0),
        ("HOUR_APPR_PROCESS_START", 0),
        ("HOUR_APPR_PROCESS_START", 23),
        ("HOUR_APPR_PROCESS_START", 23.0),
        ("PREV_DAYS_LAST_DUE_1ST_VERSION_MAX", 2_000.0),  # échéance prévue : future possible
    ],
)
def test_valeurs_limites_acceptees(client: TestClient, feature: str, value: float) -> None:
    r = client.post("/predict", json=payload(**{feature: value}), headers=AUTH)
    assert r.status_code == 200


# --- valeurs inhabituelles : acceptées avec avertissement ----------------------------------


def test_hors_bornes_du_train_accepte_avec_avertissement(client: TestClient) -> None:
    r = client.post("/predict", json=payload(AMT_CREDIT=5_000_000.0), headers=AUTH)
    assert r.status_code == 200
    warnings = r.json()["warnings"]
    message = warnings[0].pop("message")
    assert message.startswith(
        "AMT_CREDIT = 5000000.0 hors des bornes du jeu d'entraînement "
        "[45000.0 ; 4050000.0] ; importance : rang 1/122"
    )
    assert warnings == [
        {
            "feature": "AMT_CREDIT",
            "value": 5_000_000.0,
            "min": 45_000.0,
            "max": 4_050_000.0,
            "importance_rank": 1,
            "importance_share": warnings[0]["importance_share"],
        }
    ]


def test_valeur_aux_bornes_sans_avertissement(client: TestClient) -> None:
    r = client.post("/predict", json=payload(AMT_CREDIT=4_050_000.0), headers=AUTH)
    assert r.json()["warnings"] == []


def test_null_nullable_sans_avertissement(client: TestClient) -> None:
    nullable = sorted(NULLABLE_FEATURES)[0]
    r = client.post("/predict", json=payload(**{nullable: None}), headers=AUTH)
    assert r.json()["warnings"] == []


# --- route de démo -------------------------------------------------------------------------


def test_demo_client_connu(client: TestClient) -> None:
    direct = client.post("/predict", json=payload(), headers=AUTH).json()
    r = client.post(f"/predict/{DEMO_VALID_ID}", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["sk_id_curr"] == DEMO_VALID_ID
    assert r.json()["prob_default"] == pytest.approx(direct["prob_default"])


def test_demo_client_avec_valeurs_manquantes(client: TestClient) -> None:
    assert client.post(f"/predict/{DEMO_NULLABLE_ID}", headers=AUTH).status_code == 200


def test_demo_passe_par_la_meme_validation(client: TestClient) -> None:
    r = client.post(f"/predict/{DEMO_INVALID_ID}", headers=AUTH)
    assert r.status_code == 422
    assert [field for field, _ in errors(r)] == ["CNT_FAM_MEMBERS"]


def test_demo_client_inconnu(client: TestClient) -> None:
    r = client.post("/predict/1", headers=AUTH)
    assert r.status_code == 404
    assert "1" in r.json()["detail"]


def test_demo_exige_la_cle(client: TestClient) -> None:
    assert client.post(f"/predict/{DEMO_VALID_ID}").status_code == 401


# --- démarrage et documentation -------------------------------------------------------------


def test_demarrage_refuse_sans_cle_configuree(
    api_artifacts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_DIR", str(api_artifacts))
    monkeypatch.delenv("API_KEY", raising=False)
    get_model.cache_clear()
    with pytest.raises(RuntimeError, match="API_KEY"), TestClient(app):
        pass


def test_demarrage_refuse_sans_artefacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("API_KEY", API_KEY)
    get_model.cache_clear()
    with pytest.raises(ArtifactError), TestClient(app):
        pass
    get_model.cache_clear()


def test_swagger_documente_exemples_et_erreurs(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    predict = spec["paths"]["/predict"]["post"]
    examples = predict["requestBody"]["content"]["application/json"]["examples"]
    assert {"client_valide", "hors_bornes", "regle_metier_violee"} <= set(examples)
    assert {"200", "401", "422"} <= set(predict["responses"])
    demo = spec["paths"]["/predict/{sk_id_curr}"]["post"]
    assert {"200", "401", "404", "422"} <= set(demo["responses"])
    assert spec["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"


def test_detail_422_compact(client: TestClient) -> None:
    body = payload()
    del body["AMT_CREDIT"]
    detail = client.post("/predict", json=body, headers=AUTH).json()["detail"]
    assert detail == [{"loc": ["body", "AMT_CREDIT"], "msg": "Field required", "type": "missing"}]
    bad = client.post("/predict", json=payload(CNT_FAM_MEMBERS=0), headers=AUTH).json()
    assert bad["detail"][0]["input"] == 0


def test_avertissement_porte_l_importance_globale(client: TestClient) -> None:
    w = client.post("/predict", json=payload(AMT_CREDIT=5_000_000.0), headers=AUTH).json()
    warning = w["warnings"][0]
    assert warning["importance_rank"] == 1  # seule feature qui pilote la cible synthétique
    assert 0 < warning["importance_share"] <= 1
    assert "rang 1/122" in warning["message"]
