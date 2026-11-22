# Tests

```bash
uv run pytest -m "not integration"     # unitaires (CI des PR), modèle synthétique, sans réseau
uv run pytest -m integration           # vrais artefacts (artifacts/ téléchargés au préalable)
```

## Cas critiques (choix de William, 22/11/2026)

| Famille | Fichier | Ce qu'elle évite |
|---|---|---|
| **Non-régression du modèle** | `test_non_regression.py`, `test_api_integration.py` | servir un score différent de celui du modèle validé en P6 : écart 0,0 et décisions identiques sur 1 000 clients figés, tolérance 1e-9 ; sans elle, des clients seraient mal notés sans qu'aucun autre test ne le voie |
| **Contrat d'entrée (422)** | `test_api_predict.py` | scorer en silence une donnée invalide : champ manquant ou inconnu, mauvais type, `null` interdit, NaN, catégorie inconnue (« m » encodé −1), règles métier |
| **Valeurs limites** | `test_api_predict.py` | rejeter à tort un client légitime à la borne (heure 0 et 23, foyer d'une personne, borne du train sans avertissement) |

Autres familles : intégrité des artefacts (refus de démarrer), sécurité (401 avant 422,
clé en temps constant), décision au seuil exact, téléchargement à révision figée.

## Couverture

Lignes **et branches** (`--cov-branch`), seuil 80 %, rapport dans le résumé du job CI.
Valeur actuelle : **100 %**. Ce que ce chiffre **ne garantit pas** :

- la couverture mesure l'**exécution**, pas la vérification : une ligne traversée par un
  test sans `assert` compte comme couverte ;
- les tests `integration` (dont la non-régression) ne tournent pas dans la CI des PR : ils
  tournent sur `main`, dans l'environnement `ml-models` qui détient `HF_TOKEN` (#15) ;
- `scripts/` (export P6, générateur du schéma) n'est pas mesuré ;
- l'image Docker n'est pas couverte : le test de fumée de la CI s'en charge (le bug
  `libgomp` de la v0.1.0 était passé malgré 100 %).
