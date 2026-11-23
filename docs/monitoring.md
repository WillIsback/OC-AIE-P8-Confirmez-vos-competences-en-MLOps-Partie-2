# Journalisation et stockage des données de production

Décisions : ADR-004 (stockage) et ADR-005 (dashboard) dans `docs/spec.md` ; design détaillé
dans `docs/superpowers/specs/2026-11-22-journalisation-production-design.md` (#16).

## Ce qui est stocké, et pourquoi

Chaque appel `POST /predict`, `POST /predict/explain` ou `POST /predict/{sk_id_curr}` produit
**un enregistrement**
(table `prediction_logs`), y compris les appels refusés. Choix de William : tout tracer,
chaque groupe de colonnes servant un usage du monitoring.

| Groupe | Colonnes | Usage |
|---|---|---|
| Traçabilité | `request_id` (aussi renvoyé en en-tête `X-Request-ID`), `created_at` (UTC), `source`, `path` (gabarit de route), `api_version`, `model_version` | relier une ligne à une version du code et du modèle ; isoler la démo et la CI |
| Identité | `client_ref` : HMAC-SHA256 de `SK_ID_CURR` (route de démo seulement) | suivre les appels d'un même client **sans** l'identifier |
| Entrées | `features` : les 122 features validées ; pour un 422, le corps reçu (tronqué à 64 Kio) ; rien pour un 401 | dérive des données (Evidently, v0.4.0) |
| Sorties | `prob_default`, `decision`, `threshold`, `warnings`, `n_warnings` | dérive des scores, taux de refus, valeurs hors bornes |
| Performance | `latency_ms` (requête complète), `inference_ms` (encodage et `model.predict` ; plus les contributions SHAP sur `/predict/explain`) | latence, latences anormales, comparaison avant/après optimisation |
| Erreurs | `status_code`, `error_type` (`unauthorized`, `not_found`, `validation`, `client_error`, `internal`), `error_detail` (détail compact du 422) | taux d'erreur, champs le plus souvent refusés |

`source` vaut `api` (trafic de production, y compris la simulation), `ui-demo` (interface
Gradio, en-tête `X-Client`) ou `ci` (test de fumée de chaque release). **Les analyses de
production filtrent `source = 'api'`** : les essais de démonstration ne faussent pas le drift.
L'en-tête n'est pas une authentification, seulement un tri.

## Comment c'est écrit

- Un middleware ASGI mesure et assemble l'enregistrement ; les routes y déposent features,
  score et temps d'inférence.
- **Deux sorties** : une ligne JSON sur stdout (logs du Space), et une écriture en base par un
  thread de fond, par lots.
- **Une panne de la base ne casse jamais une prédiction** : file pleine ou base injoignable →
  enregistrement abandonné et compté ; `GET /health` expose `logging.database` et
  `logging.dropped`. La ligne stdout reste.
- Stack : SQLAlchemy 2, psycopg 3, migrations Alembic appliquées par le job `deploy` de la
  release (jamais par l'application).

## Où : Neon, région UE

Postgres managé [Neon](https://neon.com), projet `credit-scoring-P8`, région
**aws-eu-central-1 (Francfort)** : les données restent dans l'UE. Offre gratuite : 1 Go de
stockage (≈ 250 000 appels), mise en veille après 5 minutes d'inactivité. Le disque d'un
Space gratuit étant effacé à chaque redémarrage (donc à chaque déploiement), une base SQLite
locale aurait perdu les données à chaque release.

## Rétention et archivage

- **Fenêtre glissante de 30 jours** pour les données vivantes (décision de William).
- **Archivage quotidien** (`archive-logs.yml`, 03:00 UTC) : les lignes de plus de 30 jours
  partent en Parquet dans un dataset Hugging Face **privé**
  (`WillisBack/credit-scoring-logs-archive`), puis sont supprimées de Neon — seulement après
  l'envoi réussi.
- Mécanisme **démonstratif** : le projet est soutenu avant que des données atteignent
  30 jours ; le workflow se lance à la main avec une durée courte (`older_than = 1h`). Les
  archives ne sont pas conservées : le dataset est supprimé à l'arrêt du Space.

## RGPD

| Principe | Mise en œuvre |
|---|---|
| Minimisation | pas de nom ni de contact (absents du jeu Kaggle) ; aucun corps stocké pour un appel non authentifié |
| Pseudonymisation | `SK_ID_CURR` jamais stocké en clair (HMAC dérivé de la clé d'API ; une rotation de la clé change les pseudonymes) ; `path` = gabarit de route, sans l'identifiant |
| Limitation de la conservation | 30 jours en base, archives supprimées avec le projet |
| Localisation | Neon en UE (Francfort), dataset d'archive privé |
| Sécurité | accès par secret (`DATABASE_URL`, environnement GitHub `ml-models` limité à `main`, secret du Space) ; chiffrement au repos assuré par Neon ; TLS obligatoire (`sslmode=require`) |
| Pistes non implémentées (oral) | chiffrement applicatif des colonnes sensibles ; rôles Postgres séparés (écriture seule pour l'API, lecture seule pour le dashboard) |

Les features restent des données personnelles (revenus, âge, genre) : elles sont gardées
parce que l'analyse du drift en a besoin, et seulement pendant la fenêtre de 30 jours.

## Simulation de trafic

```bash
API_KEY=… uv run python scripts/simulate_traffic.py --p6 <dossier P6> \
    --url https://willisback-credit-scoring-api.hf.space --n 2000 --rate 5
```

Clients tirés de `clients.db` de P6 (jeu de test Kaggle, local), envoyés tels quels : leur
écart au jeu d'entraînement est une vraie dérive. 5 % de requêtes violent une règle métier
(422) et 2 % n'ont pas de clé (401).

## Requêtes d'exemple (console SQL Neon)

```sql
-- Volume et taux d'erreur par source
SELECT source, count(*) AS appels,
       round(100.0 * avg((status_code >= 400)::int), 1) AS pct_erreurs
FROM prediction_logs GROUP BY source;

-- Latence p95 par heure (trafic de production)
SELECT date_trunc('hour', created_at) AS heure,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY inference_ms) AS p95_inference_ms
FROM prediction_logs WHERE source = 'api' AND status_code = 200 AND path <> '/predict/explain'
GROUP BY 1 ORDER BY 1;

-- Distribution des scores et taux de refus
SELECT width_bucket(prob_default, 0, 1, 10) AS tranche, count(*),
       round(100.0 * avg((decision = 'refusé')::int), 1) AS pct_refus
FROM prediction_logs WHERE source = 'api' AND status_code = 200
GROUP BY 1 ORDER BY 1;

-- Champs les plus souvent refusés (422)
SELECT e->'loc'->>-1 AS champ, count(*)
FROM prediction_logs, jsonb_array_elements(error_detail) AS e
WHERE error_type = 'validation' GROUP BY 1 ORDER BY 2 DESC;
```
