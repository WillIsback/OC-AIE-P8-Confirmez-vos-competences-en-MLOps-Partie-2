# Analyse du drift et dashboard — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** analyse de dérive Evidently reproductible (module, job planifié, notebook) et onglet
« Monitoring » du Space alimenté par Neon.

**Architecture:** `monitoring/metrics.py` (pandas, racine) et `monitoring/drift.py`
(Evidently, sous-projet `analysis/` en pandas 2.3) ; le job écrit `drift_reports` ; l'onglet
Gradio lit `prediction_logs` et le dernier `drift_reports`.

**Tech Stack:** Evidently 0.7.23, pandas 2.3 (analysis) / 3.1 (racine), SQLAlchemy, Alembic,
Gradio 6.32 (`gr.BarPlot`, `gr.LinePlot`), GitHub Actions, huggingface_hub.

**Spec:** `docs/superpowers/specs/2026-11-23-drift-dashboard-design.md`

## Global Constraints

- #17 sur `feat/0.4.0-analyse-drift` (tâches 1 à 4), #18 sur `feat/0.4.0-dashboard`
  (tâches 5 et 6, depuis `feat/0.4.0` après la fusion de #17) ; `Refs #N` ; commits en français.
- Evidently jamais dans l'environnement racine ni dans l'image ; `metrics.py` et `drift.py`
  compatibles pandas 2 et 3.
- Données Kaggle : jamais versionnées ; la référence va dans le dataset HF **privé**
  `WillIsback/credit-scoring-drift-reference` ; notebook versionné avec agrégats seulement.
- Analyses de production : `source = 'api'` par défaut, `status_code = 200` pour la dérive.
- Tests sans réseau ; couverture 100 % à la racine ; ruff, mypy ; codes de retour vérifiés.

## Review Focus

1. Fenêtre vide ou < 200 appels : rapport « insuffisant », onglet sans erreur (pas de NaN affiché).
2. `features` JSON avec `null` et catégories inconnues : la dérive se calcule sans planter.
3. Base absente ou injoignable : l'onglet affiche un message, l'interface de scoring reste utilisable.
4. Le score `prob_default` de référence est calculé par le même modèle que la production.
5. Aucune ligne client dans le notebook versionné, les rapports publiés ou les journaux du job.

---

### Task 1: Table `drift_reports`, seuils et indicateurs opérationnels

**Files:** Create `src/credit_scoring/monitoring/migrations/versions/0002_drift_reports.py`,
`monitoring/metrics.py`, `monitoring/thresholds.py` ; Modify `monitoring/schema.py` ;
Test `tests/test_monitoring_metrics.py`.

**Interfaces (produits) :**
- `schema.drift_reports` (colonnes du spec) ; migration `0002` (down_revision `0001`).
- `thresholds.THRESHOLDS: dict[str, float]` : `drift_share_alert`, `score_drift_alert`,
  `error_rate_alert`, `latency_p95_ms_alert` (valeurs de départ commentées « à fixer par William »).
- `metrics.load_logs(engine, window: timedelta, source: str | None = "api", now=None) -> pd.DataFrame`
- `metrics.summary(logs) -> dict[str, float | int | None]` : `n`, `acceptance_rate`,
  `error_rate`, `latency_p50`, `latency_p95`, `inference_p50`, `inference_p95` (None si vide).
- `metrics.score_histogram(logs, bins=20) -> pd.DataFrame` (`bin`, `count`) ;
  `metrics.hourly(logs) -> pd.DataFrame` (`hour`, `n`, `latency_p95`) ;
  `metrics.errors_by_type(logs) -> pd.DataFrame` (`error_type`, `count`).
- `metrics.latest_drift(engine) -> dict | None`.

- [ ] Step 1 : tests en échec sur SQLite migré (lignes insérées à la main) : fenêtre et source filtrées ; quantiles exacts sur un jeu connu ; vide → `n=0` et `None` partout ; histogramme (bornes 0–1) ; erreurs groupées ; `latest_drift` renvoie la plus récente, `None` sans ligne ; migration 0002 appliquée (upgrade puis downgrade). Run → FAIL.
- [ ] Step 2 : implémenter → PASS ; suite complète, ruff, mypy.
- [ ] Step 3 : commit `feat(monitoring): table drift_reports et indicateurs opérationnels`.

### Task 2: Sous-projet `analysis/` et module de dérive

**Files:** Create `analysis/pyproject.toml`, `analysis/uv.lock`, `src/credit_scoring/monitoring/drift.py`,
`tests/drift/test_drift.py` ; Modify `pyproject.toml` (`pandas>=2.2`, marqueur `drift`,
`--ignore=tests/drift` par défaut, omission de `drift.py` dans la couverture racine),
`.github/workflows/ci-test.yml` (job `ci-test-drift`, filtré sur `monitoring/**`, `analysis/**`, `tests/drift/**`).

**Interfaces :**
- `drift.production_frame(engine, window, now=None) -> pd.DataFrame` : 122 features + `prob_default`, appels 200 `source='api'`.
- `drift.analyse(reference, current, model_columns, categorical) -> DriftResult` (dataclass : `summary: dict`, `html: str`) ; `summary` = `n_reference`, `n_current`, `share_drifted`, `n_drifted`, `score_drift` (`stat`, `drifted`), `features` (liste `name`, `method`, `stat`, `threshold`, `drifted`), `insufficient: bool` (`n_current < MIN_CURRENT = 200`).
- `drift.save(engine, result, window_start, window_end, model_version) -> int`.

- [ ] Step 1 : tests en échec (`uv run --project analysis pytest tests/drift`) : dérive détectée sur colonne décalée, absente sur colonne identique ; catégorie inconnue et `null` tolérés ; `insufficient` sous 200 lignes (sans appel Evidently) ; `save` puis `metrics.latest_drift` relit le résumé. Run → FAIL.
- [ ] Step 2 : implémenter → PASS ; racine toujours verte à 100 % ; ruff, mypy.
- [ ] Step 3 : commit `feat(monitoring): module de dérive Evidently (sous-projet analysis)`.

### Task 3: Référence, job planifié

**Files:** Create `scripts/export_drift_reference.py`, `scripts/drift_job.py`,
`.github/workflows/drift-analysis.yml` ; Tests `tests/drift/test_drift_job.py`.

- `export_drift_reference.sample(train_csv, n=20_000, seed=42) -> pd.DataFrame` (stratifié sur `TARGET`, `TARGET` retirée, `prob_default` ajouté via `load_model`) ; `main` envoie le Parquet au dataset privé (`create_repo(private=True, exist_ok=True)`).
- `drift_job.run(engine, reference, model, window=7 j, now=None) -> DriftResult` ; `main` télécharge la référence (`HF_TOKEN`), écrit `drift_reports`, écrit `drift-report.html`.
- Workflow : cron quotidien 04:00 UTC + `workflow_dispatch` (fenêtre en entrée), environnement `ml-models`, `uv run --project analysis`, rapport en artefact (rétention 30 j), actions épinglées par SHA, `timeout-minutes`.

- [ ] Step 1 : tests en échec (stratification et colonnes ; `prob_default` égal à `model.predict` ; job sur SQLite avec trafic synthétique : une ligne `drift_reports`) ; HF simulé. Run → FAIL.
- [ ] Step 2 : implémenter → PASS ; actionlint + shellcheck, `uvx zizmor --min-severity high`.
- [ ] Step 3 : exécuter l'export réel (P6 local → dataset privé) ; vérifier la confidentialité du dataset.
- [ ] Step 4 : commit `feat(monitoring): référence de dérive et analyse planifiée`.

### Task 4: Notebook

**Files:** Create `notebooks/analyse_drift.ipynb`, `notebooks/README.md`.

- Sections : sources (référence HF, Neon) ; rapport Evidently ; distributions comparées (top 5 importance, `bureau_balance`, `CODE_GENDER`, `prob_default`) ; anomalies opérationnelles (`metrics`) ; **Interprétation (👤 William)** et **Seuils et action (👤 William)** laissées vides avec consignes.
- [ ] Step 1 : exécution de bout en bout (`uv run --project analysis jupyter nbconvert --execute`) sur une base locale alimentée par `simulate_traffic.py` contre l'app locale ; vérifier l'absence de ligne client dans les sorties.
- [ ] Step 2 : commit `feat(monitoring): notebook d'analyse du drift`.

### Task 5: Onglet « Monitoring » (#18)

**Files:** Create `src/credit_scoring/ui/monitoring.py` ; Modify `ui/app.py` (`gr.Tabs` : « Scoring », « Monitoring ») ;
Test `tests/test_ui_monitoring.py`.

- `on_refresh(engine | None, window_label, source_label) -> tuple` : tuiles (HTML), histogramme, série horaire, erreurs, bloc dérive (HTML, alerte vs `THRESHOLDS`) ; sans base → message ; exception de base → message, jamais levée.
- [ ] Step 1 : tests en échec (SQLite peuplé ; vide ; base absente ; base cassée ; alerte au-dessus du seuil ; échappement). Run → FAIL.
- [ ] Step 2 : implémenter → PASS ; suite, ruff, mypy.
- [ ] Step 3 : recette Playwright sur l'app locale (base locale peuplée, une ligne `drift_reports` du job) ; capture `docs/ui/img/05-monitoring.png`.
- [ ] Step 4 : commit `feat(ui): onglet de monitoring (scores, latence, erreurs, dérive)`.

### Task 6: Documentation

- `docs/monitoring.md` (dérive : référence, tests par défaut, fenêtre, seuils ; dashboard : indicateurs et lecture), `README.md` (lancer l'analyse et le dashboard), `docs/cicd.md` (workflow `drift-analysis`, job `ci-test-drift`), `docs/spec.md` (ADR-005 : révision du 23/11 — sous-projet `analysis/`, connexion unique au lieu de `DATABASE_URL_RO`).
- [ ] Step 1 : rédiger ; commit `docs: analyse du drift et dashboard de monitoring`.
