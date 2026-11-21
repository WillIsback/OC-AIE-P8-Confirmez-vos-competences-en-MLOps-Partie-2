# AGENTS.md — Confirmez vos compétences en MLOps (Partie 2/2)

Mise en production et monitoring du modèle de scoring crédit Home Credit (OC AI Engineer P8)

## Contexte du projet

Projet 8 du parcours OpenClassrooms **AI Engineer** : mise en production du modèle de
scoring crédit Home Credit développé au projet 6 (« Prêt à Dépenser », département Crédit
Express). Brief complet : [`docs/brief.md`](docs/brief.md). Soutenance visée : 11/01/2027,
évaluatrice dans le rôle de Chloé Dubois, Lead Data Scientist.

- **Base** : modèle `home-credit-serving` v2 de P6 (encodeur ordinal + LightGBM sur
  122 features + seuil métier 0,5348), base SQLite des 48 744 clients du jeu de test.
- **Standards** : ceux de P5 (FastAPI, Pydantic, Docker, CI/CD GitHub Actions, monitoring).
- **Déploiement** : Space Hugging Face (Docker), alimenté par la CI/CD.
- **Livrables** : historique Git, API, Dockerfile, tests, pipeline CI/CD, notebook de drift
  + dashboard de monitoring, captures du stockage des données de production, README,
  rapport d'optimisation.
- **Projet d'apprentissage** : orchestré par le skill `oc-project`. Chaque PR de lot vers
  `main` passe un oral blanc (`oc-oral-blanc`) avant la fusion ; les parts marquées 👤
  dans les issues sont faites par William, pas par l'agent.
- Jamais versionnés : `.oc/` (sources OpenClassrooms, état, carnet), `exercices/`,
  `data/`, artefacts MLflow.

## Workflow (obligatoire)

Skills `semver-batch-workflow` et `semver-repo-setup`
(https://github.com/WillIsback/agent-skills). Résumé :

- Une issue typée par changement (`.github/ISSUE_TEMPLATE`) ; epics = issues parentes
  `type:epic`, user stories = sous-issues.
- Lots de version (milestones datés) traités dans l'ordre **patch → minor → major**.
- Branche de lot `<type>/<version>` ; une sous-branche par issue `<type>/<version>-<tâche>`,
  fusionnée dans la branche de lot par `<type>: merge <type>/<version>-<tâche> (#N)`.
- **Jamais de commit ni de merge direct sur `main`** : une PR par lot, avec `Closes #N`
  pour chaque issue.
- Board : https://github.com/users/WillIsback/projects/4 — tenir à jour la
  colonne Status (En cours, Intégré au lot) avec `gh project item-edit`.
- Conventional Commits ; `feat` → minor, `fix`/`perf` → patch, `!` → major.
- Preflight uniquement si la CI de PR ne couvre pas un job de la release.
- Toujours minimiser le temps de CI/CD : ne rien construire deux fois, cacher, filtrer
  par chemins, garder le lourd hors PR.

## Commandes

```bash
uv sync
uv run pytest -m "not integration"
uv run uvicorn credit_scoring.api.app:app --reload
docker build -t credit-scoring . && docker run --rm -p 8000:8000 --env-file .env credit-scoring
```

## Conventions

- Les tests unitaires n'appellent jamais de réseau : simuler. Les tests réels sont
  marqués `integration`.
- Explorer le code avec CodeGraph (`codegraph_explore`) avant grep/lecture.
- Textes, docs, commits et PR en français.
