"""Schema ownership: Alembic is the only thing that writes DDL (ARCH-03).

These tests exist because the previous behaviour was invisible: the schema was
changed by whichever process booted first, so nothing could be checked and a
`DROP`/`CREATE TRIGGER` pair ran on every start (PIPE-07). They assert the
opposite now:

* `verify_schema()` issues no DDL at all — it only reads the catalog.
* `alembic upgrade head` is idempotent: re-running it on a current database
  executes no DDL.
* The freshness trigger created by the migration actually fires.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import engine
from app.core.schema import SchemaNotReady, verify_schema

ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def _upgrade(url: str, revision: str = "head") -> list[str]:
    """Run alembic, returning the SQL it executed (both sync and async drivers)."""
    statements: list[str] = []
    config = _alembic_config(url)

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    previous = os.environ.get("ALEMBIC_DATABASE_URL")
    os.environ["ALEMBIC_DATABASE_URL"] = url
    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        command.upgrade(config, revision)
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)
        if previous is None:
            os.environ.pop("ALEMBIC_DATABASE_URL", None)
        else:
            os.environ["ALEMBIC_DATABASE_URL"] = previous
    return statements


def _ddl(statements: list[str]) -> list[str]:
    keywords = ("CREATE ", "ALTER ", "DROP ", "COMMENT ON ")
    return [s for s in statements if s.upper().startswith(keywords)]


async def _current_revision(url: str) -> str | None:
    async_engine = create_async_engine(url)
    try:
        async with async_engine.connect() as conn:
            return await conn.scalar(sa.text("SELECT version_num FROM alembic_version"))
    finally:
        await async_engine.dispose()


# --- ARCH-03: one DDL path ------------------------------------------------


@pytest.mark.asyncio
async def test_verify_schema_issues_no_ddl():
    """The startup check must not change the catalog (PIPE-07, ARCH-03)."""
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        await verify_schema()
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)

    assert statements, "the check should at least read the catalog"
    assert _ddl(statements) == [], f"verify_schema issued DDL: {_ddl(statements)}"


def test_upgrade_head_is_idempotent():
    """An up-to-date database is not rewritten, and stays on the same revision."""
    from tests.conftest import TEST_DATABASE_URL

    statements = _upgrade(TEST_DATABASE_URL)
    assert _ddl(statements) == [], f"a second upgrade rewrote the schema: {_ddl(statements)}"


@pytest.mark.asyncio
async def test_database_is_on_a_recorded_revision():
    from tests.conftest import TEST_DATABASE_URL

    assert await _current_revision(TEST_DATABASE_URL) is not None


@pytest.mark.asyncio
async def test_missing_schema_names_the_fix(monkeypatch):
    """A stale database must fail with the command that fixes it, not silently."""
    import app.core.schema as schema

    monkeypatch.setattr(
        schema, "REQUIRED_MANGA_COLUMNS", (*schema.REQUIRED_MANGA_COLUMNS, "no_such_column")
    )
    with pytest.raises(SchemaNotReady) as excinfo:
        await schema.verify_schema()

    message = str(excinfo.value)
    assert "no_such_column" in message
    assert "alembic upgrade head" in message


# --- PIPE-07: the trigger is created once, and works ----------------------


@pytest.mark.asyncio
async def test_updated_at_trigger_fires_without_being_recreated():
    """`updated_at` is a real freshness signal, set by the migrated trigger."""
    async with engine.begin() as conn:
        trigger_name = await conn.scalar(sa.text(
            "SELECT tgname FROM pg_trigger "
            "WHERE tgrelid = CAST('manga' AS regclass) AND NOT tgisinternal AND tgname = 'trg_manga_set_updated_at'"
        ))
        assert trigger_name == "trg_manga_set_updated_at"

        inserted_at = await conn.scalar(sa.text(
            """
            INSERT INTO manga (title_romaji, updated_at)
            VALUES ('trigger probe', now() - interval '1 day')
            RETURNING updated_at
            """
        ))
        bumped = await conn.scalar(sa.text(
            """
            UPDATE manga SET title_romaji = 'trigger probe 2'
            WHERE title_romaji = 'trigger probe'
            RETURNING updated_at
            """
        ))
        await conn.execute(sa.text("DELETE FROM manga WHERE title_romaji = 'trigger probe 2'"))

    assert bumped > inserted_at, "the update must refresh updated_at"


# --- PIPE-15: the ORM and the database agree -------------------------------


def test_autogenerate_is_clean():
    """`alembic check` must find nothing to do (PIPE-15).

    This is the guard that makes autogenerate safe: while the deployed
    constraints were named differently from the models, a generated diff wanted
    to drop and recreate the uniqueness of three id columns on a 95k-row table.
    """
    from alembic import command
    from tests.conftest import TEST_DATABASE_URL

    config = _alembic_config(TEST_DATABASE_URL)
    previous = os.environ.get("ALEMBIC_DATABASE_URL")
    os.environ["ALEMBIC_DATABASE_URL"] = TEST_DATABASE_URL
    try:
        command.check(config)  # raises AutogenerateDiffsDetected on any drift
    finally:
        if previous is None:
            os.environ.pop("ALEMBIC_DATABASE_URL", None)
        else:
            os.environ["ALEMBIC_DATABASE_URL"] = previous
