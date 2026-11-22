# Confirmez vos compétences en MLOps (Partie 2/2)

Mise en production et monitoring du modèle de scoring crédit Home Credit (OC AI Engineer P8)

- **Démo en ligne** : https://willisback-credit-scoring-api.hf.space/ (interface,
  [docs/ui](docs/ui/README.md)) · API : `/docs`
- Documentation : [API](docs/api.md) · [journalisation](docs/monitoring.md) ·
  [CI/CD](docs/cicd.md) · [image Docker](docs/docker.md) · [décisions](docs/spec.md)

## Démarrage rapide

```bash
cp .env.example .env
uv sync
uv run pytest -m "not integration"
uv run uvicorn credit_scoring.api.app:app --reload
docker build -t credit-scoring . && docker run --rm -p 8000:8000 --env-file .env credit-scoring
```

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md) (workflow par lots de version, gates de CI,
release) et le [board](https://github.com/users/WillIsback/projects/4).

## Licence

MIT — William Derue.
