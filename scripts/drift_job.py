"""Analyse de dérive planifiée (#17) : référence HF + fenêtre de production → drift_reports.

    uv run --project analysis python scripts/drift_job.py [--window 7d] [--out drift-report.html]

Compare les appels réussis de production (`source = 'api'`) de la fenêtre à l'échantillon
de référence (dataset privé), écrit le résumé dans `drift_reports` (lu par l'onglet
Monitoring) et le rapport Evidently complet en HTML (artefact du run). N'affiche que des
agrégats, jamais de ligne client. Variables : `DATABASE_URL`, `HF_TOKEN` (lecture).
Tourne dans le sous-projet analysis/ (Evidently exige pandas < 3).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from credit_scoring.model import ScoringModel  # noqa: E402
from credit_scoring.monitoring import drift  # noqa: E402
from scripts.archive_logs import parse_age  # noqa: E402
from scripts.export_drift_reference import REFERENCE_FILE, REPO_ID  # noqa: E402


def run(
    engine: sa.Engine,
    reference: pd.DataFrame,
    model: ScoringModel,
    window: timedelta,
    now: datetime | None = None,
) -> drift.DriftResult:
    """Analyse la fenêtre `[now - window, now]` et enregistre le résumé."""
    end = now or datetime.now(UTC)
    categorical = list(model.features.categories)
    numerical = [c for c in model.features.input_features if c not in categorical]
    # Score de référence recalculé par le modèle servi : une référence exportée avec un
    # ancien modèle ne crée ni ne masque de dérive du score.
    features = reference[list(model.features.input_features)]
    reference = reference.assign(prob_default=model.predict(features)["prob_default"].to_numpy())
    current = drift.production_frame(engine, window, now=end)
    result = drift.analyse(reference, current, numerical, categorical)
    drift.save(engine, result, end - window, end, model.version, now=end)
    return result


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - réseau et base réels
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--window", default="7d", help="fenêtre analysée (ex. 7d, 24h)")
    parser.add_argument("--out", type=Path, default=Path("drift-report.html"))
    args = parser.parse_args(argv)
    from huggingface_hub import hf_hub_download

    from credit_scoring.hub import ensure_artifacts
    from credit_scoring.model import load_model, model_dir
    from credit_scoring.monitoring.db import database_url, make_engine

    url = database_url()
    if not url:
        raise SystemExit("DATABASE_URL absente : aucune base à analyser")
    ensure_artifacts(model_dir())
    model = load_model(model_dir())
    path = hf_hub_download(REPO_ID, REFERENCE_FILE, repo_type="dataset")
    reference = pd.read_parquet(path)
    engine = make_engine(url)
    try:
        result = run(engine, reference, model, parse_age(args.window))
    finally:
        engine.dispose()
    s = result.summary
    if s["insufficient"]:
        print(f"Échantillon insuffisant : {s['n_current']} appels (minimum {drift.MIN_CURRENT}).")
        return 0
    args.out.write_text(result.html or "", encoding="utf-8")
    score = s["score_drift"]
    print(
        f"{s['n_current']} appels contre {s['n_reference']} de référence : "
        f"{s['n_drifted']} features en dérive ({s['share_drifted']:.1%}) ; "
        f"score : {score['stat']:.3f} ({'dérive' if score['drifted'] else 'stable'})."
    )
    for f in [f for f in s["features"] if f["drifted"]][:10]:
        print(f"  {f['name']} : {f['method']} = {f['stat']:.3f}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
