"""Scoring crédit Home Credit : API, monitoring et optimisation (OC AI Engineer P8)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("credit-scoring")
except PackageNotFoundError:  # pragma: no cover - paquet non installé
    __version__ = "0.0.0"
