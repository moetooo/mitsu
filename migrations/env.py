"""Alembic environment for Mitsu.

Migrations run through the same async driver the application uses (asyncpg), so
`alembic upgrade head` against a copy of production behaves like the app does.

Two ways to point at a database:

* `ALEMBIC_DATABASE_URL` (wins when set, used by the test suite)
* otherwise `app.config.settings.DATABASE_URL`
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.db import Base
import app.db_models  # noqa: F401 - registers every table on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


#: Indexes autogenerate cannot compare, because PostgreSQL normalises their
#: expressions. `idx_manga_search_blob_trgm` is declared as
#: `lower(coalesce(title_english, '') || ...)` and reflected back as
#: `lower(COALESCE(title_english, ''::text) || ...)`, so `alembic check` reports a
#: change to an index that is in fact identical. The index is still created by
#: migration 0006; `tests/test_search_index.py` asserts the `/search` statement
#: actually uses it, which is the property that matters.
UNCOMPARABLE_INDEXES = {"idx_manga_search_blob_trgm"}


def _include_object(object_, name, type_, reflected, compare_to):
    if type_ == "index" and name in UNCOMPARABLE_INDEXES:
        return False
    return True


def _database_url() -> str:
    override = os.getenv("ALEMBIC_DATABASE_URL")
    if override:
        return override
    from app.config import settings

    return settings.DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
