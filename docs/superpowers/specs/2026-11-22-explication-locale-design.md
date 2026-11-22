# Design — Explication locale du score (#44)

- **Date** : 2026-11-22 · **Lot** : v0.4.0 (`feat`) · **Branche** : `feat/0.4.0-explication`
- **Statut** : validé par William (option A, badge « critère protégé (non-discrimination) »)

## Intention

Devant un refus, montrer **pourquoi pour ce client** : quelles features ont poussé le score
vers le refus ou vers l'accord, et de combien. Rendre visibles deux limites du modèle de P6
qu'une soutenance doit assumer : l'usage du sexe (`CODE_GENDER`, critère protégé) et l'opacité
des 79 features `autoFE_f_*` (65 % du modèle).

## Approches

| | Approche | Verdict |
|---|---|---|
| **A** | Route `POST /predict/explain` (même entrée, même clé, journalisée) | **retenue** : contrat de `/predict` inchangé, coût payé seulement à la demande |
| B | Champ `explanation` dans chaque réponse de `/predict` | contrat validé modifié, ~2 ms et réponse plus lourde à chaque appel |
| C | Calcul dans l'interface, directement sur le modèle | écartée : contourne l'API, rien de journalisé |

## Décisions

- **Calcul** : TreeSHAP natif de LightGBM (`booster.predict(X, pred_contrib=True)`), exact,
  ~2 ms, sans dépendance. Unité : **log-odds** (logit) ; `base_value + Σ contributions =
  logit(prob_default)`. Encodeur ordinal : une contribution = une feature d'entrée.
- **Réponse** : `ExplainResponse` = `PredictionResponse` + `explanation` :
  `base_value`, `top` (10 contributions de plus grande valeur absolue : `feature`, `value`
  reçue, `contribution`, `sensitive`, `derived`), `others` (somme des autres contributions).
- **Politique** : `SENSITIVE_FEATURES = {"CODE_GENDER": "sexe : critère protégé, ne peut fonder
  une décision de crédit (C. pénal art. 225-1)"}`, déclarée dans le code ; un test vérifie que
  chaque attribut déclaré existe dans `features.json`. La sensibilité est **juridique** : elle
  ne se déduit pas des artefacts. Ce n'est pas une question de vie privée (le sexe n'est pas
  une donnée de l'art. 9 RGPD) mais de **non-discrimination**.
- **Route** : déclarée **avant** `/predict/{sk_id_curr}` ; le middleware de journalisation
  reconnaît `/predict/explain` comme chemin propre.
- **Interface** : l'interface appelle `/predict/explain` (sélection et modification) avec le
  client complet ; graphique HTML en barres horizontales centrées sur zéro (rouge vers le
  refus, vert vers l'accord), badge « critère protégé (non-discrimination) » avec info-bulle,
  mention « combinaison calculée » pour les `autoFE_f_*`, ligne « autres features ».

## Non-objectifs

Réentraîner sans `CODE_GENDER` ; analyser les proxies dans les formules OpenFE ; explication
globale (déjà fournie par l'importance) ; bibliothèque `shap`.

## Laissé au builder

Libellés français éventuels des features lisibles, mise en forme fine du graphique.
