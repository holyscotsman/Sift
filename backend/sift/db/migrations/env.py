"""Alembic environment for Sift.

The DB URL is resolved from Sift settings so migrations target the same SQLite
snapshot the app uses; the ``alembic.ini`` value is only a static fallback.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from sift.config import load_settings
from sift.db.models import Base
from sift.db.session import _resolve_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    # Same target the app uses: SQLite path by default, or a Postgres URL when
    # SIFT_DATABASE__URL / DATABASE_URL is set.
    return _resolve_url(load_settings().database.target())


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,  # SQLite needs batch mode for ALTER
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
