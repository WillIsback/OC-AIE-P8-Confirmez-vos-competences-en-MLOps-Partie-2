# Design — Journalisation et stockage des données de production (#16)

- **Date** : 2026-11-22
- **Lot** : v0.3.0 (`feat`), branche `feat/0.3.0-logs-stockage` ; exécuté **avant** l'interface
  Gradio (#40)
- **Références** : ADR-004 (stockage), ADR-005 (dashboard), design de l'interface (D8)

## 1. Intention

Garder chaque appel de scoring dans un format analysable, pour que le notebook de drift et le
dashboard (v0.4.0) travaillent sur de vraies données de production : entrées, sorties, temps
d'exécution, erreurs. Fiche d'évaluation : justifier l'adéquation aux besoins du monitoring et
documenter la stratégie (contenu, rétention, RGPD).

## 2. Décisions de William

| # | Décision |
|---|---|
| W1 | **Tout tracer** : traçabilité, entrées (122 features), sorties, performance, erreurs, source. |
| W2 | **Fenêtre glissante de 30 jours** pour les données vivantes. |
| W3 | **Archivage toutes les 24 h** des entrées expirées ; mécanisme **démonstratif** : les archives ne sont pas conservées au-delà du projet (Space arrêté après la soutenance, < 30 jours). |
| W4 | Chiffrement applicatif des colonnes : **évoqué à l'oral, non implémenté** (Neon chiffre déjà le stockage au repos). |
| W5 | Base **Neon** (Postgres managé), projet `credit-scoring-P8`, **région aws-eu-central-1** (Francfort) ; secret `DATABASE_URL` dans l'environnement `ml-models`. |
| W6 | Trafic de l'interface distingué : colonne `source` (`api` / `ui-demo`, en-tête `X-Client`). |
| W7 | Dashboard : **onglet du Space de l'API** (Gradio), pas de second Space (limite de 2 Spaces ZeroGPU). ADR-005 mis à jour en conséquence ; réalisation en v0.4.0 (#18). |

## 2 bis. Choix de l'agent (relecture du design)

| # | Question | Choix |
|---|---|---|
| A1 | Trafic de CI dans la table | Valeur `source` supplémentaire **`ci`** (en-tête `X-Client: ci`) : envoyée par le test de fumée de `deploy_space.py`. La gate de non-régression tourne en processus sans `DATABASE_URL` (stdout seulement). Les analyses filtrent `source = 'api'`. |
| A2 | Clé du HMAC de `client_ref` | Dérivée d'`API_KEY` (HMAC-SHA256 avec un préfixe de domaine) : aucun secret de plus. Limite documentée : une rotation de la clé change les `client_ref`. |
| A3 | Endpoint Neon | Le secret `DATABASE_URL` est l'endpoint **poolé** : engine psycopg 3 avec `prepare_threshold=None` (compatible PgBouncer) et `pool_pre_ping=True` ; même URL pour l'app, Alembic et l'archivage (DDL transactionnel, pas de verrou de session). Premier insert après autosuspend lent : absorbé par l'écriture en tâche de fond. |
| A4 | Dataset d'archive | Créé par le script (`create_repo(private=True, exist_ok=True)`) avec `HF_TOKEN` de `ml-models` ; s'il n'a pas le droit d'écrire sur un dataset, l'échec est explicite et William ajuste le jeton. `pyarrow` en dépendance du groupe `archive` (hors image). |
| A5 | Postgres en CI de PR | Comme le prévoyait l'ADR-004 : service **Postgres éphémère** dans `ci-test`, les tests de stockage tournent sur SQLite **et** Postgres (marqueur `postgres`, sautés sans `TEST_DATABASE_URL`) ; les écarts de dialecte sont vus avant la fusion. Neon réel : test d'intégration dans un **schéma temporaire** supprimé après coup, jamais dans `prediction_logs`. |

## 3. Non-objectifs

Analyse du drift et dashboard (v0.4.0) ; rôles Postgres séparés écriture / lecture (piste citée
dans la doc) ; chiffrement de colonnes (W4) ; journalisation des routes hors scoring.

## 4. Contenu d'un enregistrement (table `prediction_logs`)

| Groupe | Colonnes | Sert à |
|---|---|---|
| Traçabilité | `id`, `request_id` (uuid, renvoyé en en-tête `X-Request-ID`), `created_at` (UTC), `source` (`api`, `ui-demo`, `ci`), `path`, `api_version`, `model_version` | relier une ligne à une version ; filtrer la démo |
| Identité | `client_ref` : HMAC-SHA256 de `SK_ID_CURR` (route de démo uniquement), jamais l'identifiant brut | relier les appels d'un même client sans l'identifier (pseudonymisation) |
| Entrées | `features` (JSON) : les 122 features validées ; pour un 422, le corps reçu (JSON, tronqué à 64 Kio, marqueur si non JSON) ; rien pour un 401 | drift des données |
| Sorties | `prob_default`, `decision`, `threshold`, `warnings` (JSON : feature, valeur, rang) , `n_warnings` | drift des scores, taux de refus |
| Performance | `latency_ms` (requête complète, middleware), `inference_ms` (`model.predict` seul) | dashboard, latences anormales |
| Erreurs | `status_code`, `error_type` (`unauthorized`, `not_found`, `validation`, `internal`), `error_detail` (JSON compact du 422) | taux d'erreur |

Routes journalisées : `POST /predict` et `POST /predict/{sk_id_curr}` uniquement.

## 5. Mécanisme

- **Middleware ASGI** (`credit_scoring.monitoring.middleware`) sur les routes `/predict…` :
  bufferise le corps, mesure la latence, lit le statut, génère `request_id`. Les routes
  déposent features, score, avertissements, `inference_ms` et `client_ref` dans
  `request.state` ; le middleware assemble l'enregistrement.
- **Deux sorties** : une ligne JSON structurée sur stdout (toujours), et une file vers la base.
- **Écriture en tâche de fond** : `ProductionLogWriter` = file bornée (10 000) + thread qui
  insère par lots (SQLAlchemy Core). File pleine ou base en erreur → enregistrement abandonné,
  compteur incrémenté, la ligne stdout reste : **une panne de la base ne casse jamais une
  prédiction** (ADR-004). Arrêt propre : vidage de la file au lifespan shutdown.
- `DATABASE_URL` absent (tests, image Docker locale) → stdout seulement.
- `/health` ajoute `{"logging": {"database": bool, "dropped": int}}` (version inchangée pour
  le test de fumée).
- **Stack** (standard P5) : SQLAlchemy 2 + psycopg 3 + Alembic. Type JSON portable
  (`JSON().with_variant(JSONB, "postgresql")`) : tests sur SQLite, production sur Postgres.
- **Migrations hors de l'app** : `alembic upgrade head` dans le job `deploy` de la release
  (environnement `ml-models`), avant de pousser le Space ; l'app ne modifie jamais le schéma.
  Le Space reçoit `DATABASE_URL` comme secret (poussé par `deploy_space.py`).

## 6. Rétention et archivage (W2, W3)

- `scripts/archive_logs.py --older-than 30d [--dry-run]` : lignes `created_at` antérieures →
  fichier Parquet → dataset Hugging Face **privé** `WillisBack/credit-scoring-logs-archive`
  (`archive/AAAA-MM-JJ.parquet`) → suppression des lignes, **seulement après** l'envoi réussi.
- Workflow `archive-logs.yml` : planifié chaque jour (03:00 UTC) + `workflow_dispatch` avec
  `older_than` (ex. `1h` pour la démo, puisque rien n'aura 30 jours avant la soutenance).
- Archives démonstratives : supprimées avec le dataset à l'arrêt du projet (documenté).

## 7. Simulation de trafic

`scripts/simulate_traffic.py --url <Space> --n 2000 --rate 5 --invalid-share 0.05` : clients
tirés de `clients.db` de P6 (48 744 clients du test, local, jamais publié) envoyés à
`POST /predict` avec la clé ; une part de requêtes invalides (422) et sans clé (401) pour
alimenter le taux d'erreur. Source `api`. Sert au drift réel (train → test) de v0.4.0.

## 8. Tests

- Unitaires (SQLite temporaire, sans réseau) : un enregistrement par appel 200 / 401 / 404 /
  422, contenu attendu (features, score, `inference_ms`, `source`, `client_ref` haché, pas de
  corps pour 401) ; routes hors scoring non journalisées ; base en panne → prédiction 200 et
  compteur ; file pleine ; `DATABASE_URL` absent ; migrations Alembic appliquées sur SQLite ;
  archivage (sélection, envoi simulé, suppression seulement après envoi, dry-run) ;
  simulation (construction des requêtes, part invalide).
- Intégration (`-m integration`, `DATABASE_URL` réel) : migration + insertion + relecture sur
  Neon, dans la gate de la release.

## 9. Documentation et part 👤

- `docs/monitoring.md` : stratégie (contenu et usage de chaque groupe, rétention, archivage,
  RGPD : minimisation, pseudonymisation, région UE, chiffrement au repos Neon, accès par
  secret, suppression à l'arrêt), requêtes SQL d'exemple.
- ADR-004 et ADR-005 complétés (W1–W7).
- 👤 William : captures de la console Neon (table, requêtes) après une simulation de trafic.

## 10. Laissé au builder

Taille des lots d'insertion, format exact de la ligne stdout, index (au minimum
`created_at`, `source`), découpage des modules.
