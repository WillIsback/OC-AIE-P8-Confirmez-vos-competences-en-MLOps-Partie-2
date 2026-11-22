# Journalisation des données de production — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** chaque appel `/predict…` produit une ligne JSON sur stdout et une ligne
`prediction_logs` dans Neon, écrite en tâche de fond, sans jamais casser une prédiction ;
rétention 30 jours avec archivage quotidien ; simulation de trafic.

**Architecture:** paquet `credit_scoring.monitoring` (schéma SQLAlchemy Core, écrivain en
tâche de fond, middleware ASGI) branché dans le lifespan de `api/app.py` ; migrations Alembic
lancées par le job `deploy` ; scripts `archive_logs.py` et `simulate_traffic.py`.

**Tech Stack:** SQLAlchemy 2, psycopg 3 (binaire), Alembic, pyarrow (groupe `archive`),
GitHub Actions (service Postgres, cron).

**Spec:** `docs/superpowers/specs/2026-11-22-journalisation-production-design.md`
(W1–W7, A1–A5).

## Global Constraints

- Issue #16, sous-branche `feat/0.3.0-logs-stockage` ; commits en français, `Refs #16`.
- Une panne de base, une file pleine ou un `DATABASE_URL` absent ne changent **jamais** la
  réponse d'une prédiction.
- `SK_ID_CURR` jamais stocké en clair : `client_ref = hmac_sha256(key=b"client_ref:" + API_KEY, msg=str(id))`.
- Aucune valeur de `DATABASE_URL` dans un log, un message d'erreur ou un commit (masquer
  l'URL dans les exceptions remontées).
- Valeurs de `source` : `api` (défaut), `ui-demo`, `ci` ; tout autre en-tête `X-Client` → `api`.
- Tests unitaires sans réseau ; couverture 100 % lignes + branches sur `src/`.
- Ne pas toucher à `prediction_logs` réel depuis un test (schéma temporaire pour l'intégration).

## Review Focus

1. Corps de requête énorme ou non JSON sur `/predict` → 422 normal, trace tronquée à 64 Kio
   avec marqueur, aucune exception dans le middleware.
2. Exception non gérée dans la route (500) → une ligne `error_type="internal"` est quand même
   journalisée et l'exception remonte.
3. Arrêt du serveur avec des lignes en file → vidées avant la fin du lifespan (borne de temps).
4. Base qui répond lentement (réveil après autosuspend) → latence de `/predict` inchangée.
5. Archivage dont l'envoi au Hub échoue → aucune ligne supprimée.

---

### Task 1: Schéma, connexion et migrations

**Files:** Create `src/credit_scoring/monitoring/__init__.py`, `monitoring/schema.py`,
`monitoring/db.py`, `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_prediction_logs.py` ;
Modify `pyproject.toml`, `uv.lock` ; Test `tests/test_monitoring_schema.py`.

**Interfaces:**
- Produces: `metadata`, `prediction_logs: sqlalchemy.Table` (colonnes de la spec §4 ;
  `features`, `warnings`, `error_detail` en `JSON().with_variant(JSONB(), "postgresql")` ;
  `created_at` `DateTime(timezone=True)` ; index `created_at`, `source`) ;
  `def make_engine(url: str) -> Engine` (`postgresql://` réécrit en `postgresql+psycopg://`,
  `connect_args={"prepare_threshold": None}` pour Postgres, `pool_pre_ping=True`) ;
  `def database_url() -> str | None` (env `DATABASE_URL`, vide → `None`).
- [ ] Step 1: `uv add sqlalchemy "psycopg[binary]" alembic` ; `uv add --group archive pyarrow`.
- [ ] Step 2: tests en échec : `alembic upgrade head` (API `alembic.command`) sur une SQLite
  temporaire crée `prediction_logs` avec toutes les colonnes de `schema.prediction_logs` ;
  `downgrade base` la supprime ; `make_engine` réécrit le schéma d'URL ; `database_url()` vide
  → `None`. Même test sur Postgres si `TEST_DATABASE_URL` (marqueur `postgres`, ajouté à
  `pyproject.toml`). Run `uv run pytest tests/test_monitoring_schema.py -q --no-cov` → FAIL.
- [ ] Step 3: implémenter (migration écrite à la main, `env.py` lit `DATABASE_URL` ou
  `-x url=`). → PASS. Commit `feat(monitoring): schéma prediction_logs et migrations`.

### Task 2: Écrivain en tâche de fond

**Files:** Create `monitoring/writer.py` ; Test `tests/test_monitoring_writer.py`.

**Interfaces:**
- Produces: `class ProductionLogWriter` : `__init__(self, engine: Engine | None, maxsize: int = 10_000, batch: int = 100)`,
  `start()`, `submit(record: dict) -> None` (jamais bloquant, jamais d'exception),
  `stop(timeout: float = 5.0)` (vide la file), propriétés `dropped: int`, `database: bool` ;
  chaque `submit` écrit aussi `json.dumps(record, default=str)` sur le logger
  `credit_scoring.production` (une ligne).
- [ ] Step 1: tests en échec : lignes insérées après `stop()` (SQLite) ; engine `None` → stdout
  seulement, `database is False` ; base en erreur (engine sur un fichier en lecture seule ou
  faux engine qui lève) → `dropped` incrémenté, pas d'exception ; file pleine (`maxsize=1`,
  thread non démarré) → `dropped` ; message d'erreur journalisé sans l'URL. → FAIL.
- [ ] Step 2: implémenter (thread daemon, `queue.Queue`, insertion par lots en une
  transaction). → PASS. Commit `feat(monitoring): écriture des journaux en tâche de fond`.

### Task 3: Middleware et branchement dans l'API

**Files:** Create `monitoring/middleware.py`, `monitoring/record.py` ; Modify
`src/credit_scoring/api/app.py` (lifespan, routes, `/health`), `api/scoring.py` (`inference_ms`) ;
Test `tests/test_monitoring_api.py` ; Modify `tests/test_api_health.py`.

**Interfaces:**
- Consumes: `ProductionLogWriter`, `make_engine`, `database_url`.
- Produces: `class PredictionLogMiddleware` (ASGI, chemins `/predict` et `/predict/{id}`,
  méthode POST) : bufferise le corps, `request_id` uuid4 (en-tête `X-Request-ID`), latence,
  statut ; lit `scope["state"]` (`features`, `prediction`, `inference_ms`, `client_ref`) ;
  construit l'enregistrement par `record.build(...) -> dict` ; `app.state.log_writer.submit`.
  `score()` renvoie le temps d'inférence via un nouvel argument de sortie
  (`score(model, client, sk_id_curr=None, timings: dict | None = None)`).
  `error_type` : 401 `unauthorized`, 404 `not_found`, 422 `validation`, ≥ 500 `internal`.
  `/health` → `{"status","version","logging":{"database": bool,"dropped": int}}`.
- [ ] Step 1: tests en échec (fixture `client` de `test_api_predict.py`, `DATABASE_URL` =
  SQLite temporaire migrée, lecture de la table après `stop()`) : 200 `POST /predict` (122
  features, score, `inference_ms > 0`, `source="api"`, `client_ref` nul) ; 200 démo
  (`client_ref` = HMAC attendu, jamais l'id brut dans la ligne) ; `X-Client: ui-demo` et `ci` ;
  `X-Client: autre` → `api` ; 401 (pas de `features`) ; 404 ; 422 (`error_detail`, corps
  reçu) ; corps non JSON et corps > 64 Kio (marqueur, troncature) ; 500 forcé (monkeypatch de
  `score`) → ligne `internal` ; `/health` et `/docs` non journalisés ; base en panne →
  prédiction 200, `dropped` dans `/health`. → FAIL.
- [ ] Step 2: implémenter ; writer démarré dans le lifespan et arrêté à sa sortie.
- [ ] Step 3: suite complète + ruff + mypy → PASS, couverture 100 %.
  Commit `feat(monitoring): journalisation de chaque appel de scoring`.

### Task 4: Déploiement, CI et intégration Neon

**Files:** Modify `.github/workflows/ci-test.yml` (service `postgres:17`, `TEST_DATABASE_URL`),
`.github/workflows/release.yml` (job `deploy` : `DATABASE_URL`, étape `uv run alembic upgrade head`
avant le déploiement), `scripts/deploy_space.py` (secret Space `DATABASE_URL`, test de fumée
avec `X-Client: ci`), `tests/test_deploy_space.py` ; Create `tests/test_monitoring_integration.py`.

- [ ] Step 1: tests en échec : `deploy` pousse `DATABASE_URL` parmi les secrets ; `smoke`
  envoie `X-Client: ci`. Test `integration` : sur `DATABASE_URL`, schéma temporaire
  `ci_<uuid>` (`search_path`), migration, insertion via le writer, relecture, `DROP SCHEMA … CASCADE`.
- [ ] Step 2: implémenter ; `actionlint` et `uvx zizmor --min-severity high .github/workflows`.
- [ ] Step 3: exécuter le test d'intégration en local contre Neon (`.env.local`) → PASS.
  Commit `ci(monitoring): migrations au déploiement et Postgres en CI`.

### Task 5: Archivage quotidien

**Files:** Create `scripts/archive_logs.py`, `.github/workflows/archive-logs.yml` ;
Test `tests/test_archive_logs.py`.

**Interfaces:** `parse_age("30d"|"12h"|"1h") -> timedelta` ;
`archive(engine, api, repo_id, older_than: timedelta, now: datetime, dry_run=False) -> int`
(lignes sélectionnées → Parquet en mémoire → `api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)`
→ `upload_file` `archive/AAAA-MM-JJTHHMM.parquet` → `DELETE` des mêmes `id` ; renvoie le nombre).
Workflow : `schedule: "0 3 * * *"` + `workflow_dispatch` (`older_than`, défaut `30d`), env
`ml-models`, `uv sync --group archive`.
- [ ] Step 1: tests en échec (SQLite, faux `api`) : seules les lignes plus anciennes partent ;
  envoi en échec → aucune suppression ; dry-run → ni envoi ni suppression ; rien à archiver →
  aucun envoi ; `parse_age` invalide → erreur. → FAIL.
- [ ] Step 2: implémenter → PASS ; actionlint/zizmor. Commit `feat(monitoring): archivage quotidien des journaux expirés`.

### Task 6: Simulation de trafic et documentation

**Files:** Create `scripts/simulate_traffic.py`, `docs/monitoring.md` ; Modify `docs/spec.md`
(ADR-004, ADR-005), `docs/api.md`, `docs/cicd.md`, `.env.example` (`DATABASE_URL=`) ;
Test `tests/test_simulate_traffic.py`.

**Interfaces:** `load_clients(db: Path, n: int, seed: int) -> list[dict]` (122 features de
`clients.db` de P6, NaN → `None`) ; `plan_requests(clients, invalid_share, unauthorized_share, rng) -> list[Request]`
(`Request(path, body, headers, expected_status)`) ; `main` envoie à `--url` au débit `--rate`
et affiche le décompte par statut.
- [ ] Step 1: tests en échec (base SQLite factice de 3 clients) : chargement, parts
  invalides et sans clé respectées, invalide = règle métier violée (422 attendu). → FAIL.
- [ ] Step 2: implémenter → PASS.
- [ ] Step 3: docs (stratégie de la spec §9, requêtes SQL d'exemple : volume par source,
  taux d'erreur, latence p95 par heure, distribution des scores).
- [ ] Step 4: commit `feat(monitoring): simulation de trafic et stratégie de stockage`.
- [ ] Step 5 (après release) : simulation contre le Space, vérification dans Neon ; 👤 captures.
