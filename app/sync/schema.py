"""Schema readiness checks and the data backfills the sync job owns.

Schema *changes* live in `migrations/` (Alembic) and nowhere else. This module
used to issue `ALTER TABLE`, `create_all` and a `DROP`/`CREATE TRIGGER` pair on
every application start, which meant the deployed schema depended on which
process happened to boot first and could not be inspected or rolled back
(ARCH-03, PIPE-07).

What is left here is deliberately read-only: `verify_schema()` looks, and
`seed_external_ids()` writes rows, not structure.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import engine

logger = logging.getLogger("mitsu.sync.schema")

# Columns the sync job and the safety predicate require on `manga`.
REQUIRED_MANGA_COLUMNS = (
    "id",
    "anilist_id",
    "mal_id",
    "mangadex_id",
    "title_romaji",
    "genres",
    "tags",
    "embedding",
    "is_nsfw",
    "source_updated_at",
    "last_synced_at",
    "sync_source",
    "similarities_computed_at",
    "updated_at",
)

REQUIRED_TABLES = (
    "manga",
    "manga_external_ids",
    "sync_state",
    "sync_settings",
    "sync_runs",
    "sync_api_usage",
    "discovery_queue",
    "recommendations_edges",
)

REQUIRED_INDEXES = (
    "idx_manga_embedding_hnsw",
    "idx_manga_external_ids_manga",
)


class SchemaNotReady(RuntimeError):
    """The database is behind the migrations this build expects."""


async def verify_schema(conn: AsyncConnection | None = None) -> None:
    """Raise `SchemaNotReady` if the database is missing anything we need.

    Read-only by design. The fix for a failure is always `alembic upgrade head`,
    which the message says.
    """
    owns_connection = conn is None
    context = engine.connect() if owns_connection else None
    if owns_connection:
        conn = await context.__aenter__()
    try:
        tables = set(
            (await conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            ))).scalars().all()
        )
        columns = set(
            (await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'manga'"
            ))).scalars().all()
        )
        indexes = set(
            (await conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
            ))).scalars().all()
        )
    finally:
        if owns_connection:
            await context.__aexit__(None, None, None)

    missing_tables = [name for name in REQUIRED_TABLES if name not in tables]
    missing_columns = [name for name in REQUIRED_MANGA_COLUMNS if name not in columns]
    missing_indexes = [name for name in REQUIRED_INDEXES if name not in indexes]

    if missing_tables or missing_columns or missing_indexes:
        problems = []
        if missing_tables:
            problems.append(f"tables: {', '.join(missing_tables)}")
        if missing_columns:
            problems.append(f"manga.{', manga.'.join(missing_columns)}")
        if missing_indexes:
            problems.append(f"indexes: {', '.join(missing_indexes)}")
        raise SchemaNotReady(
            "database schema is behind this build (missing "
            + "; ".join(problems)
            + "). Run `alembic upgrade head` against this database."
        )


async def seed_external_ids() -> int:
    """Backfill the mapping table from the three legacy ID columns.

    Idempotent. Existing mappings are never moved; this only inserts missing
    `(source, external_id)` pairs.
    """
    statements = (
        ("anilist", "anilist_id::text", "anilist_id IS NOT NULL"),
        ("mal", "mal_id::text", "mal_id IS NOT NULL"),
        ("mangadex", "mangadex_id::text", "mangadex_id IS NOT NULL"),
    )
    inserted = 0
    async with engine.begin() as conn:
        for source, expr, predicate in statements:
            result = await conn.execute(text(
                f"""
                INSERT INTO manga_external_ids (manga_id, source, external_id)
                SELECT id, '{source}', {expr}
                FROM manga
                WHERE {predicate}
                ON CONFLICT (source, external_id) DO NOTHING
                """
            ))
            inserted += result.rowcount or 0
    logger.info("Seeded %d external-ID mappings.", inserted)
    return inserted
