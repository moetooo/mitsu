"""Test configuration.

Tests never touch the developer database. Before `app.config` is imported,
`DATABASE_URL` is redirected to a dedicated test database: the schema is built
once per session by running the real migrations (`alembic upgrade head`), and
every test starts from empty tables.

Tests that need a populated catalog are marked `requires_catalog`; they skip when
the test database is empty instead of asserting against whatever happens to be
in the developer's database. Point `MITSU_TEST_DATABASE_URL` at a disposable
copy of a real catalog (for example a restored dump) to run them locally:

    createdb -T mangamind mitsu_catalog
    MITSU_TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5433/mitsu_catalog pytest

A database supplied that way is never truncated by the suite.
"""

from __future__ import annotations

import asyncio
import math
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# app.config loads .env on import; load it here first so the test URL is derived
# from the same DATABASE_URL the application would use.
load_dotenv()

_DEFAULT_DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/mangamind"


def _test_database_url() -> str:
    explicit = os.environ.get("MITSU_TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("DATABASE_URL") or _DEFAULT_DATABASE_URL
    root, _, name = base.rpartition("/")
    name = name.split("?", 1)[0]
    if name.endswith("_test"):
        return base
    return f"{root}/{name}_test"


TEST_DATABASE_URL = _test_database_url()
# A prepared catalog (MITSU_TEST_DATABASE_URL) is shared and must not be wiped
# after every test; the auto-created database is owned by the suite.
OWNS_TEST_DATABASE = not os.environ.get("MITSU_TEST_DATABASE_URL")

# These must be set before app.config/app.db are imported anywhere.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# Keep the test cache out of the developer's Redis keyspace. Only a dedicated
# db index is ever flushed (see cleanup_connections).
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
REDIS_IS_ISOLATED = (urlparse(os.environ["REDIS_URL"]).path.lstrip("/") or "0") == "15"

from app.config import settings  # noqa: E402  (import after env redirect)
from app.db import AsyncSessionLocal, engine  # noqa: E402
from app.db_models import Manga  # noqa: E402
from app.services.cache import redis_client  # noqa: E402
import app.db_models  # noqa: E402,F401  (registers the tables the migrations create)

# Truncated between tests, children first via CASCADE.
_APP_TABLES = (
    "manga_external_ids",
    "recommendations_edges",
    "discovery_queue",
    "sync_runs",
    "sync_api_usage",
    "sync_state",
    "sync_settings",
    "manga",
)


def _server_url() -> str:
    root, _, _ = TEST_DATABASE_URL.rpartition("/")
    return f"{root}/postgres"


def _database_name() -> str:
    return TEST_DATABASE_URL.rpartition("/")[2].split("?", 1)[0]


def _bootstrap_database() -> None:
    """Create the test database and bring it to `alembic upgrade head`.

    The suite builds its schema through the same migrations a deployment runs,
    so a revision that is broken for a real database fails here first instead of
    being noticed after a release.

    The three phases are separate `asyncio.run` calls on purpose: Alembic's own
    environment calls `asyncio.run` internally, and nesting it inside a running
    loop raises RuntimeError.
    """

    async def create_database() -> None:
        admin = create_async_engine(_server_url(), isolation_level="AUTOCOMMIT")
        try:
            async with admin.connect() as conn:
                exists = await conn.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": _database_name()},
                )
                if not exists:
                    await conn.execute(text(f'CREATE DATABASE "{_database_name()}"'))
        finally:
            await admin.dispose()

        target = create_async_engine(TEST_DATABASE_URL)
        try:
            async with target.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        finally:
            await target.dispose()

    async def truncate() -> None:
        if not OWNS_TEST_DATABASE:
            return
        target = create_async_engine(TEST_DATABASE_URL)
        try:
            async with target.begin() as conn:
                # A previous crashed run must not leak rows into this one.
                await conn.execute(
                    text(f"TRUNCATE {', '.join(_APP_TABLES)} RESTART IDENTITY CASCADE")
                )
        finally:
            await target.dispose()

    asyncio.run(create_database())
    # Migrations own the schema. `upgrade head` is idempotent, so a database
    # created by an older run is simply brought forward.
    _upgrade_to_head(TEST_DATABASE_URL)
    asyncio.run(truncate())


def _upgrade_to_head(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    previous = os.environ.get("ALEMBIC_DATABASE_URL")
    os.environ["ALEMBIC_DATABASE_URL"] = url
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("ALEMBIC_DATABASE_URL", None)
        else:
            os.environ["ALEMBIC_DATABASE_URL"] = previous


@lru_cache(maxsize=1)
def catalog_available() -> bool:
    """True when the test database contains at least one catalog row."""

    async def run() -> int:
        target = create_async_engine(TEST_DATABASE_URL)
        try:
            async with target.connect() as conn:
                return int(await conn.scalar(text("SELECT count(*) FROM manga")) or 0)
        finally:
            await target.dispose()

    return asyncio.run(run()) > 0


@pytest.fixture(scope="session", autouse=True)
def test_database() -> str:
    _bootstrap_database()
    return TEST_DATABASE_URL


def pytest_runtest_setup(item):
    if "requires_catalog" in item.keywords and not catalog_available():
        pytest.skip(
            "requires a populated catalog; set MITSU_TEST_DATABASE_URL to a "
            "prepared test database to run this test"
        )


@pytest.fixture(autouse=True)
def permissive_sync_guardrails(monkeypatch):
    """Keep unrelated tests deterministic; guardrail tests opt back in."""
    monkeypatch.setattr(settings, "SYNC_DAILY_RUN_LIMIT", 10_000)
    monkeypatch.setattr(settings, "SYNC_MANUAL_COOLDOWN_SECONDS", 0)
    # The test database has its own usage table, so a real exhausted budget can
    # no longer leak in; keep the caps generous anyway.
    monkeypatch.setattr(settings, "ANILIST_DAILY_REQUEST_BUDGET", 10_000)
    monkeypatch.setattr(settings, "MANGADEX_DAILY_REQUEST_BUDGET", 10_000)
    monkeypatch.setattr(settings, "SYNC_HARD_DAILY_CEILING", 10_000)
    # Admin is fail-closed, so tests authenticate by default instead of relying
    # on open access. Tests that exercise the signed-out path override this.
    monkeypatch.setattr(settings, "SYNC_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(settings, "SYNC_ADMIN_USERNAME", "")
    monkeypatch.setattr(settings, "SYNC_ADMIN_PASSWORD", "")
    monkeypatch.setattr(settings, "SYNC_ADMIN_SESSION_SECRET", "")


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "test-admin-token"}


@pytest.fixture(autouse=True)
async def cleanup_connections():
    yield
    # Every test starts from empty tables and its own connection pool. A
    # prepared catalog is shared, so it is left intact.
    if OWNS_TEST_DATABASE:
        async with engine.begin() as conn:
            await conn.execute(
                text(f"TRUNCATE {', '.join(_APP_TABLES)} RESTART IDENTITY CASCADE")
            )
    if REDIS_IS_ISOLATED:
        # Cached responses would otherwise leak between tests (and between
        # runs), which reads as random ordering rather than a cache hit.
        try:
            await redis_client.flushdb()
        except Exception:
            pass
    # `redis_client` is a module-level connection pool, so it binds to whichever
    # event loop first used it -- which is test one's loop. Every later test then
    # failed with `RuntimeError: Event loop is closed`, and because `get_cached`
    # swallows Redis errors and returns None, the symptom was a silent cache miss
    # rather than an error. Closing the pool forces the next test to reconnect
    # inside its own loop.
    try:
        await redis_client.aclose()
    except Exception:
        pass
    await engine.dispose()


# ---------------------------------------------------------------------------
# A small, deliberately hostile catalogue.
#
# Shared by the tests that assert whole-endpoint behaviour (safety pagination,
# trending). The NSFW row is the most popular *and* highest-scored title on
# purpose: a missing safety filter surfaces it at rank 1 rather than nowhere.
# ---------------------------------------------------------------------------

TARGET_TITLE = "Pagination Probe"
NEIGHBOURS = 16


def embedding_for_seed(seed: int) -> list[float]:
    """Distinct, strictly ordered similarity to the target row.

    Every neighbour sits at a slightly larger angle from the target, so the ANN
    ordering is total: without distinct distances the vector search has ties and
    page boundaries are non-deterministic, which would make those tests flaky
    rather than meaningful.
    """
    theta = 0.05 * seed
    vector = [0.0] * 384
    vector[0] = math.cos(theta)
    vector[1] = math.sin(theta)
    return vector


def catalog_row(title: str, seed: int, **overrides) -> Manga:


    values = dict(
        title_english=title,
        title_romaji=title,
        synopsis=f"{title} synopsis for retrieval.",
        genres=["Action"],
        tags=[{"name": "Action", "rank": 100}],
        status="FINISHED",
        start_year=2021,
        average_score=80,
        popularity=100 + seed,
        cover_image_url=f"https://example.invalid/{seed}.jpg",
        embedding=embedding_for_seed(seed),
        is_nsfw=False,
    )
    values.update(overrides)
    return Manga(**values)


@pytest.fixture
async def seeded_catalog():
    async with AsyncSessionLocal() as session:
        rows = [catalog_row(TARGET_TITLE, 0)]
        rows += [catalog_row(f"Probe Neighbour {index}", index) for index in range(1, NEIGHBOURS + 1)]
        rows.append(
            catalog_row(
                "Explicit Probe",
                99,
                genres=["Hentai"],
                tags=[{"name": "Hentai", "rank": 100}],
                average_score=95,
                popularity=9999,
                is_nsfw=True,
            )
        )
        session.add_all(rows)
        await session.commit()
    return True
