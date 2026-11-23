# API de scoring

Décisions de référence : ADR-001 (contrat d'entrée), ADR-002 (modèle), ADR-003 (clé d'API)
dans `docs/spec.md`. Documentation interactive : `/docs` (Swagger, avec exemples).

## Routes

| Route | Clé | Rôle |
|---|---|---|
| `GET /health` | non | vivacité, version déployée, état de la journalisation (`logging.database`, `logging.dropped`) |
| `POST /predict` | oui | score d'un client décrit par ses 122 features |
| `POST /predict/explain` | oui | même entrée et même validation que `/predict`, plus l'**explication locale** du score (#44) |
| `POST /predict/{sk_id_curr}` | oui | démo : client de l'échantillon (1 000 clients du test), **même validation** |
| `GET /docs`, `/openapi.json` | non | documentation |
| `GET /` | non | interface de démonstration Gradio (Space, extra `ui`) ; page HTML sinon — `docs/ui/README.md` |

Réponse 200 :

```json
{
  "sk_id_curr": null,
  "prob_default": 0.31,
  "decision": "accordé",
  "threshold": 0.5348,
  "model_version": "home-credit-serving v2",
  "warnings": []
}
```

`decision` vaut `refusé` si `prob_default ≥ threshold` (seuil métier, coût FN = 10 × FP).

Chaque appel `/predict…` est journalisé (`docs/monitoring.md`) : la réponse porte l'en-tête
`X-Request-ID`, identifiant de sa ligne dans `prediction_logs`. L'en-tête facultatif
`X-Client` (`ui-demo`, `ci`) classe l'appel hors du trafic de production.

## Contrat d'entrée (validé par William le 22/11/2026)

**Invalide → 422** (`detail` : liste de `{loc, msg, type, input?}`) :

- champ manquant ou inconnu (`extra="forbid"`) ; mauvais type ; NaN ou infini ;
- `null` sur une feature non nullable — seules les **19 `autoFE_*`** qui ont des valeurs
  manquantes dans les données de P6 acceptent `null` (le modèle a une branche NaN pour
  elles) ; les 43 features lisibles n'en ont jamais eu ;
- catégorie hors liste (ex. `"m"` au lieu de `"M"`) : plus strict que P6, qui encodait une
  inconnue en −1, pour qu'une faute de saisie ne fausse pas le score en silence ;
- règle métier violée :

| Règle | Features |
|---|---|
| > 0 | `AMT_CREDIT` |
| entier 0 ou 1 | `FLAG_EMAIL`, `FLAG_CONT_MOBILE`, `FLAG_DOCUMENT_3`, `REG_CITY_NOT_WORK_CITY` |
| entier de 0 à 23 | `HOUR_APPR_PROCESS_START` (règle écrite par William) |
| entier ≥ 1 | `CNT_FAM_MEMBERS` |
| entier ≥ 0 | `INST_COUNT`, `INST_PREV_COUNT`, `PREV_CANCELED_COUNT`, `OBS_60_CNT_SOCIAL_CIRCLE`, `DEF_30_CNT_SOCIAL_CIRCLE` |
| ≥ 0 | `PREV_CNT_PAYMENT_MEAN`, `POS_CNT_INSTALMENT_FUTURE_MEAN`, `DAYS_REGISTRATION` (années), `OWN_CAR_AGE` |
| ≤ 0 (jours passés) | `PREV_DAYS_DECISION_MEAN`, `PREV_DAYS_TERMINATION_MAX`, `PREV_REF_DAYS_DECISION_MAX`, `BUR_DAYS_CREDIT_MIN`, `BUR_ACT_DAYS_CREDIT_MEAN`, `INST_DAYS_ENTRY_PAYMENT_MAX` |

`PREV_DAYS_LAST_DUE_1ST_VERSION_MAX` n'a pas de règle : une échéance prévue peut être
future (jusqu'à +2 389 jours dans le train). Les 48 744 clients du test respectent toutes
les règles.

**Inhabituel → 200 + avertissement** : une valeur hors des bornes [min ; max] du jeu
d'entraînement est acceptée et décrite dans `warnings` (feature, valeur, bornes). Le
client est réel ; le refuser bloquerait le métier, et l'avertissement alimente le suivi de
dérive. Les 79 `autoFE_*` (formules OpenFE sans sens métier) n'ont que ce contrôle. Un arbre
n'extrapole pas : au-delà de la dernière coupure, la valeur reçoit le score de la borne
(ex. `HOUR_APPR_PROCESS_START` = 25 donne le même score que 23).

Chaque avertissement porte l'**importance globale** de la feature (idée de William) :
`importance_rank` (1 = la plus forte, sur 122) et `importance_share` (part du gain total du
booster servi, calculée une fois au démarrage, sans coût par requête). Un dépassement sur
une feature du haut du classement mérite une attention immédiate ; en fin de classement, il
pèse peu sur le score. Exemples sur le modèle servi : `autoFE_f_0` rang 1 (19,3 % du gain),
`OCCUPATION_TYPE` rang 8, `AMT_CREDIT` rang 18 (1,2 %), `HOUR_APPR_PROCESS_START` rang 108
(0,2 %) ; 2 features ont un gain nul.

Pourquoi le gain et pas SHAP : P6 a utilisé |SHAP| moyen pour **sélectionner** les features
(BorutaShap, sur un LightGBM de 200 arbres), pas pour classer le modèle servi ; le gain est
lu directement dans le booster en production. La contribution SHAP locale (impact de la
valeur sur le score de ce client) coûterait une seconde passe sur les 2 983 arbres à chaque
avertissement : écartée, elle relève de l'explication d'une décision, pas de la qualité des
données.

**Ordre des contrôles** : clé d'API (401) avant la validation (422) — un appelant non
authentifié n'apprend rien du contrat.

## Explication locale : `POST /predict/explain` (#44)

La réponse est celle de `/predict`, avec un champ `explanation` en plus :

```json
"explanation": {
  "base_value": -0.59,
  "top": [
    {"feature": "CODE_GENDER", "value": "M", "contribution": 0.136,
     "sensitive": true, "derived": false},
    {"feature": "autoFE_f_131", "value": 0.0426, "contribution": -0.087,
     "sensitive": false, "derived": true}
  ],
  "others": 0.535
}
```

- **Calcul** : TreeSHAP natif de LightGBM (`booster.predict(X, pred_contrib=True)`).
  Le calcul est exact, n'ajoute aucune dépendance et coûte environ 1,6 ms de plus qu'un
  `/predict` (médianes locales de `inference_ms` pour 100038 : 12,6 ms contre 14,2 ms). Le
  client n'est encodé qu'une fois pour le score et les contributions.
- **Unité : log-odds.** Voici comment l'explication reconstitue le score :
  `base_value + Σ top.contribution + others = logit(prob_default)`, où
  `logit(p) = ln(p / (1 − p))`. Pour le client 100038, l'écart est de 2·10⁻¹⁵.
- **Lecture** :
  - une contribution > 0 pousse vers le refus, < 0 vers l'accord ;
  - `top` contient les 10 contributions les plus fortes en valeur absolue ;
  - `others` est la somme des 112 autres.
- **`sensitive`** : la feature est un critère protégé (politique déclarée dans
  `api/fairness.py`, ADR-007). Seul `CODE_GENDER` l'est.
- **`derived`** : la feature est une combinaison calculée par OpenFE (`autoFE_*`), sans sens
  métier direct. Elles représentent 79 features sur 122.
- **Coût** : il n'est payé qu'à la demande, et le contrat de `/predict` reste inchangé.
  La route est journalisée sous son propre chemin (`path = "/predict/explain"`), avec
  `inference_ms` = score + contributions.

## Où est le code

- `src/credit_scoring/api/features_schema.py` : types des 122 features, **généré** par
  `scripts/generate_schema.py` (à relancer à chaque nouveau modèle) ; l'exemple Swagger est
  un client synthétique (médianes du train), aucune ligne des données Kaggle n'est versionnée ;
- `src/credit_scoring/api/schemas.py` : règles métier, écrites à la main ;
- `src/credit_scoring/api/security.py` : clé comparée en temps constant ;
- `src/credit_scoring/api/fairness.py` : attributs protégés signalés par l'explication ;
- `src/credit_scoring/api/scoring.py` : `score` et `explain` (contributions SHAP) ;
- `src/credit_scoring/api/app.py` : routes, `lifespan` (clé, modèle chargé une fois, clients
  de démo ; le service refuse de démarrer s'il manque l'un d'eux), 422 compact.

## Latence locale

`uv run python scripts/bench_latency.py` (1 000 requêtes `/predict` en processus, après 50
de chauffe, vrais artefacts) — 22/11/2026 :

| Mesure | p50 | p95 | p99 |
|---|---|---|---|
| latence totale | 13,2 ms | **14,4 ms** | 15,6 ms |
| inférence seule (`ScoringModel.predict`) | 10,3 ms | 11,0 ms | 12,4 ms |

Machine : AMD Ryzen 7 5700G (16 threads), Linux 6.8, Python 3.12.3, LightGBM 4.7.0.
L'inférence (2 983 arbres) représente ~77 % de la latence : c'est la cible du rapport
d'optimisation (v0.4.0). Ne comparer qu'à des mesures faites sur la même machine.
