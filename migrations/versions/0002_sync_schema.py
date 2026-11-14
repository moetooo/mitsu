"""Sync schema: the columns, tables, indexes and trigger the sync job owns.

Until this revision the same statements ran from `app/sync/schema.py` on *every*
application start and from `app/ingestion/ingest.py` on every ingestion run:

* `DROP TRIGGER IF EXISTS trg_manga_set_updated_at ON manga` followed by a
  `CREATE TRIGGER` (PIPE-07) — a `DROP`/`CREATE` pair takes `ACCESS EXCLUSIVE`
  on the largest table in the database and does it on every boot, so live
  readers queue behind a table nobody was actually changing.
* `ALTER TABLE manga ADD COLUMN IF NOT EXISTS ...` (ARCH-03) — two different
  runtime paths adding overlapping columns, neither of them recorded anywhere,
  so there was no way to tell what schema a database was actually on.

Now it happens once, here. Everything is guarded so the revision is a no-op on a
database that already reached this state by the old paths, and a real upgrade on
one that did not.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations.helpers import (
    add_column_if_missing,
    column_exists,
    constraint_exists,
    index_exists,
    trigger_exists,
)

revision = "0002_sync_schema"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

# The genre evidence available offline for rows written before is_nsfw existed.
BACKFILL_BATCH_SIZE = 5000

BACKFILL_SQL = f"""
WITH batch AS (
    SELECT id FROM manga
    WHERE is_nsfw = false
      AND genres IS NOT NULL
      AND genres && ARRAY['Hentai', 'Erotica']
    LIMIT {BACKFILL_BATCH_SIZE}
)
UPDATE manga m SET is_nsfw = true FROM batch WHERE m.id = batch.id
"""


def _ensure_legacy_id_columns() -> None:
    """The three external ids, each unique on its own (ARCH-01's shape)."""
    if add_column_if_missing("manga", "mal_id", "INTEGER"):
        op.execute("ALTER TABLE manga ADD CONSTRAINT manga_mal_id_key UNIQUE (mal_id)")
    if add_column_if_missing("manga", "mangadex_id", "VARCHAR"):
        op.execute("ALTER TABLE manga ADD CONSTRAINT manga_mangadex_id_key UNIQUE (mangadex_id)")
    # MangaDex-only titles have no AniList id; a NOT NULL here would reject them.
    op.execute("ALTER TABLE manga ALTER COLUMN anilist_id DROP NOT NULL")


def _ensure_sync_columns() -> None:
    let_column_be_nsfw = add_column_if_missing(
        "manga", "is_nsfw", "BOOLEAN NOT NULL", default="false"
    )
    add_column_if_missing("manga", "source_updated_at", "TIMESTAMPTZ")
    add_column_if_missing("manga", "last_synced_at", "TIMESTAMPTZ")
    add_column_if_missing("manga", "sync_source", "VARCHAR(32)")
    add_column_if_missing("manga", "similarities_computed_at", "TIMESTAMPTZ")

    add_column_if_missing("sync_state", "progress_at", "TIMESTAMPTZ")
    add_column_if_missing("sync_state", "page_total", "INTEGER")

    if let_column_be_nsfw:
        # The flag has a real default now, so every pre-existing row would read
        # as safe. Seed it from the genre evidence the safety predicate used as
        # its fallback, in batches: rewriting a row rewrites its indexes too,
        # including the HNSW vector index.
        op.execute("SET statement_timeout = '120s'")
        total = 0
        while True:
            changed = op.get_bind().execute(sa.text(BACKFILL_SQL)).rowcount or 0
            total += changed
            if changed == 0:
                break
        op.execute("SET statement_timeout TO DEFAULT")
        print(f"0002_sync_schema: seeded is_nsfw for {total} legacy rows")


def _ensure_indexes() -> None:
    if not index_exists("idx_manga_external_ids_manga"):
        op.execute("CREATE INDEX idx_manga_external_ids_manga ON manga_external_ids (manga_id)")
    if not index_exists("idx_sync_runs_started"):
        op.execute("CREATE INDEX idx_sync_runs_started ON sync_runs (started_at DESC)")
    if not index_exists("idx_sync_runs_status"):
        op.execute("CREATE INDEX idx_sync_runs_status ON sync_runs (status, started_at DESC)")


def _ensure_updated_at_trigger() -> None:
    """Create the freshness trigger once, instead of dropping it on every boot."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION mitsu_set_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    if not trigger_exists("manga", "trg_manga_set_updated_at"):
        op.execute(
            """
            CREATE TRIGGER trg_manga_set_updated_at
            BEFORE UPDATE ON manga
            FOR EACH ROW EXECUTE FUNCTION mitsu_set_updated_at()
            """
        )


def upgrade() -> None:
    _ensure_legacy_id_columns()
    _ensure_sync_columns()
    _ensure_indexes()
    _ensure_updated_at_trigger()


def downgrade() -> None:
    # Destructive on purpose and never run against a populated deployment: the
    # sync job and the safety predicate both require these columns.
    op.execute("DROP TRIGGER IF EXISTS trg_manga_set_updated_at ON manga")
    op.execute("DROP FUNCTION IF EXISTS mitsu_set_updated_at()")
    op.execute("DROP INDEX IF EXISTS idx_sync_runs_status")
    op.execute("DROP INDEX IF EXISTS idx_sync_runs_started")
    op.execute("DROP INDEX IF EXISTS idx_manga_external_ids_manga")
    for column in ("progress_at", "page_total"):
        if column_exists("sync_state", column):
            op.execute(f"ALTER TABLE sync_state DROP COLUMN {column}")
    for column in (
        "similarities_computed_at",
        "sync_source",
        "last_synced_at",
        "source_updated_at",
        "is_nsfw",
    ):
        if column_exists("manga", column):
            op.execute(f"ALTER TABLE manga DROP COLUMN {column}")
    if constraint_exists("manga", "manga_mangadex_id_key"):
        op.execute("ALTER TABLE manga DROP CONSTRAINT manga_mangadex_id_key")
        op.execute("ALTER TABLE manga DROP COLUMN mangadex_id")
    if constraint_exists("manga", "manga_mal_id_key"):
        op.execute("ALTER TABLE manga DROP CONSTRAINT manga_mal_id_key")
        op.execute("ALTER TABLE manga DROP COLUMN mal_id")
