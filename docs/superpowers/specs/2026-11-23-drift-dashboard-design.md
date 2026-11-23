# Design — Analyse du drift (#17) et dashboard de monitoring (#18)

- **Date** : 2026-11-23 · **Lot** : v0.4.0 (`feat`) · **Branches** : `feat/0.4.0-analyse-drift`,
  `feat/0.4.0-dashboard`
- **Décisions de William** : ADR-005 (Evidently ; dashboard en onglet de l'app Gradio du
  Space ; analyse planifiée), puis le 23/11/2026 :
  - référence = **échantillon stratifié de 20 000 lignes** du train de P6, en Parquet dans un
    dépôt HF privé ;
  - dérive calculée par un **job planifié** qui écrit son résumé dans Neon, et non à la
    demande dans le Space ;
  - Evidently 0.7.23 ne s'importe pas avec pandas 3 (incompatibilité non déclarée) :
    l'analyse vit dans un **sous-projet `analysis/` avec son propre verrou** (Evidently,
    pandas 2.3, Jupyter). L'API, l'image et le Space restent en pandas 3.

## Intention

Chloé doit voir d'un coup d'œil si la production va bien : volume, décisions, latence,
erreurs, dérive. William doit pouvoir **interpréter** cette dérive en soutenance, et l'ADR-005
le prévoit : « 30 % des features ont dérivé : est-ce grave, et comment le sais-tu sans
cible ? ». Il faut un **même calcul partout** : notebook, job et dashboard.

## Approches retenues (rappel)

| | Approche | Verdict |
|---|---|---|
| **A** | Job planifié (GitHub Actions) → table Neon `drift_reports` ; l'onglet lit Neon | **retenue** (William) : Evidently hors de l'image, onglet léger |
| B | Calcul Evidently à la demande dans le Space | écartée : image plus lourde, plusieurs secondes par clic |
| **Réf. 1** | Échantillon de 20 000 lignes, Parquet dans un dataset HF privé | **retenue** (William) |
| Réf. 2 | `train_fs.csv` complet, en local | écartée : aucune analyse en ligne |

## Composants

1. **Référence** (🤖, une fois) : `scripts/export_drift_reference.py`.
   - Tirage stratifié sur `TARGET` dans `train_fs.csv` de P6 (graine fixe) : les
     122 features brutes, au format de l'API, plus `prob_default`, le score du modèle sur
     cette ligne, qui sert de référence pour la dérive des scores.
   - Le fichier est écrit en Parquet et envoyé dans le dataset privé
     `WillIsback/credit-scoring-drift-reference`. Il n'est jamais versionné dans Git ni
     placé dans l'image.
2. **Module partagé** `credit_scoring.monitoring` :
   - `metrics.py` (sans Evidently, utilisé par le Space) : lecture de `prediction_logs` sur
     une fenêtre (24 h, 7 j ou 30 j) et une source (`api` par défaut). Il calcule les
     indicateurs : nombre d'appels, taux d'acceptation, taux d'erreur par type, latence et
     `inference_ms` en p50/p95, distribution des scores et série horaire. Les calculs se
     font avec pandas, donc ils marchent aussi sur SQLite pour les tests ;
   - `drift.py` (Evidently, importé seulement depuis `analysis/`) :
     - `production_frame()` : features et score des appels 200 de la fenêtre ;
     - `analyse(reference, current)` : `DataDriftPreset` sur les 122 features et dérive de
       `prob_default` ; il renvoie un résumé (part et nombre de features en dérive, détail
       par feature, dérive du score) et le rapport HTML ;
   - migration `0002_drift_reports` : `created_at`, bornes de la fenêtre, `n_reference`,
     `n_current`, `share_drifted`, `n_drifted`, `score_drift` (statistique et booléen),
     `model_version`, `details` (JSON, une entrée par feature) ;
   - `thresholds.py` : seuils d'alerte. Les valeurs de départ sont marquées « à fixer par
     William » (part 👤 de #17).
3. **Job** : `scripts/drift_job.py` et le workflow `drift-analysis.yml` (quotidien, plus
   déclenchement manuel, environnement `ml-models`).
   - Il télécharge la référence, analyse les 7 derniers jours de `source = 'api'` et écrit
     une ligne dans `drift_reports`.
   - Le rapport HTML est publié comme artefact du run, conservé 30 jours.
   - En dessous de 200 appels dans la fenêtre, il écrit un rapport « échantillon
     insuffisant » au lieu d'un faux signal.
4. **Notebook** `notebooks/analyse_drift.ipynb` (🤖 pour le code, 👤 pour l'interprétation).
   - Il utilise le même module : il lit Neon (`DATABASE_URL`) et la référence HF.
   - Il produit le rapport Evidently, compare les distributions des features clés (top
     importance, `bureau_balance`, `CODE_GENDER`) et des scores, et donne les anomalies
     opérationnelles.
   - Les cellules d'interprétation et de seuils sont laissées à William.
   - Le notebook versionné ne montre **que des agrégats**, jamais de ligne client.
5. **Dashboard** : un onglet « Monitoring » à côté de l'onglet « Scoring »
   (`gr.Tabs`).
   - Contrôles : fenêtre, source, bouton « Actualiser ».
   - Tuiles : appels, acceptation, erreurs, p50/p95 de la latence et de l'inférence.
   - Graphiques Gradio natifs (`gr.BarPlot`, `gr.LinePlot`, sans dépendance) :
     distribution des scores avec le seuil, latence par heure, erreurs par type.
   - Bloc « Dérive » : dernier `drift_reports`, alerte comparée au seuil, tableau des
     features en dérive, dérive du score.
   - Sans base configurée, l'onglet l'indique au lieu de planter.
   - Lecture seule, agrégats seulement : il est public comme le reste de la démo.

## Environnements

- **Racine** (API, Space, tests) : pandas 3, sans Evidently. La contrainte du paquet passe
  de `pandas>=3.1.1` à `pandas>=2.2`, mais le verrou de la racine reste en 3.1.1.
- **`analysis/`** : `pyproject.toml` et `uv.lock` propres. On y trouve `evidently==0.7.23`,
  `pandas>=2.2,<3`, `jupyter`, `pyarrow`, `huggingface_hub`, et le paquet racine en
  dépendance de chemin (`credit-scoring = { path = "..", editable = true }`).
  - Le job (`uv run --project analysis …`) et le notebook s'exécutent ici.
  - La CI y lance les tests du module de dérive (`tests/drift/`, marqueur `drift`).
- `metrics.py` et `drift.py` doivent marcher avec pandas 2 et 3.

## Non-objectifs

Réentraînement ; alertes par e-mail ; estimation de performance sans cible (NannyML,
écarté dans l'ADR-005) ; second Space ; compte Neon en lecture seule (`DATABASE_URL_RO`,
prévu par l'ADR-005 initial). Ce dernier est remplacé par la même connexion que le Space,
puisque le dashboard vit dans le même processus : à dire à l'oral.

## Parts de William (👤)

- #17 : interpréter le rapport, dont la dérive `bureau_balance`, fixer les seuils dans
  `thresholds.py` et décider de l'action (surveiller, ajuster, réentraîner).
- #18 : lire et commenter chaque indicateur comme en soutenance.
- Avant les captures : lancer la simulation de trafic contre le Space.

## Laissé au builder

Mise en page fine de l'onglet, choix des tests statistiques par défaut d'Evidently
(conservés), libellés.
