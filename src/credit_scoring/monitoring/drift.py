"""Analyse de dérive des données de production (#17) avec Evidently.

Module partagé par le job planifié (`scripts/drift_job.py`) et le notebook : même calcul
partout. Evidently 0.7.23 ne s'importe pas avec pandas 3 : ce module ne tourne que dans le
sous-projet `analysis/` (pandas 2.3) ; l'API et le Space ne l'importent jamais.

Tests par défaut d'Evidently (référence > 1 000 lignes) : distance de Wasserstein
normalisée (numériques), distance de Jensen-Shannon (catégorielles et numériques à peu de
valeurs), seuil 0,1. Une colonne entièrement vide dans la fenêtre est écartée et signalée.
Sous 1 000 appels, le bruit d'échantillonnage dépasse ce seuil : pas de calcul.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import sqlalchemy as sa

from credit_scoring.monitoring.schema import drift_reports, prediction_logs

# En dessous : « échantillon insuffisant ». Mesuré en revue (référence contre elle-même) :
# 16 à 26 % de features « en dérive » à 200 appels, une à 400, aucune à 1 000.
MIN_CURRENT = 1000
SCORE = "prob_default"
EMPTY = "vide"


@dataclass(frozen=True)
class DriftResult:
    summary: dict[str, Any]
    html: str | None


def production_frame(
    engine: sa.Engine, window: timedelta, now: datetime | None = None
) -> pd.DataFrame:
    """Features et score des appels réussis de production (`source = 'api'`) de la fenêtre."""
    end = now or datetime.now(UTC)
    query = sa.select(prediction_logs.c.features, prediction_logs.c.prob_default).where(
        prediction_logs.c.source == "api",
        prediction_logs.c.status_code == 200,
        prediction_logs.c.created_at >= end - window,
        prediction_logs.c.created_at <= end,
    )
    with engine.connect() as conn:
        rows = conn.execute(query).all()
    records = [{**(features or {}), SCORE: prob} for features, prob in rows]
    return pd.DataFrame.from_records(records)


def _decide(stat: float, method: str, threshold: float) -> bool:
    """Distance : dérive si ≥ seuil ; test statistique (p-value) : dérive si < seuil."""
    return stat < threshold if "p_value" in method else stat >= threshold


def _run_report(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    numerical: list[str],
    categorical: list[str],
) -> tuple[list[dict[str, Any]], str]:
    from evidently import DataDefinition, Dataset, Report
    from evidently.metrics import ValueDrift
    from evidently.presets import DataDriftPreset

    columns = [*numerical, *categorical]
    definition = DataDefinition(
        numerical_columns=[*numerical, SCORE], categorical_columns=categorical
    )
    report = Report([DataDriftPreset(columns=columns), ValueDrift(column=SCORE)])
    keep = [*columns, SCORE]
    snapshot = report.run(
        Dataset.from_pandas(current[keep], data_definition=definition),
        Dataset.from_pandas(reference[keep], data_definition=definition),
    )
    results = [
        {
            "name": m["config"]["column"],
            "method": m["config"]["method"],
            "stat": float(m["value"]),
            "threshold": float(m["config"]["threshold"]),
        }
        for m in snapshot.dict()["metrics"]
        if m["config"]["type"].endswith("ValueDrift")
    ]
    return results, snapshot.get_html_str(as_iframe=False)


def analyse(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    numerical: list[str],
    categorical: list[str],
) -> DriftResult:
    """Dérive feature par feature et dérive du score, entre la référence et la fenêtre."""
    base: dict[str, Any] = {"n_reference": len(reference), "n_current": len(current)}
    if len(current) < MIN_CURRENT:
        return DriftResult(
            {
                **base,
                "insufficient": True,
                "share_drifted": None,
                "n_drifted": None,
                "score_drift": None,
                "features": [],
            },
            None,
        )
    current = current.reindex(columns=[*reference.columns])
    empty = [c for c in (*numerical, *categorical) if current[c].isna().all()]
    num = [c for c in numerical if c not in empty]
    cat = [c for c in categorical if c not in empty]
    # Catégorielles en texte des deux côtés : une valeur inconnue reste une catégorie.
    reference = reference.astype({c: "object" for c in cat})
    current = current.astype({c: "object" for c in cat})
    results, html = _run_report(reference, current, num, cat)
    for r in results:
        r["drifted"] = _decide(r["stat"], r["method"], r["threshold"])
    score = next(r for r in results if r["name"] == SCORE)
    features = [r for r in results if r["name"] != SCORE]
    features.sort(key=lambda r: r["stat"], reverse=True)
    features += [
        {"name": c, "method": EMPTY, "stat": None, "threshold": None, "drifted": None}
        for c in empty
    ]
    analysed = [f for f in features if f["drifted"] is not None]
    n_drifted = sum(1 for f in analysed if f["drifted"])
    return DriftResult(
        {
            **base,
            "insufficient": False,
            "share_drifted": n_drifted / len(analysed) if analysed else None,
            "n_drifted": n_drifted,
            "score_drift": score,
            "features": features,
        },
        html,
    )


def save(
    engine: sa.Engine,
    result: DriftResult,
    window_start: datetime,
    window_end: datetime,
    model_version: str | None,
    now: datetime | None = None,
) -> int:
    """Écrit le résumé dans `drift_reports` (lu par l'onglet Monitoring) ; renvoie l'id."""
    s = result.summary
    score = s["score_drift"] or {}
    row = {
        "created_at": now or datetime.now(UTC),
        "window_start": window_start,
        "window_end": window_end,
        "n_reference": s["n_reference"],
        "n_current": s["n_current"],
        "share_drifted": s["share_drifted"],
        "n_drifted": s["n_drifted"],
        "score_drift_stat": score.get("stat"),
        "score_drifted": score.get("drifted"),
        "insufficient": s["insufficient"],
        "model_version": model_version,
        "details": {"features": s["features"], "score_drift": s["score_drift"]},
    }
    with engine.begin() as conn:
        inserted = conn.execute(drift_reports.insert().values(**row))
        key = inserted.inserted_primary_key
    return int(key[0]) if key else 0
