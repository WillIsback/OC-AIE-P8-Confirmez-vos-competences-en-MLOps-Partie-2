# Confirmez vos compétences en MLOps (Partie 2/2)

Mise en production et monitoring du modèle de scoring crédit Home Credit (OC AI Engineer P8)

- **Démo en ligne** : https://willisback-credit-scoring-api.hf.space/ (interface,
  [docs/ui](docs/ui/README.md)) · API : `/docs`
- Documentation : [API](docs/api.md) · [journalisation, dérive et dashboard](docs/monitoring.md) ·
  [notebook de dérive](notebooks/README.md) ·
  [CI/CD](docs/cicd.md) · [image Docker](docs/docker.md) · [décisions](docs/spec.md)

## Démarrage rapide

```bash
cp .env.example .env
uv sync
uv run pytest -m "not integration"
uv run uvicorn credit_scoring.api.app:app --reload
docker build -t credit-scoring . && docker run --rm -p 8000:8000 --env-file .env credit-scoring
```

## Monitoring

```bash
# Dashboard : onglet « Monitoring » de l'interface (base de DATABASE_URL)
DATABASE_URL=… API_KEY=… uv run uvicorn credit_scoring.api.app:app   # → http://127.0.0.1:8000/
# Analyse de dérive (sous-projet analysis/, Evidently exige pandas < 3)
uv sync --project analysis
DATABASE_URL=… HF_TOKEN=… uv run --project analysis python scripts/drift_job.py --window 7d
DATABASE_URL=… HF_TOKEN=… uv run --project analysis jupyter nbconvert --execute --to notebook \
    --inplace notebooks/analyse_drift.ipynb
```

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md) (workflow par lots de version, gates de CI,
release) et le [board](https://github.com/users/WillIsback/projects/4).

## Licence

MIT — William Derue.
