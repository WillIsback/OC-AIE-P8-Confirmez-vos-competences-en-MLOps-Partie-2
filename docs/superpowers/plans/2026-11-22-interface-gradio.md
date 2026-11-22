# Interface Gradio de démonstration — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** servir à la racine du Space une interface Gradio qui score les clients de démo en
appelant la vraie route `/predict` (clé côté serveur, en-tête `X-Client: ui-demo`).

**Architecture:** paquet `credit_scoring.ui` (client HTTP interne via `httpx.ASGITransport`,
formatage pur, `gr.Blocks`) monté par `gr.mount_gradio_app(app, demo, path="/")` à la fin de
`api/app.py` quand Gradio est installé ; sinon la page HTML actuelle reste à `/`.

**Tech Stack:** FastAPI 0.165, Gradio 6.32.0 (extra `ui`), httpx (ASGITransport), pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-interface-gradio-design.md` (décisions D1–D8).

## Global Constraints

- Issue #40, lot v0.3.0, sous-branche `feat/0.3.0-interface-gradio` ; commits Conventional
  Commits en français ; `Refs #40` dans chaque commit.
- **#16 (journalisation) est exécutée avant ce plan** ; ce plan n'en dépend pas
  techniquement (il envoie seulement l'en-tête `X-Client: ui-demo`).
- `gradio==6.32.0` exactement (= `sdk_version` du Space) ; `pydantic>=2.12,<2.13` inchangé.
- Gradio jamais importé par `credit_scoring.api` au niveau module ; appel par attribut
  `gr.mount_gradio_app(...)` (le paquet `spaces` remplace cet attribut sur ZeroGPU).
- La clé d'API ne quitte jamais le serveur (ni composant, ni état Gradio, ni log).
- Tous les événements Gradio : `api_visibility="private"` ; `launch`/mount sans historique
  (`run_history=False` si l'option existe au montage, sinon ledger une Ruling).
- Tests unitaires sans réseau ; couverture lignes + branches à 100 % sur `src/`.
- `pyproject.toml` et `uv.lock` portent une modification locale de William non commitée
  (`debugpy` dans `dev`) : **ne pas la commiter sans son accord** (le demander avant le
  premier commit qui touche ces fichiers).
- Textes de l'interface en français ; nombres au format français (`61,2 %`, `514 777,5`).

## Review Focus

1. Le montage de Gradio à `/` casse le lifespan (modèle non chargé) → `/predict` doit
   toujours répondre 200 avec Gradio monté (test dans la tâche 4).
2. Un client de démo invalide (`DEMO_INVALID_ID`) ou avec des `null` (`DEMO_NULLABLE_ID`)
   sélectionné dans l'interface → 422 affiché en clair, valeurs `null` affichées vides et
   renvoyées `null` (tests tâche 3).
3. API qui renvoie un statut inattendu (500) ou lève une exception de transport → bandeau
   « API indisponible », pas de trace Python à l'écran (test tâche 3).
4. Startup report ZeroGPU envoyé deux fois (middleware explicite + middleware ajouté par
   `spaces` au montage) → l'`app.py` du Space n'enveloppe plus l'app (tâche 5, simulation).
5. Saisie vide dans un champ numérique (Gradio renvoie `None`) pour une feature non
   nullable → l'API répond 422 et l'interface l'affiche (test tâche 3).

---

### Task 1: Dépendance `ui` et client HTTP interne

**Files:**
- Modify: `pyproject.toml` (extra `ui`, groupe `dev`), `uv.lock`
- Create: `src/credit_scoring/ui/client.py`
- Test: `tests/test_ui_client.py`

**Interfaces:**
- Produces: `class ApiError(Exception)` avec `status: int` et `details: list[dict] | str` ;
  `class ApiClient` : `__init__(self, http: httpx.AsyncClient, api_key: str)`,
  `async predict_demo(self, sk_id_curr: int) -> dict`,
  `async predict(self, features: dict[str, Any]) -> dict` ;
  `def internal_client(app: FastAPI) -> ApiClient` (ASGITransport,
  `base_url="http://ui.internal"`, clé lue dans `app.state.api_key` à l'appel).
- Constante `CLIENT_HEADER = {"X-Client": "ui-demo"}`.

- [ ] **Step 1:** `uv add --optional ui gradio==6.32.0 httpx` puis `uv add --dev gradio==6.32.0`
  (sans toucher aux autres lignes ; vérifier `git diff pyproject.toml`).
  Expected: résolution OK, pydantic reste en 2.12.x.
- [ ] **Step 2: tests en échec** — `tests/test_ui_client.py`, sur l'app réelle avec la fixture
  `api_artifacts` (même fixture `client` que `tests/test_api_predict.py`, l'`ApiClient`
  construit par `internal_client(app)` dans le `with TestClient(app)` pour que le lifespan
  ait tourné ; tests `async` via `anyio` ou `asyncio.run`) :
  - `test_client_demo_valide` : `predict_demo(DEMO_VALID_ID)` → `decision in {"accordé","refusé"}`.
  - `test_client_inconnu_404` : `predict_demo(999)` → `ApiError`, `status == 404`.
  - `test_regle_violee_422_restituee` : `predict({**EXAMPLE_CLIENT, "CNT_FAM_MEMBERS": 0})`
    → `ApiError.status == 422`, `details[0]["loc"][-1] == "CNT_FAM_MEMBERS"`.
  - `test_hors_bornes_avertissement` : `AMT_CREDIT=5_000_000.0` → 200, un warning sur `AMT_CREDIT`.
  - `test_cle_et_source_envoyees` : `httpx.MockTransport` qui capture la requête →
    en-têtes `X-API-Key` = clé fournie et `X-Client` = `ui-demo`.
  - `test_statut_inattendu` : `MockTransport` renvoyant 500 texte brut → `ApiError(500, str)`.
  Run: `uv run pytest tests/test_ui_client.py -q --no-cov` → Expected: FAIL (module absent).
- [ ] **Step 3:** implémenter `client.py` ; 422 → `details = response.json()["detail"]` ;
  autre statut ≠ 200 → `details` = `detail` JSON s'il existe, sinon le texte.
- [ ] **Step 4:** même commande → PASS.
- [ ] **Step 5:** commit `feat(ui): client HTTP interne de l'API pour l'interface`.

### Task 2: Formatage (`view.py`)

**Files:** Create `src/credit_scoring/ui/view.py` ; Test `tests/test_ui_view.py`

**Interfaces:**
- Produces: `fmt_number(x: float | int | None) -> str` (`514777.5` → `"514 777,5"`,
  `None` → `""`, espace insécable fine U+202F comme séparateur de milliers) ;
  `fmt_percent(p: float) -> str` (`0.6123` → `"61,2 %"`) ;
  `result_html(prediction: dict) -> str` (décision en majuscules, classe CSS
  `decision-accorde` / `decision-refuse`, barre de probabilité avec repère du seuil, texte
  `Probabilité de défaut : 61,2 % — seuil 53,5 %`) ;
  `warnings_rows(prediction: dict) -> list[list[str]]` (colonnes : feature, valeur,
  min–max, rang `3/122`, part `3,1 %`) ;
  `errors_markdown(err: ApiError) -> str` (422 : une puce par erreur
  `**CNT_FAM_MEMBERS** : <msg> (reçu : 0)` avec le dernier élément de `loc` ; sinon
  `⚠️ API indisponible (statut 500)`).

- [ ] **Step 1: tests en échec** couvrant chaque exemple ci-dessus, un warning sans
  `importance_rank`, une erreur 422 sans `input`.
  Run: `uv run pytest tests/test_ui_view.py -q --no-cov` → FAIL.
- [ ] **Step 2:** implémenter (fonctions pures, aucun import de Gradio).
- [ ] **Step 3:** → PASS ; commit `feat(ui): formatage du score, des avertissements et des erreurs`.

### Task 3: Écran et gestionnaires (`ui/app.py`)

**Files:** Create `src/credit_scoring/ui/app.py` ; Test `tests/test_ui_app.py`

**Interfaces:**
- Consumes: `ApiClient`, `ApiError` (tâche 1) ; fonctions de `view` (tâche 2).
- Produces:
  - `EDITABLE: tuple[Field, ...]` — `Field(name: str, label: str, kind: Literal["float","int","choice"])`,
    au moins `AMT_CREDIT` (« Montant du crédit », float), `CNT_FAM_MEMBERS` (« Membres du
    foyer », int), `HOUR_APPR_PROCESS_START` (« Heure de la demande », int),
    `OCCUPATION_TYPE` (« Profession », choice, choix lus dans l'annotation `Literal` de
    `GeneratedFeatures`), `FLAG_EMAIL` (« E-mail fourni », int), `OWN_CAR_AGE`
    (« Âge du véhicule », float) ; 5 à 8 champs au total.
  - `async on_select(client, clients, sk_id_curr) -> tuple` : valeurs des champs (une par
    `EDITABLE`), `result_html`, lignes d'avertissements, markdown d'erreur ; score via
    `predict_demo`.
  - `async on_score(client, clients, sk_id_curr, *values) -> tuple` : client complet =
    `clients[sk_id_curr]` + champs modifiés, score via `predict`.
  - `def on_reset(clients, sk_id_curr) -> tuple` : valeurs d'origine.
  - `def random_id(clients, rng: random.Random) -> int`.
  - `def build_ui(client_factory: Callable[[], ApiClient], clients_provider: Callable[[], dict[int, dict]]) -> gr.Blocks`.
  - Sortie d'erreur : `ApiError` → `errors_markdown` ; toute autre exception (transport) →
    `⚠️ API indisponible`, résultat vidé.

- [ ] **Step 1: tests en échec** (gestionnaires appelés directement, `ApiClient` réel via
  `internal_client(app)` sur la fixture `api_artifacts`, ou faux client pour les pannes) :
  - `test_selection_score_immediat` (`DEMO_VALID_ID`) : résultat non vide, pas d'erreur,
    `AMT_CREDIT` du champ = valeur du client.
  - `test_client_nullable_valeurs_vides` (`DEMO_NULLABLE_ID`) : un champ nullable affiché
    `None` est renvoyé `None` par `on_score` (corps capturé par un faux client).
  - `test_client_invalide_422_affiche` (`DEMO_INVALID_ID`) : markdown d'erreur non vide.
  - `test_modification_avertissement` : `AMT_CREDIT=5e6` → une ligne d'avertissement.
  - `test_modification_422` : `CNT_FAM_MEMBERS=0` → erreur affichée, résultat vidé.
  - `test_champ_vide_non_nullable_422` : `AMT_CREDIT=None` → erreur affichée.
  - `test_panne_api` : faux client qui lève `httpx.ConnectError` → `API indisponible`.
  - `test_reset_valeurs_origine`, `test_hasard_dans_l_echantillon`.
  - `test_build_ui` : `build_ui(...)` renvoie un `gr.Blocks` ; aucune fonction exposée en API
    (`demo.fns` toutes en `api_visibility="private"` ou équivalent Gradio 6.32).
  Run: `uv run pytest tests/test_ui_app.py -q --no-cov` → FAIL.
- [ ] **Step 2:** implémenter : mise en page de la spec §5 (deux colonnes, sélecteur
  `gr.Dropdown` filtrable des identifiants triés, bouton « 🎲 Client au hasard », champs,
  note « Les features autoFE ne sont pas recalculées : la modification sert à éprouver le
  contrat de l'API, pas à mesurer la sensibilité du score. », boutons « Scorer le client »
  et « Rétablir », `gr.HTML` résultat, `gr.Dataframe` avertissements, `gr.Markdown`
  erreurs). Thème de P5 (`gr.themes.Base`, accent bleu, sans ombres, clair forcé,
  `footer_links=[]`), CSS : vert `decision-accorde`, rouge `decision-refuse`. En-tête :
  version (`credit_scoring.__version__`) et lien `/docs`. Sélection initiale : premier
  identifiant, scoré au chargement (`demo.load`).
- [ ] **Step 3:** → PASS ; commit `feat(ui): écran de démonstration et gestionnaires`.

### Task 4: Montage dans l'API

**Files:**
- Create: `src/credit_scoring/ui/__init__.py` (`import gradio as gr` au niveau module,
  `def mount_ui(app: FastAPI) -> None`)
- Modify: `src/credit_scoring/api/app.py:106-117` (route `home`)
- Test: `tests/test_ui_mount.py` ; Modify `tests/test_api_health.py`

**Interfaces:**
- Consumes: `build_ui`, `internal_client`.
- Produces: `mount_ui(app)` = `gr.mount_gradio_app(app, build_ui(lambda: internal_client(app), lambda: app.state.demo_clients), path="/", ...options)` ;
  dans `api/app.py`, `def install_home(app: FastAPI) -> None` appelée en fin de module :
  `try: from credit_scoring.ui import mount_ui` / `except ImportError:` → route HTML
  `home` à `/` (texte actuel) ; sinon `mount_ui(app)`.

- [ ] **Step 1: tests en échec**
  - `test_racine_sert_gradio` : `TestClient(app).get("/")` → 200, HTML contenant `gradio`.
  - `test_api_intacte_avec_gradio` : avec la fixture `api_artifacts`, dans `with TestClient(app)` :
    `/health` 200, `/docs` 200, `POST /predict` (EXAMPLE_CLIENT + clé) 200 → le lifespan a
    bien chargé le modèle malgré le montage.
  - `test_sans_gradio_page_html` : `monkeypatch.setitem(sys.modules, "gradio", None)`,
    `monkeypatch.delitem(sys.modules, "credit_scoring.ui", raising=False)`, nouvelle
    `FastAPI()`, `install_home(app2)` → `GET /` = HTML avec `href="/docs"` et la version.
  - adapter `test_racine_publique_repond_200_avec_lien_vers_la_doc` (devient le test ci-dessus).
  Run: `uv run pytest tests/test_ui_mount.py tests/test_api_health.py -q --no-cov` → FAIL.
- [ ] **Step 2:** implémenter ; supprimer le décorateur `@app.get("/")` de `home` (la
  fonction reste, enregistrée par `install_home` via `app.add_api_route`).
- [ ] **Step 3:** suite complète `uv run pytest -m "not integration" -q` → PASS, couverture
  100 % ; `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests scripts`.
- [ ] **Step 4:** recette locale rapide : `MODEL_DIR=artifacts API_KEY=demo uv run uvicorn credit_scoring.api.app:app`
  puis navigateur (Playwright) sur `http://127.0.0.1:8000/` : sélection, hasard,
  avertissement (`AMT_CREDIT` 5 000 000), 422 (foyer 0), rétablir ; `/docs` accessible.
- [ ] **Step 5:** commit `feat(ui): interface Gradio montée à la racine de l'API`.

### Task 5: Déploiement sur le Space et documentation

**Files:**
- Modify: `scripts/deploy_space.py` (`locked_requirements`, `APP_PY`, docstring),
  `tests/test_deploy_space.py`
- Modify: `docs/api.md`, `docs/cicd.md`, `docs/docker.md`, `README.md`
- Create: `docs/ui/README.md` (+ captures `docs/ui/img/*.png`)

**Interfaces:**
- `locked_requirements()` ajoute `--extra ui` à `uv export`.
- `APP_PY` : `import spaces` en premier, fonction `@spaces.GPU` déclarée conservée,
  `uvicorn.run(app, ...)` **sans** `ZeroGPUMiddleware` (ajouté par `spaces` au montage).

- [ ] **Step 1: tests en échec** dans `tests/test_deploy_space.py` :
  `test_app_annonce_l_api_a_zerogpu` devient : `import spaces` avant `credit_scoring`,
  `@spaces.GPU` présent, `"ZeroGPUMiddleware" not in app_py` ; nouveau
  `test_export_avec_extra_ui` (monkeypatch de `subprocess.run`, `--extra` `ui` dans la
  commande). Run → FAIL.
- [ ] **Step 2:** implémenter → PASS.
- [ ] **Step 3: simulation ZeroGPU manuelle** (hors CI, comme v0.2.5) : faux service
  ZeroGPU (`POST /startup-report` journalisé) sur un port local, `app.py` généré lancé avec
  `SPACES_ZERO_GPU=true SPACES_ZERO_DEVICE_API_URL=… API_KEY=… MODEL_DIR=artifacts uv run --extra ui --with spaces==0.53.0 python app.py`.
  Expected: **un seul** `REÇU /startup-report` ; `/` (Gradio), `/health`, `POST /predict`
  en 200. Résultat recopié dans la PR.
- [ ] **Step 4:** docs : interface (`docs/ui/README.md` : accès, parcours, limite autoFE,
  source `ui-demo`, captures Playwright en thème clair), `api.md` (section interface et
  en-tête `X-Client`), `cicd.md` (extra `ui`, ZeroGPU via `mount_gradio_app`), `docker.md`
  (image sans interface, page HTML), `README.md` (lien vers l'interface du Space).
- [ ] **Step 5:** commit `feat(deploy): interface Gradio sur le Space ZeroGPU`.
- [ ] **Step 6 (après fusion du lot et release, hors plan) :** parcours Playwright sur
  `https://willisback-credit-scoring-api.hf.space/` et captures finales.
