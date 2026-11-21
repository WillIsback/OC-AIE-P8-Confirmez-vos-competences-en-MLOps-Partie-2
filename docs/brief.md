# Brief — Confirmez vos compétences en MLOps (Partie 2/2) (OC-AIE-P8)

> Reformulation des documents OpenClassrooms (non versionnés, dans `.oc/sources/`).

## Scénario

William est Data Scientist chez **« Prêt à Dépenser »**. Le modèle de scoring crédit
développé et versionné avec MLflow au projet précédent (P6) doit passer en production.
**Chloé Dubois, Lead Data Scientist**, demande pour le département « Crédit Express », qui
veut traiter les demandes en quasi temps réel :

- une **API fonctionnelle et déployable** (« Docker ready ») sous une semaine et demie ;
- un **dashboard ou rapport de suivi** en production (distribution des scores, temps de
  réponse…) ;
- un plan d'action.

## Livrables officiels

1. Historique des versions (liste des commits du dépôt GitHub public).
2. Scripts de l'API (prend les données d'un client, renvoie un score).
3. Dockerfile.
4. Scripts de tests automatisés.
5. Pipeline CI/CD au format YAML (tests et mise en production au moins à chaque push sur
   la branche principale).
6. Analyse du data drift au format notebook, avec un tableau de bord ou rapport de
   monitoring (distribution des scores, latence de l'API, temps d'inférence…).
7. Screenshots de la solution de stockage des données de production.

Attendu aussi dans la mission : un README (lancer l'API, interpréter le monitoring) et le
rapport d'optimisation de l'étape 4.

## Étapes

1. **Dépôt et versionnage** : dépôt public structuré (code, tests, notebooks, Dockerfile,
   dépendances), commits explicites, `.gitignore`, stratégie de branches, aucune donnée
   sensible.
2. **API + CI/CD** : API (FastAPI ou Gradio) documentée (Swagger) avec gestion des
   erreurs ; image Docker ; pipeline qui teste, construit l'image si les tests passent,
   puis déploie (environnement simulé ou réel). Vigilance : tests des cas critiques
   (champ obligatoire manquant, valeur hors plage, mauvais type), secrets, validation des
   entrées, **modèle chargé une seule fois au démarrage**, ressources de l'environnement.
3. **Stockage et analyse des données de production** : journaliser au minimum appels,
   entrées, sorties et temps d'exécution (logging structuré JSON) ; analyse automatique
   du drift et des anomalies opérationnelles (taux d'erreur, latence) avec Evidently ou
   NannyML ; visualisation. Une référence est nécessaire (données d'entraînement de P6).
   PoC local accepté. Vigilance : coûts de stockage, RGPD.
4. **Analyse et optimisation des performances** : profiling (cProfile…) à partir des
   données de monitoring, stratégies d'optimisation (quantification, code, ONNX Runtime,
   matériel), version optimisée déployée par la CI/CD, rapport avec gains mesurés et
   absence de régression (précision, biais), configuration finale justifiée.

## Soutenance

- Date visée : **11/01/2027** (planning du parcours : 14/12/2026 → 11/01/2027, 45 h).
- Rôle de l'évaluateur : **Chloé Dubois, Lead Data Scientist**.
- Déroulé (30 min) : 15 min de présentation (±5 ; hors de 10 à 20 min, refus possible),
  10 min de discussion, 5 min de débrief hors rôle.
- Présentation : contexte ; résultats du monitoring (analyse du drift, graphiques et
  métriques, collecte et analyse des logs) ; optimisations (tests, goulots, gain
  concret) ; tour rapide du dépôt (organisation, Dockerfile, CI/CD, README).
- **Démos imposées** : une requête type à l'API déployée et sa réponse ; un changement de
  code (commit) qui déclenche automatiquement tests, build de l'image et déploiement.
- **Axes de discussion** : robustesse et fiabilité (gestion des erreurs à tous les
  niveaux) ; monitoring et maintenance (dérive des données, maintenance à long terme) ;
  optimisation et scalabilité (choix software et hardware).

## Existant réutilisé

**Décision de William : appliquer les standards de P5 à la base de P6.**

- **P6** (`OC-AIE-P6-Initiez-vous-au-MLOps-Partie-1`) : modèle servi
  `home-credit-serving` v2 = encodeur ordinal + LightGBM tuné sur **122 features** + seuil
  métier figé **0,5348** (coût FN = 10 × FP), sortie `prob_default` / `decision` /
  `threshold` ; base SQLite `clients.db` des **48 744 clients du jeu de test** avec features
  calculées ; app Gradio ; latence ~22 ms en régime établi (113 ms au premier appel) ;
  build Docker jamais lancé ; artefacts non versionnés (`mlflow-artifacts/` 50 Mo,
  `data/inference` 49 Mo, `preprocessing_bundle.joblib`).
- **P5** (`OC-AIE-P5-Deployez-un-modele-de-Machine-Learning`) : FastAPI + Pydantic + JWT,
  PostgreSQL + SQLAlchemy + Alembic, Grafana provisionné, Docker Compose, image GHCR avec
  modèle embarqué, Space Hugging Face, CI GitHub Actions complète (tests, qualité,
  sécurité, release semver). Pas de SonarCloud (Aikido).

**Pièges qui changent le projet**

1. **Contrat d'entrée de l'API** : le modèle attend 122 features dont beaucoup sont des
   formules OpenFE sans plage naturelle, alors que l'énoncé parle des « données d'un
   client » et de tests du type « âge = −5 ». → décision n°1 de la session de specs.
2. **Dérive naturelle déjà présente** : la couverture `bureau_balance` passe de 30 %
   (train) à 87 % (test) — une vraie dérive à analyser, sans données fabriquées.
3. **Pas de cible dans le jeu de test** : on suit la dérive des données et des scores,
   pas la performance réelle.
4. **Faible marge d'optimisation** : LightGBM < 10 ms ; le temps est surtout dans le
   serveur (MLflow) et pandas — c'est là que l'étape 4 a des gains mesurables.
5. **Artefacts lourds non versionnés** (modèle ~10 Mo, base 49 Mo) : à embarquer
   proprement dans l'image ou à reconstruire.

## Matrice d'objectifs

| Livrable | Indicateur de la fiche | User story | 👤 Ta part | 🤖 Délégué |
|---|---|---|---|---|
| Historique des versions | Commits réguliers · lien public · `.gitignore` · système de branches | US1 Socle du dépôt et artefacts du modèle | Faire toi-même le flux branche → PR → merge sur au moins deux lots ; expliquer la stratégie de branches | Dépôt, outillage, rangement et chargement des artefacts P6 |
| Scripts API | Erreurs appréhendées correctement · routes documentées · modèle et données gérés sans erreur | US2 API de scoring | **Définir le contrat** : champs obligatoires, plages, réponses d'erreur ; expliquer le chargement unique du modèle | FastAPI, schéma Pydantic des 122 features, gestion des erreurs, Swagger |
| Dockerfile | Fonctionnel · ne copie que le nécessaire | US3 Image Docker | Lancer `docker build` / `docker run` à la main ; justifier chaque `COPY` | Dockerfile multi-étapes, `.dockerignore` |
| Tests automatisés | Couverture vérifiée · pertinence justifiable · inclus dans la CI/CD | US4 Tests et couverture | **Choisir les cas critiques** et justifier chacun ; lire le rapport de couverture | Code des tests, configuration de la couverture |
| Pipeline CI/CD | Tests inclus · déclenché au push sur main | US5 Pipeline CI/CD et déploiement | Comprendre l'ordre test → build → déploiement et les secrets ; suivre un run en direct | Workflows adaptés de P5, déploiement sur l'environnement cible |
| Screenshots du stockage | Adéquation aux exigences du monitoring justifiée · stratégie définie et documentée | US6 Journalisation et stockage des données de production | **Choisir quoi stocker et pourquoi** ; RGPD (rétention, minimisation) ; faire les captures | Logging structuré JSON, base de stockage, script de simulation de trafic |
| Analyse du data drift | Visualisation des différences · interprétation | US7 Analyse du drift (notebook) | **Interpréter** le rapport (dont `bureau_balance`), fixer les seuils d'alerte, décider de l'action | Notebook Evidently, comparaison référence / production |
| Dashboard de monitoring | (mission : scores, latence, temps d'inférence) | US8 Dashboard de monitoring | Lire et commenter chaque indicateur | Dashboard (Streamlit ou Grafana) |
| Optimisation (étape 4) | (mission : gain démontré, pas de régression, config justifiée) | US9 Profiling et optimisation | **Hypothèses** à partir du profiling, choix de la config finale, vérification de non-régression | Profiling, conversion ONNX, benchmarks, rapport |
| README | (mission : lancer l'API, interpréter le monitoring) | US10 Documentation | Relire et corriger | Première version du README et des docs |

## Nommage du zip

Dossier `Confirmez_vos_competences_en_MLOps_Partie_2_Derue_William`, fichiers
`Derue_William_<n°>_<livrable>_112026` (démarrage réel le 21/11/2026 ; à confirmer).
