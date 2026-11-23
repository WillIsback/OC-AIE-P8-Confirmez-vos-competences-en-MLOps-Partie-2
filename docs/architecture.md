# Architecture — OC-AIE-P8

Décisions de référence : `docs/spec.md` (ADR-001 à ADR-007). Schéma mis à jour au lot
v0.4.0 : le dashboard est un onglet du Space de l'API (révisions de l'ADR-005), et non un
second Space Streamlit comme prévu aux specs.

## Composants

```mermaid
flowchart LR
  client["Système Crédit Express<br/>(appelant)"]
  subgraph space["Space HF (SDK Gradio, ZeroGPU) : FastAPI + Gradio monté à « / »"]
    auth["Contrôle de la clé d'API<br/>X-API-Key (ADR-003)"]
    valid["Validation Pydantic<br/>122 features : invalide → 422,<br/>inhabituel → avertissement (ADR-001)"]
    model["Modèle chargé une fois<br/>encodeur + LightGBM + seuil (ADR-002)<br/>contributions SHAP (ADR-007)"]
    demo[("Échantillon ~1 000 clients<br/>route /predict/{sk_id_curr}")]
    logger["Journalisation<br/>tâche de fond + stdout JSON (ADR-004)"]
    ui_score["Onglet Scoring<br/>POST /predict/explain (client interne)"]
    ui_mon["Onglet Monitoring<br/>indicateurs + dernière dérive"]
  end
  hub[("Hub HF : dépôt modèle privé<br/>artefacts + manifest.json")]
  ref[("Hub HF : dataset privé<br/>référence 20 000 lignes du train P6")]
  archive[("Hub HF : dataset privé<br/>archives Parquet (> 30 jours)")]
  neon[("PostgreSQL Neon (UE)<br/>prediction_logs, drift_reports")]
  job["GitHub Actions quotidien<br/>drift-analysis (Evidently, analysis/)"]
  purge["GitHub Actions quotidien<br/>archive-logs"]
  notebook["Notebook d'analyse du drift<br/>(analysis/)"]

  client -->|"POST /predict, /predict/explain"| auth --> valid --> model
  ui_score --> auth
  demo --> valid
  model --> logger -->|"INSERT"| neon
  hub -. "téléchargé au démarrage<br/>(révision figée)" .-> model
  neon -->|"lecture"| ui_mon
  neon --> job
  ref --> job
  job -->|"drift_reports"| neon
  neon --> purge --> archive
  neon --> notebook
  ref --> notebook
```

## Séquence du flux principal

```mermaid
sequenceDiagram
  autonumber
  participant C as Crédit Express
  participant A as API (FastAPI)
  participant M as Modèle (en mémoire)
  participant B as Tâche de fond
  participant DB as PostgreSQL Neon

  C->>A: POST /predict (X-API-Key, 122 features)
  alt clé absente ou fausse
    A-->>C: 401
  else entrée invalide (manquante, mauvais type, règle métier)
    A-->>C: 422 + détail des erreurs
  else entrée valide
    A->>A: avertissements hors bornes du train
    A->>M: features encodées
    M-->>A: prob_default
    A->>A: décision = prob_default ≥ seuil (0,5348)
    A-->>C: 200 {score, décision, seuil, avertissements, version}
    A-)B: enregistrement (entrées, sorties, temps par étape, statut)
    B->>DB: INSERT
    alt base indisponible
      B->>B: repli sur stdout JSON + compteur d'échecs
    end
  end
```

## Déploiement

```mermaid
flowchart LR
  dev["Push / PR"] --> gh["GitHub"]
  subgraph ci["GitHub Actions"]
    q["ci-code-quality<br/>ruff, mypy"]
    t["ci-test<br/>pytest + couverture<br/>PostgreSQL éphémère"]
    s["ci-security / CodeQL"]
    img["build de l'image Docker<br/>(artefacts du Hub HF)"]
    rel["release semver<br/>(au merge sur main)"]
    dep["déploiement des Spaces HF<br/>(si tests verts)"]
    cron["analyse de dérive planifiée"]
  end
  gh --> q & t & s
  t --> img --> rel --> dep
  dep --> api["Space « API »"]
  dep --> mon["Space « Monitoring »"]
  ghcr[("GHCR : image versionnée")]
  img --> ghcr
  cron --> mon
  secrets[["Secrets : HF_TOKEN, API_KEY,<br/>DATABASE_URL, DATABASE_URL_RO"]] -.-> dep
```
