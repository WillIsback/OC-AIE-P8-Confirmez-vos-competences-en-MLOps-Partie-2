"""Environnement Alembic : URL fournie par `run_migrations` ou `DATABASE_URL`."""

from __future__ import annotations

from alembic import context

from credit_scoring.monitoring.db import database_url, make_engine
from credit_scoring.monitoring.schema import metadata

url = context.config.attributes.get("url") or database_url()
if not url:
    raise RuntimeError("DATABASE_URL absente : aucune base à migrer")

engine = make_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
