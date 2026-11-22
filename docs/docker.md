# Image Docker

Construction et lancement locaux :

```bash
docker build -t credit-scoring .
docker run --rm -p 8000:8000 -e API_KEY=dev -e HF_TOKEN=<jeton lecture> credit-scoring
```

Au premier démarrage, le service télécharge les artefacts du modèle depuis le dépôt privé
du Hub, à la révision figée de `model_revision.txt`, puis vérifie leurs empreintes
(ADR-002, option A). L'image publiée sur GHCR est publique et ne contient aucune donnée.

## Choix

- multi-étapes : `uv` et les outils de build restent dans l'étape `builder` ;
- Python 3.12, comme la CI (`.python-version`) : Dependabot ne propose plus de saut de
  version mineure de l'image de base ;
- `libgomp1` : runtime OpenMP requis par LightGBM ; pip retiré (CVE de ses copies
  embarquées, inutile à l'exécution) ;
- utilisateur `app` (uid 1000, celui qu'attendent les Spaces Hugging Face) ; le code et
  les dépendances appartiennent à root, seul `/app/artifacts` est inscriptible ;
- `HEALTHCHECK` sur `/health`, délai de démarrage de 60 s (téléchargement inclus).

## Mesures (22/11/2026, machine de dev)

| Mesure | Valeur |
|---|---|
| Taille de l'image | 509 Mo (scipy 139 Mo, pandas 81 Mo, numpy 66 Mo, LightGBM 10 Mo) |
| Démarrage à froid, téléchargement compris | 2,3 s |
| Redémarrage, artefacts présents | 0,85 s |
| Mémoire au repos | 130 Mio |
| Scan Trivy (HIGH, CRITICAL, corrigeables) | aucune vulnérabilité |

scipy, la plus grosse dépendance, n'est utilisée que par LightGBM : piste pour le rapport
d'optimisation (v0.4.0).
