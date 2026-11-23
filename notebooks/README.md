# Notebooks

## `analyse_drift.ipynb` — analyse du data drift (#17)

Compare les appels de production (`prediction_logs`, `source = 'api'`, statut 200) à
l'échantillon de référence du train de P6, avec le module partagé
`credit_scoring.monitoring.drift` (Evidently), le même que le job planifié et l'onglet
Monitoring du Space.

```bash
# Sous-projet analysis/ : Evidently 0.7.23 exige pandas < 3
DATABASE_URL=… HF_TOKEN=… uv run --project analysis jupyter nbconvert --execute \
    --to notebook --inplace notebooks/analyse_drift.ipynb
```

Variables facultatives : `DRIFT_REFERENCE` (Parquet local au lieu du dataset HF privé),
`DRIFT_WINDOW_DAYS` (7 par défaut), `MODEL_DIR` (`artifacts/` par défaut). Le rapport
Evidently interactif est écrit dans `reports/drift-report.html` (non versionné).

La version versionnée a été exécutée sur une base locale alimentée par
`scripts/simulate_traffic.py` (1 500 clients du jeu de test, contre l'application locale) ;
elle sera réexécutée sur Neon après la simulation contre le Space. Elle ne contient que des
agrégats. Les sections 5 et 6 (interprétation, seuils et action) sont la part de William.
