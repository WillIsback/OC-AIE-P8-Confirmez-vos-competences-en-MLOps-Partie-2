# syntax=docker/dockerfile:1
# Image de l'API : dépendances installées dans une couche dédiée (cache), code
# du projet ensuite, image finale sans uv ni outils de build, utilisateur non root.
FROM ghcr.io/astral-sh/uv:0.13.9 AS uv

FROM python:3.12-slim AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Couche dépendances : invalidée seulement si pyproject.toml / uv.lock changent.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# Pas de .git dans le contexte : version fournie par la release (tag vX.Y.Z).
ARG VERSION=0.0.0
RUN --mount=type=cache,target=/root/.cache/uv \
    SETUPTOOLS_SCM_PRETEND_VERSION="${VERSION#v}" uv sync --locked --no-dev --no-editable

# Même version mineure que la CI (.python-version) : on sert ce qu'on a testé.
FROM python:3.12-slim
# Correctifs de sécurité Debian publiés après l'image de base (sinon le scan Trivy
# de la release bloque sur des CVE déjà corrigées en amont).
# libgomp1 : runtime OpenMP requis par LightGBM (absent de l'image slim).
# pip est retiré : l'environnement arrive tout prêt du builder, et pip embarque ses propres
# copies de msgpack, urllib3 et setuptools, signalées par Trivy (release v0.1.0 bloquée).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --no-input pip \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/artifacts && chown app:app /app/artifacts
COPY --from=builder /app/.venv /app/.venv
# Code et dépendances restent à root (lecture seule pour app) ; seul artifacts/ est inscriptible.
# Révision figée du dépôt modèle (40 caractères) : seul lien entre ce code et ses artefacts,
# téléchargés au démarrage (ADR-002, option A) — l'image publique ne contient aucune donnée.
COPY model_revision.txt /app/model_revision.txt
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    MODEL_DIR=/app/artifacts \
    MODEL_REVISION_FILE=/app/model_revision.txt
USER app
WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
CMD ["uvicorn", "credit_scoring.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
