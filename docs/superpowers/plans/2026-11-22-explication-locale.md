# Explication locale du score — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** route `POST /predict/explain` (contributions SHAP exactes) et graphique d'explication
avec badge « critère protégé (non-discrimination) » dans l'interface.

**Architecture:** `ScoringModel.contributions()` (TreeSHAP natif) → `scoring.explain()` →
route FastAPI ; l'interface passe de `/predict` à `/predict/explain` et rend un graphique HTML.

**Tech Stack:** LightGBM 4.7 (`pred_contrib`), FastAPI, Pydantic, Gradio 6.32.

**Spec:** `docs/superpowers/specs/2026-11-22-explication-locale-design.md`

## Global Constraints

- Issue #44, sous-branche `feat/0.4.0-explication`, `Refs #44`, commits en français.
- Contrat de `/predict` et `/predict/{sk_id_curr}` inchangé.
- `/predict/explain` déclarée avant `/predict/{sk_id_curr}` ; même clé, même validation (`ClientFeatures`).
- Tests sans réseau ; couverture 100 % ; ruff, mypy ; codes de retour vérifiés (pas de `| tail`).

## Review Focus

1. Ordre des routes : `POST /predict/explain` ne doit jamais tomber sur la route de démo (422 « int »).
2. Journalisation : une ligne `path="/predict/explain"`, jamais classée `/predict/{sk_id_curr}`.
3. Somme `base_value + Σ contributions` = logit du score à 1e-6 près, y compris avec des `null`.
4. Catégorie inconnue / valeurs nulles : contribution calculée, valeur affichée vide sans erreur.
5. Badge et mention « combinaison calculée » échappés en HTML (noms et valeurs issus de la requête).

---

### Task 1: Contributions, politique et route

**Files:** Modify `src/credit_scoring/model.py`, `src/credit_scoring/api/schemas.py`,
`src/credit_scoring/api/scoring.py`, `src/credit_scoring/api/app.py`,
`src/credit_scoring/monitoring/middleware.py` ; Create `src/credit_scoring/api/fairness.py` ;
Test `tests/test_explain.py`.

**Interfaces:**
- `ScoringModel.contributions(frame: pd.DataFrame) -> tuple[float, np.ndarray]` : (base, contributions dans l'ordre de `features.model_columns`), une seule ligne.
- `fairness.SENSITIVE_FEATURES: dict[str, str]` (nom → justification).
- Schémas : `Contribution(feature, value: float | str | None, contribution: float, sensitive: bool, derived: bool)`, `Explanation(base_value: float, top: list[Contribution], others: float)`, `ExplainResponse(PredictionResponse)` + `explanation: Explanation`.
- `scoring.explain(model, client, top_n=10, timings=None) -> ExplainResponse`.
- Route `POST /predict/explain` (journalisée via `_scored`-équivalent : features, prédiction, `inference_ms` = score + contributions).
- `middleware.logged_path` : `/predict/explain` → `"/predict/explain"`.

- [ ] Step 1 : tests en échec (fixture `api_artifacts`) : somme base + contributions = logit(prob) à 1e-6 ; `top` de 10 triés par |contribution| décroissante ; `others` = somme du reste ; `CODE_GENDER` `sensitive`, `autoFE_*` `derived` (si présentes dans le modèle synthétique, sinon test unitaire sur `explain` avec noms factices) ; 401 sans clé ; 422 foyer 0 ; client avec `null` ; route non capturée par `/predict/{sk_id_curr}` ; ligne journalisée `path="/predict/explain"` ; chaque clé de `SENSITIVE_FEATURES` ∈ `features.json` réel (`artifacts/` si présent, sinon modèle synthétique). Run → FAIL.
- [ ] Step 2 : implémenter → PASS ; suite complète, ruff, mypy.
- [ ] Step 3 : vérification sur les vrais artefacts (client 100038 : CODE_GENDER en tête, somme exacte).
- [ ] Step 4 : commit `feat(api): explication locale du score (contributions SHAP)`.

### Task 2: Graphique dans l'interface

**Files:** Modify `src/credit_scoring/ui/client.py` (`explain(features)`), `ui/view.py`
(`explanation_html(explanation) -> str`), `ui/app.py` (sélection et modification via
`/predict/explain`, composant `gr.HTML` du graphique) ; Tests `tests/test_ui_*.py`.

- [ ] Step 1 : tests en échec : `ApiClient.explain` appelle `/predict/explain` avec clé et `X-Client: ui-demo` ; `explanation_html` : une barre par contribution, classe `push-refus` / `push-accord`, badge « critère protégé (non-discrimination) » avec info-bulle sur `CODE_GENDER`, mention « combinaison calculée » sur `autoFE_*`, ligne « autres features », valeurs échappées ; `on_select` / `on_score` renvoient le graphique ; erreur → graphique vide. Run → FAIL.
- [ ] Step 2 : implémenter → PASS ; suite, ruff, mypy.
- [ ] Step 3 : recette navigateur (Playwright) sur l'app locale : client 100038 (badge visible), client accordé ; captures `docs/ui/img/04-explication.png`.
- [ ] Step 4 : commit `feat(ui): graphique d'explication et badge de critère protégé`.

### Task 3: Documentation

**Files:** `docs/api.md` (route, unité log-odds, lecture), `docs/ui/README.md` (graphique, badge,
65 % opaque), `docs/spec.md` (ADR-007 explicabilité et équité : décisions de William, limites,
pistes : réentraînement sans `CODE_GENDER`, audit des proxies OpenFE).

- [ ] Step 1 : rédiger ; commit `docs: explication locale, équité et limites (ADR-007)`.
