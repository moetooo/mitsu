from __future__ import annotations

import logging

from sqlalchemy import text

from ..db import Base, engine
from ..db_models import MangaExternalId, SyncSetting  # noqa: F401 - imported for metadata
from ..services.safety import backfill_is_nsfw

logger = logging.getLogger("mitsu.sync.schema")

_SYNC_COLUMNS = (
    ("source_updated_at", "TIMESTAMPTZ"),
    ("last_synced_at", "TIMESTAMPTZ"),
    ("sync_source", "VARCHAR(32)"),
    ("similarities_computed_at", "TIMESTAMPTZ"),
    # Persisted safety signal. New rows get it from provider metadata; existing
    # rows are backfilled from genre evidence the first time the column appears.
    ("is_nsfw", "BOOLEAN NOT NULL DEFAULT false"),
)


async def ensure_sync_schema() -> None:
    """Create/upgrade the small amount of schema the sync job needs.

    `manga` already exists in production and is not recreated here. Columns are
    added with `IF NOT EXISTS`, which is safe to run repeatedly and on every app
    start. New tables are created through SQLAlchemy metadata so their model
    definitions stay the source of truth.
    """
    async with engine.begin() as conn:
        is_nsfw_existed = await conn.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'manga' AND column_name = 'is_nsfw')"
        ))

        for column, sql_type in _SYNC_COLUMNS:
            await conn.execute(
                text(f"ALTER TABLE manga ADD COLUMN IF NOT EXISTS {column} {sql_type}")
            )

        # One-time, idempotent seed of the stored flag for rows that predate it.
        # Only genre evidence is available offline, so this is the fallback the
        # safety predicate would have applied anyway.
        if not is_nsfw_existed:
            seeded = await backfill_is_nsfw(conn)
            logger.info("Backfilled is_nsfw for %s rows from genre evidence.", seeded)

        # New tables only; create_all checks existence first.
        await conn.run_sync(Base.metadata.create_all)

        # Additive columns for the backfill progress bar.
        await conn.execute(text(
            "ALTER TABLE sync_state ADD COLUMN IF NOT EXISTS progress_at TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE sync_state ADD COLUMN IF NOT EXISTS page_total INTEGER"
        ))

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_manga_external_ids_manga "
            "ON manga_external_ids (manga_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sync_runs_started "
            "ON sync_runs (started_at DESC)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sync_runs_status "
            "ON sync_runs (status, started_at DESC)"
        ))

        # updated_at is currently insert-only. Make it a real freshness signal
        # without touching application write paths.
        await conn.execute(text(
            """
            CREATE OR REPLACE FUNCTION mitsu_set_updated_at()
            RETURNS trigger AS $$
            BEGIN
                NEW.updated_at = now();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        ))
        await conn.execute(text("DROP TRIGGER IF EXISTS trg_manga_set_updated_at ON manga"))
        await conn.execute(text(
            """
            CREATE TRIGGER trg_manga_set_updated_at
            BEFORE UPDATE ON manga
            FOR EACH ROW EXECUTE FUNCTION mitsu_set_updated_at()
            """
        ))

    logger.info("Sync schema is ready.")


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
