"""Application FastAPI."""

from fastapi import FastAPI

from credit_scoring import __version__

app = FastAPI(
    title="Confirmez vos compétences en MLOps (Partie 2/2)",
    version=__version__,
    description=(
        "Mise en production et monitoring du modèle de scoring crédit Home Credit "
        "(OC AI Engineer P8)"
    ),
)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Sonde de vivacité : état et version déployée."""
    return {"status": "ok", "version": __version__}
