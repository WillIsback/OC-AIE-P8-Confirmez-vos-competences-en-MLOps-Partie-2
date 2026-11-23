"""Politique d'équité : attributs protégés que l'explication signale (#44, ADR-007).

La sensibilité est juridique et ne se déduit pas des artefacts : elle est déclarée ici.
Un test vérifie que chaque attribut déclaré existe dans `features.json`.
"""

from __future__ import annotations

SENSITIVE_FEATURES: dict[str, str] = {
    "CODE_GENDER": (
        "sexe : critère protégé, ne peut fonder une décision de crédit (C. pénal art. 225-1)"
    ),
}

DERIVED_PREFIX = "autoFE_"
