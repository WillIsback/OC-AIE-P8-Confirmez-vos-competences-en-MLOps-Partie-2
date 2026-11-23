"""Clients synthétiques au contrat réel (122 features), pour la dérive (#17)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from credit_scoring.api.features_schema import EXAMPLE_CLIENT, FEATURE_ORDER


def clients(
    n: int, categories: dict[str, dict[str, float]], seed: int = 0, shift: float = 0.0
) -> pd.DataFrame:
    """Numériques autour du client d'exemple (bruit), catégorielles tirées dans la liste."""
    rng = np.random.default_rng(seed)
    data: dict[str, Any] = {}
    for col in FEATURE_ORDER:
        if col in categories:
            data[col] = rng.choice(list(categories[col]), n)
        else:
            centre = float(EXAMPLE_CLIENT[col])
            scale = max(abs(centre) * 0.3, 1.0)
            data[col] = centre + scale * (shift + rng.normal(0, 1, n))
    return pd.DataFrame(data, columns=list(FEATURE_ORDER))
