"""Seuils d'alerte du monitoring (#17, #18), affichés dans l'onglet Monitoring.

Valeurs de départ proposées par l'agent : **à fixer par William** (part 👤 de #17), avec
l'action décidée pour chacun (surveiller, ajuster, réentraîner).
"""

from __future__ import annotations

THRESHOLDS: dict[str, float] = {
    # Part des 122 features en dérive au-delà de laquelle on alerte (Evidently : 0,5 par défaut).
    "drift_share_alert": 0.3,  # à fixer par William
    # Distance de Wasserstein normalisée du score prob_default (seuil Evidently : 0,1).
    "score_drift_alert": 0.1,  # à fixer par William
    # Part d'appels en erreur (4xx/5xx) sur la fenêtre.
    "error_rate_alert": 0.05,  # à fixer par William
    # Latence p95 des appels réussis, en millisecondes.
    "latency_p95_ms_alert": 200.0,  # à fixer par William
}
