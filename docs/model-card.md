---
language: fr
library_name: lightgbm
pipeline_tag: tabular-classification
license: other
tags:
  - credit-scoring
  - lightgbm
  - tabular-classification
  - home-credit
---

# Home Credit — scoring de défaut (`home-credit-serving` v2)

Modèle de probabilité de défaut de remboursement d'un crédit, servi par l'API du projet
OpenClassrooms AI Engineer P8 (« Prêt à Dépenser », département Crédit Express).
Code, CI/CD et API : https://github.com/WillIsback/OC-AIE-P8-Confirmez-vos-competences-en-MLOps-Partie-2

## Contenu du dépôt

| Fichier | Rôle |
|---|---|
| `model.txt` | booster LightGBM 4.7.0 au format texte natif (aucun pickle) |
| `features.json` | ordre des 122 features, catégories de l'encodeur ordinal, bornes min/max du train |
| `manifest.json` | traçabilité MLflow, seuil, coûts, empreintes SHA-256, résultat de la validation |
| `sample_clients.csv` | 1 000 clients du jeu de test (tirage figé, graine 42) — démo et non-régression |
| `reference_predictions.csv` | scores et décisions du modèle P6 sur ces 1 000 clients |

Le service télécharge ce dépôt à une **révision figée** (SHA de commit) et refuse de démarrer
si une empreinte diffère du manifeste.

## Modèle

- **Origine** : Registry MLflow du projet P6, `home-credit-serving` v2 (run
  `2323ae2f37b74360b71498fe33e40d5b`), lui-même issu de `home-credit-lightgbm` v9 (tuné
  par Optuna).
- **Entrée** : 122 features déjà calculées (43 lisibles, dont 6 catégorielles encodées en
  ordinal — inconnue → −1 ; 79 générées par OpenFE), produites par le pipeline de P6 à
  partir de `application` et des tables secondaires (bureau, crédits précédents, échéances,
  POS, cartes).
- **Sortie** : `prob_default` ∈ [0, 1] ; décision **refusé** si `prob_default ≥ 0,5348`.
- **Seuil métier** : 0,5348, optimisé pour minimiser le coût moyen par client avec un faux
  négatif (défaut non détecté) **10 fois** plus coûteux qu'un faux positif.

## Données et entraînement

- Données : compétition Kaggle *Home Credit Default Risk* (`application_train` enrichie de
  111 agrégats des tables secondaires).
- Split stratifié 80/20 (246 008 / 61 503 lignes, graine 42) ; `application_test` jamais
  utilisé pour un ajustement. Imputation (médiane / mode) et encodage ajustés sur le train.
- Objectif d'optimisation : coût métier moyen en validation croisée 5 plis (seuil
  ré-optimisé dans chaque pli, sans fuite).

## Performances (projet P6)

| Mesure | Valeur |
|---|---|
| Coût métier moyen, CV 5 plis (objectif) | 0,4899 |
| Coût métier moyen, validation | 0,4814 |
| AUC, CV 5 plis | 0,7861 ± 0,0024 |
| AUC, validation | 0,7893 |
| PR-AUC, validation | 0,2887 |

## Fidélité du service (projet P8)

L'export depuis MLflow (booster texte + encodage réécrit) a été comparé au modèle P6 sur les
**48 744 clients du jeu de test** : écart maximal de probabilité **0,0**, décisions
identiques. Un test de non-régression le revérifie avant chaque déploiement (1 000 clients,
tolérance 1e-9).

## Usage prévu et limites

- **Usage prévu** : aide à la décision d'octroi pour un système interne, avec relecture
  humaine des cas limites ; démonstration pédagogique.
- **Hors périmètre** : décision automatique sans recours, autre population que celle de
  l'entraînement.
- **Limites connues** :
  - split aléatoire et non temporel : la performance réelle sur des demandes futures peut
    être plus faible ;
  - 79 features OpenFE sans interprétation métier ; les plus importantes du modèle en font
    partie ;
  - un arbre n'extrapole pas : hors des bornes du train, le score est celui de la borne ;
    l'API accepte ces valeurs et les signale (avertissement avec rang d'importance) ;
  - sans cible en production, la qualité se surveille par la dérive des données et des
    scores (monitoring du projet).
- **Équité** : `CODE_GENDER` fait partie des features (rang 13 sur 122 par gain) ; son
  usage dans une décision de crédit réelle demanderait une analyse d'impact et un avis
  juridique.

## Licence et confidentialité

Dépôt **privé** : `sample_clients.csv` et `reference_predictions.csv` proviennent des
données Kaggle Home Credit, dont le règlement interdit la redistribution. Usage limité au
projet pédagogique.
