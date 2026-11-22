"""Contrat d'entrée et de sortie de l'API (ADR-001, contrat validé par William le 22/11/2026).

- **Invalide → 422** : champ manquant, champ inconnu, mauvais type, `null` sur une feature
  non nullable, NaN/infini, catégorie hors liste, règle métier violée (ci-dessous).
- **Inhabituel → 200 + avertissement** : valeur plausible hors des bornes du jeu
  d'entraînement (voir `credit_scoring.api.scoring.out_of_bounds`).

Les types des 122 features viennent du module généré `features_schema`. Ici, seules les
features lisibles reçoivent une règle métier ; les 79 `autoFE_*` (formules OpenFE sans sens
métier) n'ont que le contrôle des bornes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from credit_scoring.api.features_schema import GeneratedFeatures

BOOLEEN = "indicateur : 0 ou 1"
COMPTEUR = "nombre d'événements : jamais négatif"
JOURS_PASSES = "jours relatifs à la demande : un événement passé est daté avant (≤ 0)"
DUREE = "durée : jamais négative"


class ClientFeatures(GeneratedFeatures):
    """Les 122 features d'un client, avec les règles métier des features lisibles."""

    # Montant demandé : un crédit de 0 € ou moins n'existe pas.
    AMT_CREDIT: float = Field(gt=0, description="montant du crédit demandé (> 0)")

    # Indicateurs booléens.
    FLAG_EMAIL: int = Field(ge=0, le=1, description=BOOLEEN)
    FLAG_CONT_MOBILE: int = Field(ge=0, le=1, description=BOOLEEN)
    FLAG_DOCUMENT_3: int = Field(ge=0, le=1, description=BOOLEEN)
    REG_CITY_NOT_WORK_CITY: int = Field(ge=0, le=1, description=BOOLEEN)

    # Foyer : le demandeur en fait partie.
    CNT_FAM_MEMBERS: int = Field(ge=1, description="taille du foyer, demandeur compris (≥ 1)")

    # Compteurs (entiers) et moyennes de compteurs.
    INST_COUNT: int = Field(ge=0, description=COMPTEUR)
    INST_PREV_COUNT: int = Field(ge=0, description=COMPTEUR)
    PREV_CANCELED_COUNT: int = Field(ge=0, description=COMPTEUR)
    OBS_60_CNT_SOCIAL_CIRCLE: int = Field(ge=0, description=COMPTEUR)
    DEF_30_CNT_SOCIAL_CIRCLE: int = Field(ge=0, description=COMPTEUR)
    PREV_CNT_PAYMENT_MEAN: float = Field(ge=0, description=COMPTEUR)
    POS_CNT_INSTALMENT_FUTURE_MEAN: float = Field(ge=0, description=COMPTEUR)

    # Dates d'événements passés, en jours relatifs à la demande. Pas
    # PREV_DAYS_LAST_DUE_1ST_VERSION_MAX : une échéance prévue peut être future.
    PREV_DAYS_DECISION_MEAN: float = Field(le=0, description=JOURS_PASSES)
    PREV_DAYS_TERMINATION_MAX: float = Field(le=0, description=JOURS_PASSES)
    PREV_REF_DAYS_DECISION_MAX: float = Field(le=0, description=JOURS_PASSES)
    BUR_DAYS_CREDIT_MIN: float = Field(le=0, description=JOURS_PASSES)
    BUR_ACT_DAYS_CREDIT_MEAN: float = Field(le=0, description=JOURS_PASSES)
    INST_DAYS_ENTRY_PAYMENT_MAX: float = Field(le=0, description=JOURS_PASSES)

    # Durées positives (P6 a converti DAYS_REGISTRATION en années).
    DAYS_REGISTRATION: float = Field(ge=0, description="ancienneté de l'enregistrement, en années")
    OWN_CAR_AGE: float = Field(ge=0, description="âge du véhicule, en années")

    # HOUR_APPR_PROCESS_START : règle à écrire par William (#12, part 👤).


class FeatureWarning(BaseModel):
    """Valeur acceptée mais hors des bornes du jeu d'entraînement."""

    feature: str
    value: float
    min: float
    max: float
    importance_rank: int = Field(description="rang d'importance globale (1 = la plus forte)")
    importance_share: float = Field(description="part du gain total du modèle (0 à 1)")
    message: str


class PredictionResponse(BaseModel):
    """Score, décision et traçabilité d'une prédiction."""

    sk_id_curr: int | None = Field(None, description="identifiant client (route de démo)")
    prob_default: float = Field(description="probabilité de défaut estimée")
    decision: Literal["accordé", "refusé"] = Field(description="refusé si prob_default ≥ threshold")
    threshold: float = Field(description="seuil métier (coût FN = 10 x coût FP)")
    model_version: str
    warnings: list[FeatureWarning] = Field(
        description="valeurs hors des bornes du jeu d'entraînement (acceptées)"
    )


class ErrorMessage(BaseModel):
    """Erreur simple (401, 404)."""

    detail: str
