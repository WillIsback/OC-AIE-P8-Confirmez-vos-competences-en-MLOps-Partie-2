"""Application FastAPI : scoring crédit sécurisé par clé d'API (ADR-001, ADR-002, ADR-003)."""

from __future__ import annotations

import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from credit_scoring import __version__
from credit_scoring.api.features_schema import EXAMPLE_CLIENT
from credit_scoring.api.schemas import ClientFeatures, ErrorMessage, PredictionResponse
from credit_scoring.api.scoring import load_demo_clients, score
from credit_scoring.api.security import configured_api_key, require_api_key
from credit_scoring.hub import ensure_artifacts
from credit_scoring.model import ScoringModel, get_model, model_dir


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Au démarrage : clé d'API, artefacts, modèle (chargé une seule fois), clients de démo.

    Une erreur ici (clé absente, artefacts absents ou altérés) empêche le service de
    démarrer : mieux vaut un Space en échec visible qu'une API qui répond avec un mauvais
    modèle.
    """
    app.state.api_key = configured_api_key()
    ensure_artifacts(model_dir())  # image sans données : téléchargées au 1er démarrage
    app.state.model = get_model()
    _ = app.state.model.importance  # calculée ici plutôt qu'à la première requête
    app.state.demo_clients = load_demo_clients(model_dir())
    yield


app = FastAPI(
    title="Confirmez vos compétences en MLOps (Partie 2/2)",
    version=__version__,
    description=(
        "Mise en production et monitoring du modèle de scoring crédit Home Credit "
        "(OC AI Engineer P8).\n\n"
        "Les routes `/predict` exigent l'en-tête `X-API-Key`. Une valeur invalide renvoie "
        "**422** ; une valeur plausible hors des bornes du jeu d'entraînement est acceptée "
        "et signalée dans `warnings`."
    ),
    lifespan=lifespan,
)

ERRORS_401: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorMessage, "description": "Clé d'API absente ou invalide"},
    422: {"description": "Requête invalide : champ manquant ou inconnu, type, règle métier"},
}

PREDICT_EXAMPLES: dict[str, Any] = {
    "client_valide": {
        "summary": "Client valide (synthétique : médianes du train)",
        "value": EXAMPLE_CLIENT,
    },
    "hors_bornes": {
        "summary": "Crédit au-delà du maximum vu à l'entraînement → 200 + avertissement",
        "value": {**EXAMPLE_CLIENT, "AMT_CREDIT": 5_000_000.0},
    },
    "regle_metier_violee": {
        "summary": "Foyer de 0 personne → 422",
        "value": {**EXAMPLE_CLIENT, "CNT_FAM_MEMBERS": 0},
    },
}


def _json_scalar(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, str | int | bool)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """422 compact : champ, message, type, et la valeur reçue si elle est scalaire et finie.

    Le gestionnaire par défaut renvoie l'entrée telle quelle : tout le corps pour un champ
    manquant, et une erreur 500 pour un NaN (non sérialisable en JSON).
    """
    detail = []
    for error in exc.errors():
        item: dict[str, Any] = {k: error[k] for k in ("loc", "msg", "type")}
        if "input" in error and _json_scalar(error["input"]):
            item["input"] = error["input"]
        detail.append(item)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": detail}
    )


def current_model(request: Request) -> ScoringModel:
    model: ScoringModel = request.app.state.model
    return model


ModelDep = Annotated[ScoringModel, Depends(current_model)]


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Sonde de vivacité : état et version déployée."""
    return {"status": "ok", "version": __version__}


@app.post(
    "/predict",
    tags=["scoring"],
    response_model=PredictionResponse,
    dependencies=[Depends(require_api_key)],
    responses=ERRORS_401,
)
def predict(
    client: Annotated[ClientFeatures, Body(openapi_examples=PREDICT_EXAMPLES)],
    model: ModelDep,
) -> PredictionResponse:
    """Score de défaut et décision pour un client décrit par ses 122 features."""
    return score(model, client)


@app.post(
    "/predict/{sk_id_curr}",
    tags=["scoring"],
    response_model=PredictionResponse,
    dependencies=[Depends(require_api_key)],
    responses={
        **ERRORS_401,
        404: {"model": ErrorMessage, "description": "Client absent de l'échantillon de démo"},
    },
)
def predict_demo(sk_id_curr: int, request: Request, model: ModelDep) -> PredictionResponse:
    """Démo : score d'un client de l'échantillon (1 000 clients du test), même validation."""
    raw = request.app.state.demo_clients.get(sk_id_curr)
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client {sk_id_curr} absent de l'échantillon de démo",
        )
    try:
        client = ClientFeatures.model_validate(raw)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**e, "loc": ("sample_clients", sk_id_curr, *e["loc"])} for e in exc.errors()]
        ) from exc
    return score(model, client, sk_id_curr=sk_id_curr)
