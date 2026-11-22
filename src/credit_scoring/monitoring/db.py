"""Connexion à la base de production et migrations Alembic."""

from __future__ import annotations

import os
from pathlib import Path

import sqlalchemy as sa

MIGRATIONS = Path(__file__).with_name("migrations")


def database_url() -> str | None:
    """`DATABASE_URL`, ou `None` si absente ou vide (journalisation sur stdout seulement)."""
    return os.environ.get("DATABASE_URL") or None


def make_engine(url: str) -> sa.Engine:
    """Moteur SQLAlchemy ; Postgres via psycopg 3, compatible avec le pooler Neon (PgBouncer)."""
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
        # PgBouncer en mode transaction ne garde pas les requêtes préparées côté serveur.
        # connect_timeout : une base injoignable ne bloque pas le thread d'écriture indéfiniment.
        return sa.create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"prepare_threshold": None, "connect_timeout": 10},
        )
    return sa.create_engine(url, pool_pre_ping=True)


def run_migrations(url: str, revision: str = "head", *, downgrade: bool = False) -> None:
    """`alembic upgrade|downgrade <revision>` sur `url`, sans fichier alembic.ini."""
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["url"] = url
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


def main() -> None:
    """`python -m credit_scoring.monitoring.db` : migre la base de `DATABASE_URL` (job deploy)."""
    url = database_url()
    if not url:
        raise SystemExit("DATABASE_URL absente : aucune base à migrer")
    run_migrations(url)
    print("Migrations appliquées (head).")


if __name__ == "__main__":  # pragma: no cover - point d'entrée CLI
    main()
