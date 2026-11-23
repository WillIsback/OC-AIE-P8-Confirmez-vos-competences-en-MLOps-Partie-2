# Spécification technique — OC-AIE-P8

## Vue d'ensemble

Service de scoring crédit pour le département Crédit Express de « Prêt à Dépenser » :
une API reçoit les caractéristiques d'un client, renvoie un score de risque de défaut, la
décision (accorder / refuser) et le seuil métier appliqué. Le service est conteneurisé,
déployé automatiquement par la CI/CD sur un Space Hugging Face, journalise ses appels pour
le monitoring (dérive des données, latence, erreurs) et fait l'objet d'une optimisation
mesurée. Architecture : `docs/architecture.md`.

## Décisions

### ADR-001 — Contrat d'entrée de l'API

- **Contexte** : la mission demande une API qui prend « les données d'un client » et des
  tests sur des entrées manquantes, hors plage ou mal typées. Le modèle de P6 attend
  122 features déjà calculées, dont une partie générée par OpenFE sans plage naturelle ;
  leur recalcul depuis les données brutes demande l'historique des 6 tables secondaires et
  2 à 5 s par client.
- **Options** :
  1. Identifiant client seul, features lues dans `clients.db` — simple, mais presque rien
     à valider et éloigné de l'énoncé.
  2. Les 122 features validées (Pydantic) : types et champs obligatoires, règles métier sur
     les features lisibles, bornes du jeu d'entraînement pour les autres ; route de démo
     `/predict/{sk_id_curr}` qui passe par la même validation — fidèle à l'énoncé, schéma
     volumineux (généré).
  3. Données brutes et recalcul — irréaliste (historique complet, latence de plusieurs
     secondes).
- **Recommandation** : option 2.
- **Choix** : **option 2** (William, 21/11/2026).
  - Valeur **invalide** (type, champ obligatoire manquant, règle métier violée, ex. âge
    négatif) → refus **422** avec message explicite.
  - Valeur **inhabituelle** (hors des bornes du jeu d'entraînement mais plausible) →
    **acceptée et signalée** (champ d'avertissement dans la réponse, journalisée pour le
    monitoring). Confirmé par William le 22/11/2026, avec la liste des règles métier, la
    politique des `null` et le refus des catégories inconnues : voir `docs/api.md`.
- **Conséquences** :
  - code : schéma Pydantic généré à partir de la liste ordonnée des features, des règles
    métier et des bornes de `preprocessing_bundle.joblib` ;
  - tests : un test par type d'erreur (manquant, mauvais type, règle métier) et des cas
    limites aux bornes ;
  - monitoring : taux de valeurs hors bornes par feature, signal précoce de dérive ;
  - soutenance : distinguer clairement donnée invalide et donnée inhabituelle.
- **Indicateurs de la fiche** : scripts API (erreurs appréhendées correctement ; modèle et
  données gérés sans erreur) ; tests (pertinence justifiable).
- **Question d'oral probable** : « Pourquoi refuser un âge de −5 mais accepter un revenu
  supérieur au maximum vu à l'entraînement ? »

### ADR-002 — Mode de service du modèle et emplacement des artefacts

- **Contexte** : en P6, le modèle est servi par `mlflow models serve` à partir du wrapper
  `home-credit-serving` v2 (`python_model.pkl`, ~4,5 Mo : encodeur ordinal + LightGBM +
  seuil). MLflow au runtime alourdit l'image et le démarrage ; les artefacts vivent dans un
  tracking server local non versionné ; l'appel complet (~22 ms) coûte plus que
  l'inférence LightGBM seule (< 10 ms).
- **Options** :
  1. Garder le pyfunc MLflow chargé une fois dans FastAPI — fidélité et traçabilité
     natives, mais image lourde, démarrage lent, surcoût par appel.
  2. Extraire les artefacts bruts du Registry (encodeur, booster, seuil, features
     ordonnées, bornes) et les charger directement avec `lightgbm` / `scikit-learn`, avec
     un manifeste de traçabilité et un test de non-régression contre P6 — image légère,
     chemin d'inférence maîtrisé, logique du wrapper à réimplémenter.
- **Recommandation** : option 2, artefacts publiés sur un dépôt modèle Hugging Face
  téléchargé au build à une révision figée ; échantillon de ~1 000 clients du jeu de test
  embarqué pour la route de démo.
- **Choix** : **option 2** (William, 21/11/2026), avec les artefacts sur le Hub HF.
- **Conséquences** :
  - code : script d'extraction depuis le Registry P6 (`manifest.json` : run id, version du
    Registry, empreintes SHA-256) ; chargement unique dans le `lifespan` FastAPI ;
  - tests : non-régression des scores contre P6 (test le plus important du projet) ;
  - CI/CD : le service télécharge le dépôt HF à une révision figée (`model_revision.txt`)
    **au démarrage**, pas au build (William, 22/11/2026) : l'image GHCR est publique et ne
    doit contenir aucune donnée ; un Hub injoignable ou un fichier altéré empêche le
    démarrage (échec visible).
  - déploiement (#29, William, 22/11/2026) : le SDK Docker des Spaces étant payant, le
    Space est en SDK **Gradio** ; son `app.py` lance l'API FastAPI (uvicorn, port 7860).
    Le Space reconstruit l'environnement : même code (paquet installé depuis le tag) et
    mêmes versions (`requirements.txt` exporté de `uv.lock`), mais pas la même image que
    GHCR. L'image Docker reste construite, scannée, attestée et publiée à chaque release,
    prête pour un hébergeur Docker.
    **Dépôt privé** (William, 22/11/2026) : l'échantillon de clients vient des données
    Kaggle Home Credit, dont le règlement interdit la redistribution ; téléchargement
    authentifié par le secret `HF_TOKEN`, déjà nécessaire au déploiement des Spaces ;
  - étape 4 : point de départ mesuré ; une version ONNX se branchera au même endroit ;
  - soutenance : MLflow reste la source de vérité de la traçabilité, pas un runtime.
- **Indicateurs de la fiche** : scripts API (modèle géré sans erreur) ; Dockerfile (ne
  copie que le nécessaire).
- **Question d'oral probable** : « Tu as versionné ton modèle dans MLflow en P6 : pourquoi
  ne pas le servir avec MLflow, et comment garantis-tu que c'est le même modèle ? »

### ADR-003 — Sécurité de l'API

- **Contexte** : API exposée publiquement sur un Space Hugging Face ; l'appelant est un
  système interne (Crédit Express), pas des particuliers ; la mission demande de sécuriser
  l'API et le pipeline (secrets, validation d'entrée — couverte par l'ADR-001). P5 utilisait
  un JWT complet (utilisateurs en base, Argon2, Bearer).
- **Options** :
  1. Aucune authentification — démo la plus simple, mais modèle de crédit ouvert à tous et
     données de monitoring falsifiables.
  2. Clé d'API (`X-API-Key`) gardée dans les secrets du Space et de la CI ; `/health` et
     `/docs` publics — adapté à un appel entre systèmes, rotation sans redéploiement, pas
     d'identité par utilisateur.
  3. JWT / OAuth2 comme P5 — identité et expiration, mais base d'utilisateurs et flux de
     connexion sans objet pour un appel machine.
- **Recommandation** : option 2.
- **Choix** : **option 2** (William, 21/11/2026).
- **Conséquences** :
  - code : dépendance FastAPI comparant la clé en temps constant (`secrets.compare_digest`),
    401 normalisée ;
  - tests : clé absente, fausse, correcte ;
  - CI/CD : secret `API_KEY` poussé dans les secrets du Space au déploiement ;
  - monitoring : les 401 comptent dans le taux d'erreur ;
  - soutenance : en vraie production, passerelle (mTLS ou OAuth2 client-credentials),
    rotation des clés, limitation de débit.
- **Routes de documentation publiques** (`/docs`, `/openapi.json`) — décision de William
  (22/11/2026), maintenue **à des fins de démonstration pour la soutenance** :
  - contrepartie assumée : le schéma OpenAPI expose le contrat que le 401 protège sur
    `/predict` (122 noms de features, catégories acceptées, plages des règles métier,
    client d'exemple synthétique) ; aucun score ni donnée client n'est accessible sans clé ;
  - pourquoi : la démo imposée (« une requête type à l'API déployée et sa réponse ») se fait
    depuis Swagger, sans outillage côté évaluatrice, et la documentation des routes est un
    indicateur de la fiche ;
  - en vraie production : `/docs` et `/openapi.json` derrière la clé ou la passerelle
    (`FastAPI(docs_url=None, openapi_url=None)` en production, ou une dépendance de
    sécurité sur ces routes), le contrat étant remis à Crédit Express hors bande.
- **Indicateurs de la fiche** : scripts API (erreurs appréhendées, routes documentées) ;
  tests (pertinence).
- **Question d'oral probable** : « Ton API de crédit est publique : qu'est-ce qui empêche
  quelqu'un de l'interroger, et pourquoi ne pas avoir repris le JWT de P5 ? »

### ADR-004 — Stockage des données de production

- **Contexte** : il faut stocker au minimum appels, entrées, sorties et temps d'exécution
  pour l'analyse de dérive, et fournir des captures de la solution de stockage. Un Space HF
  gratuit perd son disque à chaque redémarrage ou redéploiement (donc à chaque push sur
  main). La mission cite PostgreSQL et Elasticsearch, et accepte un PoC local.
- **Options** :
  1. PostgreSQL managé externe (Neon, région UE), écriture en tâche de fond + logs JSON sur
     stdout — persistant, interrogeable en SQL, captures parlantes, même stack que P5 ;
     dépendance externe et secret `DATABASE_URL`.
  2. Dataset Hugging Face privé alimenté par paquets Parquet — gratuit et versionné, mais
     pas interrogeable en direct, pertes possibles au redémarrage, captures pauvres.
  3. Stockage local dans le conteneur + simulation locale — le plus simple, mais données
     perdues à chaque déploiement.
- **Recommandation** : option 1, avec trois règles : une panne de la base ne casse jamais
  une prédiction (repli sur stdout + compteur d'échecs), écriture en arrière-plan, schéma
  versionné par migrations.
- **Choix** : **option 1** (William, 21/11/2026).
- **Contenu proposé** (à valider par William dans #16) : horodatage, `request_id`, version
  du modèle (`manifest.json`), les 122 features (JSONB), avertissements hors bornes, score,
  décision, seuil, latence totale, temps d'inférence, code HTTP et type d'erreur ;
  `SK_ID_CURR` uniquement haché (minimisation RGPD) ; rétention à fixer (ex. 90 jours).
- **Conséquences** :
  - code : SQLAlchemy + Alembic, tâche de fond, repli sur stdout ;
  - tests : écriture réussie ; panne de la base sans effet sur la réponse ;
  - CI/CD : secret `DATABASE_URL` ; PostgreSQL éphémère en service pendant les tests ;
  - drift : le notebook lit directement la table ;
  - soutenance : PostgreSQL plutôt qu'Elasticsearch (volume modeste, requêtes analytiques
    simples, une stack de moins) ; choix RGPD.
- **Indicateurs de la fiche** : captures du stockage (adéquation aux exigences du
  monitoring ; stratégie définie et documentée).
- **Décisions de William dans #16 (22/11/2026)** : tout tracer (traçabilité, entrées,
  sorties, performance, erreurs, source) ; fenêtre glissante de **30 jours** ; archivage
  quotidien des lignes expirées (Parquet dans un dataset HF privé), **démonstratif** :
  archives non conservées après le projet ; chiffrement de colonnes évoqué à l'oral sans
  implémentation ; projet Neon en **région UE (Francfort)** ; colonne `source`
  (`api`, `ui-demo`, `ci`). `SK_ID_CURR` pseudonymisé (HMAC). Détail : `docs/monitoring.md`.
- **Question d'oral probable** : « Ta base de logs tombe une heure : que se passe-t-il pour
  Crédit Express, et que perds-tu pour le monitoring ? »

### ADR-005 — Analyse du drift, dashboard et hébergement

- **Contexte** : livrables attendus : notebook d'analyse du drift (visualisation et
  interprétation) et tableau de bord de monitoring (scores, latence, temps d'inférence) ;
  l'étape 3 demande une analyse automatique des données stockées (dérive, taux d'erreur,
  latence anormale). Référence : jeu d'entraînement de P6 ; données de production dans
  Neon (ADR-004). P5 a déjà démontré un Grafana provisionné.
- **Dérive** : Evidently dans tous les cas (outil cité, rapports HTML interactifs, tests
  statistiques par feature et dérive des prédictions). NannyML (estimation de performance
  sans cible) écarté : plus lourd à justifier pour un gain limité ici.
- **Options pour le dashboard** :
  1. Streamlit sur un second Space HF, lecture seule sur Neon, rapport Evidently intégré,
     workflow GitHub Actions planifié qui relance l'analyse — une seule stack Python, outil
     suggéré, démo en ligne ; un Space de plus et des graphiques à coder.
  2. Grafana (Cloud gratuit ou local) sur Neon — séries temporelles et alertes natives,
     mais dérive à précalculer, redite de P5, stack de plus.
  3. Notebook seul — minimum de l'énoncé, rien à montrer en production, pas
     d'automatisation.
- **Recommandation** : option 1.
- **Choix** : **option 1** (William, 21/11/2026).
- **Conséquences** :
  - code : un module d'analyse partagé par le notebook, le job planifié et le dashboard
    (même calcul partout) ;
  - CI/CD : workflow planifié, déploiement du second Space, secret `DATABASE_URL_RO`
    (compte en lecture seule) ;
  - monitoring : les seuils d'alerte (part 👤 de #17) sont affichés dans le dashboard ;
  - soutenance : démo du dashboard en ligne sur le trafic simulé.
- **Indicateurs de la fiche** : analyse du data drift (visualisation présente ;
  interprétation).
- **Révision (William, 22/11/2026, #16)** : le dashboard devient un **onglet de l'app
  Gradio du Space de l'API** (Gradio monté sur FastAPI, #40), et non un second Space
  Streamlit : un compte gratuit n'héberge que 2 Spaces ZeroGPU, réservés au SDK Gradio, et le
  SDK Docker est payant. Lecture sur Neon inchangée ; analyse planifiée inchangée.
- **Question d'oral probable** : « Ton rapport Evidently dit que 30 % des features ont
  dérivé : est-ce grave, et comment le sais-tu sans cible en production ? »

### ADR-006 — Protocole de mesure des performances

- **Contexte** : l'étape 4 demande de partir des données de monitoring réelles, de
  profiler, d'optimiser (code, ONNX Runtime, matériel) et de démontrer le gain sans
  régression. Un Space HF gratuit tourne sur CPU partagé (mesures bruitées) ; en P6,
  l'inférence LightGBM prend < 10 ms pour un appel complet d'environ 22 ms ; les champs à
  journaliser doivent être fixés avant le lot v0.3.0.
- **Options** :
  1. Mesures sur le Space seulement — conditions réelles, mais comparaisons fragiles et
     non répétables.
  2. Banc local seulement (`docker run --cpus=2`, script de charge, cProfile) —
     reproductible, mais ce n'est pas la production.
  3. Les deux : banc local pour décider (même scénario pour chaque version : montée en
     température, 1 000 requêtes, p50/p95/p99, profilage), Space pour confirmer
     (`latency_ms`, `inference_ms` avant/après déploiement).
- **Recommandation** : option 3.
- **Choix** : **option 3** (William, 21/11/2026).
- **Conséquences** :
  - code : chronométrage par étape dans l'API (validation, préparation, inférence,
    sérialisation), journalisé dès v0.3.0 ; script de banc versionné dans `bench/` ;
  - tests : la non-régression des scores (ADR-002) garde chaque optimisation, avec une
    tolérance définie pour ONNX ;
  - rapport : tableau avant/après issu du banc, confirmé par les percentiles du Space ;
    le Space (SDK Gradio, #29) ne fait pas tourner l'image Docker du banc : mêmes versions
    de bibliothèques, mais système et matériel différents, d'où la confirmation séparée ;
  - soutenance : pourquoi un p95 plutôt qu'une moyenne, pourquoi ne pas comparer des
    mesures prises sur CPU partagé.
- **Indicateurs** : mission, étape 4 (gain démontré, absence de régression,
  configuration justifiée).
- **Question d'oral probable** : « Ton gain de 40 % a été mesuré sur ta machine : qu'est-ce
  qui me prouve qu'il existe en production ? »

### ADR-007 — Explicabilité locale et équité

- **Contexte** :
  - devant un refus, Crédit Express doit pouvoir dire au client pourquoi ;
  - le modèle de P6 utilise `CODE_GENDER`, le sexe du demandeur, un critère protégé ;
  - 79 de ses 122 features (65 %) sont des combinaisons OpenFE (`autoFE_f_*`) sans sens
    métier direct ;
  - l'importance globale (gain) existe déjà dans les avertissements, mais elle ne dit rien
    d'un client en particulier.
- **Options** :
  1. Route dédiée `POST /predict/explain` : même entrée, même clé, journalisée. Le contrat
     de `/predict` reste inchangé et le coût n'est payé qu'à la demande.
  2. Champ `explanation` dans chaque réponse de `/predict` : modifie un contrat validé et
     alourdit chaque appel.
  3. Calcul dans l'interface, directement sur le modèle : contourne l'API, et rien n'est
     journalisé.
- **Choix** : **option 1** (William, 22/11/2026), avec le TreeSHAP natif de LightGBM.
  - Il est exact : `base + Σ contributions = logit(score)`.
  - Il prend environ 2 ms et n'ajoute aucune dépendance (pas de bibliothèque `shap`).
- **Politique d'équité (William)** : les attributs protégés sont déclarés dans le code
  (`api/fairness.py`), avec leur justification. On ne peut pas les déduire des artefacts :
  la sensibilité est une notion juridique.
  - `CODE_GENDER` : sexe, critère protégé, qui ne peut fonder une décision de crédit
    (C. pénal art. 225-1).
  - C'est une question de **non-discrimination**, pas de vie privée : le sexe n'est pas
    une donnée de l'art. 9 du RGPD.
  - L'interface affiche un badge « critère protégé (non-discrimination) » et la mention
    « combinaison calculée » sur les `autoFE_*`.
  - Un test vérifie que chaque attribut déclaré existe dans `features.json`.
- **Constat** : pour le client 100038 (refusé, 60,4 %), la première contribution est
  `CODE_GENDER = M` (+0,136 log-odds). Le badge rend le problème visible ; il ne le règle
  pas.
- **Limites assumées** :
  - l'explication décrit le modèle, pas la causalité ;
  - une `autoFE_*` peut agir comme proxy d'un critère protégé sans qu'on le voie ;
  - modifier une feature brute dans l'interface ne recalcule pas les `autoFE_*`.
- **Pistes, hors périmètre** :
  - réentraîner sans `CODE_GENDER` et mesurer l'écart de performance et de taux
    d'acceptation par sexe (parité démographique, égalité des chances) ;
  - auditer les formules OpenFE pour repérer les proxies ;
  - écrire des libellés métier pour les features lisibles.
- **Question d'oral probable** : « Ton modèle refuse le client 100038 d'abord parce que
  c'est un homme. Tu le mets en production quand même ? »

