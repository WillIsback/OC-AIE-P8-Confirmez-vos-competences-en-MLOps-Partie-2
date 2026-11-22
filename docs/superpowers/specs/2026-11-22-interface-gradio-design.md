# Design — Interface Gradio de démonstration

- **Date** : 2026-11-22
- **Lot** : v0.3.0 (`feat`), branche `feat/0.3.0-interface-gradio`
- **Statut** : approche validée par William (option A) ; document en relecture

## 1. Intention

Le Space Hugging Face simule la production de « Prêt à Dépenser ». Aujourd'hui, sa racine
affiche une page HTML statique : pour voir un score, il faut passer par Swagger et coller une
clé. On veut une interface graphique qui montre, en quelques clics, ce que fait le service :
choisir un client, obtenir sa probabilité de défaut et la décision, et voir le contrat de
l'API à l'œuvre (avertissement hors des bornes, refus 422).

C'est un **Space de démonstration** : l'interface porte la clé d'API côté serveur, le
visiteur n'a rien à saisir (décision de William : pas de danger, aucune donnée réelle
exposée au-delà de l'échantillon de démo déjà servi par `/predict/{sk_id_curr}`).

Adaptation de l'interface de P5 (`app/ui/`), pas une copie : P5 était un service séparé
avec connexion utilisateur ; ici l'interface vit dans l'application, sans connexion.

## 2. Objectifs, non-objectifs, anti-objectifs

**Objectifs**
- Scorer un des 1 000 clients de démo (recherche par identifiant ou tirage au hasard).
- Afficher probabilité, seuil métier, décision et avertissements (avec rang et part
  d'importance).
- Démontrer le contrat : modifier quelques valeurs lisibles pour provoquer un
  avertissement ou un 422, et lire l'erreur en clair.
- Faire passer chaque score par la vraie route `/predict` : même validation, et le trafic
  de démo sera journalisé par #16 (même lot) **avec sa source** (`ui-demo`, D8), donc
  visible du monitoring sans fausser l'analyse du drift.

**Non-objectifs**
- Saisie libre des 122 features ; explication locale (SHAP) ; historique des scores ;
  comptes utilisateurs ; limitation de débit.

**Anti-objectifs** (échec même si « ça marche »)
- Une interface qui appelle le modèle directement, en contournant `/predict` (trafic
  invisible du monitoring, validation contournée).
- Un « et si ? » présenté comme une analyse de sensibilité : les features `autoFE_f_*`
  (les plus importantes) ne sont **pas** recalculées quand on modifie une feature brute
  (limite vue à l'oral v0.2.2). L'interface le dit explicitement.
- Casser l'API existante (`/docs`, `/health`, `/predict`, test de fumée du déploiement) ou
  alourdir l'image Docker publique.

## 3. Approches considérées

| | Approche | Pour | Contre |
|---|---|---|---|
| **A (retenue)** | Gradio monté dans l'app FastAPI à `/` (`gr.mount_gradio_app`) ; appels internes à `/predict` | une seule app (Docker = Space) ; la démo suit le chemin de la prod ; ZeroGPU gère nativement le montage | Gradio dans le processus de l'API |
| B | `app.py` Gradio (`launch()`) avec l'API greffée | proche de la doc ZeroGPU | Gradio possède le serveur ; lifespan fragile ; app différente de l'image Docker |
| C | Second Space, client HTTP de l'API publique (comme P5) | séparation nette | consomme le 2ᵉ Space ZeroGPU gratuit, réservé au dashboard (ADR-005) ; 2ᵉ déploiement |

## 4. Décisions

| # | Sujet | Décision |
|---|---|---|
| D1 | Montage | `gr.mount_gradio_app(app, demo, path="/")` à la fin de `api/app.py`, **seulement si Gradio est installé** ; sinon la page HTML actuelle reste à `/`. La route `home()` n'est donc déclarée **que si Gradio est absent** (sinon elle masquerait l'interface). Les autres routes, déclarées avant le montage (`/docs`, `/openapi.json`, `/health`, `/predict…`), gardent la priorité. Appel par attribut, `gr.mount_gradio_app(...)`, jamais `from gradio import mount_gradio_app` : c'est l'attribut que `spaces` remplace (D6). |
| D2 | Appel de l'API | L'interface est un client HTTP de l'application elle-même : `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ui.internal")`, en-tête `X-API-Key` = `app.state.api_key`. Pas de réseau, mais middleware, validation et (bientôt) journalisation traversés. Gestionnaires Gradio `async`. |
| D3 | Données des clients | Liste des identifiants et valeurs de départ lues dans `app.state.demo_clients` (lecture seule, même processus) ; le **score** passe toujours par `/predict/{id}` ou `POST /predict`. |
| D4 | Clé | Côté serveur (`app.state.api_key`) ; jamais affichée, jamais renvoyée au navigateur. Événements Gradio en `api_visibility="private"` (pas d'API Gradio publique qui scorerait sans passer par l'interface) ; `run_history=False`. |
| D5 | Dépendance | Extra `ui = ["gradio==6.32.0"]` (même version que `sdk_version` du Space) ; dans le groupe `dev` pour les tests. Image Docker : sans l'extra (inchangée). Space : `uv export --extra ui`. |
| D6 | ZeroGPU | Le paquet `spaces` remplace `gr.mount_gradio_app` et y ajoute `ZeroGPUMiddleware` (startup report). Le `app.py` du Space garde `import spaces` en premier et la fonction `@spaces.GPU` déclarée, mais **ne enveloppe plus** l'app dans le middleware (il serait ajouté deux fois). |
| D8 | Source du trafic | Décision de William : le trafic de l'interface est **distingué** de la production. L'`ApiClient` envoie l'en-tête `X-Client: ui-demo` ; la journalisation de #16 l'enregistre dans une colonne `source` (`ui-demo`, sinon `api`). Le notebook de drift et le dashboard (v0.4.0) filtrent ou comparent les deux. Ordre dans le lot : **#16 d'abord**, puis l'interface. L'en-tête n'est pas une authentification (tout appelant peut l'envoyer) : il sert seulement à trier. |
| D7 | Thème | Repris de P5 : `gr.themes.Base`, gris neutres, un accent bleu, sans ombres, clair forcé ; pied de page Gradio masqué. Couleur de décision : vert « accordé », rouge « refusé ». |

## 5. Écran (une page, deux colonnes)

```
┌───────────────────────────────────────────────────────────────────────────┐
│ 🏦 Scoring crédit — Prêt à Dépenser            v0.3.0 · home-credit-serving v2 │
│ Démonstration : 1 000 clients du jeu de test. API : /docs                   │
├──────────────────────────────┬────────────────────────────────────────────┤
│ Client                       │ Résultat                                   │
│ [ SK_ID_CURR ▼ (recherche) ] │  REFUSÉ                                     │
│ [ 🎲 Client au hasard ]       │  Probabilité de défaut : 61,2 %            │
│                              │  ███████████████▏░░░░░░░  seuil 53,5 %     │
│ Valeurs modifiables          │                                            │
│  Montant du crédit  [ ... ]  │ Avertissements (hors des bornes du train)  │
│  Membres du foyer   [ ... ]  │  feature | valeur | min–max | rang | part  │
│  Heure de la demande[ ... ]  │                                            │
│  Type d'emploi      [ ▼  ]   │ Erreur 422 (si refus de l'API)             │
│  … (5 à 8 champs)            │  • CNT_FAM_MEMBERS : ≥ 1 attendu (reçu 0)  │
│ ⚠ Les features autoFE ne sont│                                            │
│   pas recalculées.           │                                            │
│ [ Scorer le client ] [Rétablir]│                                          │
└──────────────────────────────┴────────────────────────────────────────────┘
```

- Sélection d'un client → valeurs de départ chargées et **score immédiat** via
  `POST /predict/{sk_id_curr}`.
- « Scorer le client » après modification → `POST /predict` avec le client complet
  (122 features) dont les champs modifiés ; « Rétablir » recharge les valeurs d'origine.
- Champs modifiables : features **lisibles par un humain** et utiles pour démontrer le
  contrat, choisies parmi `ClientFeatures` (règles métier connues, ex. `AMT_CREDIT`,
  `CNT_FAM_MEMBERS`, `HOUR_APPR_PROCESS_START`, `OCCUPATION_TYPE`, un `FLAG_*`). Liste
  exacte et libellés français laissés au builder (5 à 8 champs, types cohérents avec le
  schéma : entier, décimal, liste pour les catégories).
- Les saisies hors règles **ne sont pas bloquées** par l'interface : c'est l'API qui
  refuse, et l'interface affiche son 422 en clair (champ, message, valeur reçue).
- Erreurs : 422 → liste lisible ; autre statut ou exception → bandeau « API
  indisponible (statut) ».
- Valeurs `null` (features nullables) : affichées vides, renvoyées `null`.

## 6. Code

| Fichier | Rôle |
|---|---|
| `src/credit_scoring/ui/__init__.py` | `mount_ui(app) -> None` (D1), importé paresseusement par `api/app.py` |
| `src/credit_scoring/ui/client.py` | `ApiClient` asynchrone (D2) : `predict_demo(id)`, `predict(features)` ; renvoie la réponse ou une `ApiError(status, details)` |
| `src/credit_scoring/ui/view.py` | formatage pur : pourcentage français, barre seuil/probabilité, tableau des avertissements, liste des erreurs 422 |
| `src/credit_scoring/ui/app.py` | `build_ui(client_factory, clients_provider) -> gr.Blocks` ; gestionnaires = fonctions de module testables sans Gradio lancé |

`scripts/deploy_space.py` : `--extra ui` dans `uv export`, `app.py` du Space sans
enveloppe `ZeroGPUMiddleware` (D6).

## 7. Tests et vérification

- Unitaires (sans réseau) : `ApiClient` sur l'app de test (fixture `api_artifacts`) : client
  de démo valide, client inconnu (404), corps modifié valide (200 + avertissement), règle
  violée (422 restitué), clé et en-tête `X-Client: ui-demo` envoyés ; `view` (formats) ; gestionnaires (sélection, tirage,
  modification, rétablir, erreur) ; `build_ui()` construit un `gr.Blocks` ; montage :
  `GET /` sert Gradio quand il est installé, `/health` et `/docs` inchangés.
- Le chemin « Gradio absent » (image Docker) est testé en simulant l'absence de
  l'import : la couverture reste à 100 % (pratique du projet ; le seuil bloquant de
  `pyproject.toml` reste à 80 %).
- Simulation ZeroGPU locale, **manuelle et hors CI** (comme v0.2.5 : `uv run --with
  spaces==0.53.0`, faux service ZeroGPU) : startup report reçu **une seule fois**,
  `/`, `/health`, `/predict` en 200. `spaces` n'entre dans aucune dépendance du projet.
- Recette : parcours dans un navigateur (Playwright) sur l'app locale puis sur le Space ;
  captures pour la soutenance (`docs/ui/`).

## 8. Documentation

`docs/api.md` (section interface), `README.md` (lien vers l'interface du Space),
`docs/cicd.md` (extra `ui` et ZeroGPU), `docs/docker.md` (image sans interface).

## 9. Laissé au builder

Liste exacte et libellés des champs modifiables ; mise en page fine ; formulation des
messages ; découpage des tests.
