"""Track cover health in the database instead of guessing from the URL host.

MangaDex stopped serving covers to browsers (see `cover_unavailable_resolve.md`):
`uploads.mangadex.org` answers a browser-like image request with a JS challenge,
so every row pointing there renders `CoverFallback`. Until now that fact lived
only in a document and in URL substring matching, which means:

* there was no way to ask "how many covers are dead right now?";
* a repair could not be verified, because the old URL and the new URL look the
  same to every query (`cover_image_url IS NOT NULL` is true either way);
* a second provider dying (AniList) would have been invisible until users
  complained, because nothing records *when* a cover was last proven loadable.

Three columns, one index:

* `cover_status`  - `ok | dead | unverified`. The tracking column.
* `cover_source`  - `anilist | kitsu | mangadex | none`, so the preference order
  in `upsert`/`deduplicate` is checkable and a provider swap is measurable.
* `cover_checked_at` - when the status was last established. Without it a `dead`
  row is indistinguishable from a stale verdict.

The partial index serves the only cover-health query that scans: "which rows
still need checking" (`cover_status <> 'ok'`).

Backfill is host-derived and deliberately conservative:

* rows whose cover host is `uploads.mangadex.org` are marked `dead` with
  `cover_source='mangadex'` - measured 0/10 usable with browser headers, so this
  is a known fact, not a guess;
* rows on a host known to be browser-safe are marked `ok` with the matching
  source, because the probe (10/10 `image/*`) established the host, not the row;
* everything else stays `unverified` and is left for the verifier job.

`cover_status` is NOT NULL with a default so ingestion code that has not learned
about these columns yet keeps working.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations.helpers import add_column_if_missing, constraint_exists, index_exists

revision = "0007_cover_health"
down_revision = "0006_search_blob_index"
branch_labels = None
depends_on = None

PENDING_INDEX = "idx_manga_cover_status_pending"
STATUS_CHECK = "ck_manga_cover_status"
SOURCE_CHECK = "ck_manga_cover_source"

# Hosts proven to serve images to browser requests. Kept as a literal here on
# purpose: a migration must not change meaning when application config changes.
BROWSER_SAFE_HOSTS = ("s4.anilist.co", "media.kitsu.app")
DEAD_HOSTS = ("uploads.mangadex.org",)

# Rows per UPDATE. The API engine sets asyncpg `command_timeout` (20 s by
# default), which a single full-table UPDATE of ~96k rows exceeds; batching keeps
# every statement far below it and keeps the lock short.
BATCH = 5_000

BATCH_SQL = """
    UPDATE manga SET
        cover_status = CASE
            WHEN substring(cover_image_url from '^https?://([^/]+)') IN ({dead}) THEN 'dead'
            WHEN substring(cover_image_url from '^https?://([^/]+)') IN ({safe}) THEN 'ok'
            ELSE 'unverified'
        END,
        cover_source = CASE
            WHEN substring(cover_image_url from '^https?://([^/]+)') LIKE '%mangadex.org' THEN 'mangadex'
            WHEN substring(cover_image_url from '^https?://([^/]+)') LIKE '%anilist.co' THEN 'anilist'
            WHEN substring(cover_image_url from '^https?://([^/]+)') LIKE '%kitsu.app' THEN 'kitsu'
            WHEN cover_image_url IS NULL THEN 'none'
            ELSE cover_source
        END,
        cover_checked_at = now()
    WHERE cover_status = 'unverified' AND id >= :lo AND id < :hi
"""


def upgrade() -> None:
    add_column_if_missing(
        "manga", "cover_status", "VARCHAR(16) NOT NULL DEFAULT 'unverified'"
    )
    add_column_if_missing("manga", "cover_source", "VARCHAR(16)")
    add_column_if_missing("manga", "cover_checked_at", "TIMESTAMPTZ")

    if not constraint_exists("manga", STATUS_CHECK):
        op.execute(
            f"ALTER TABLE manga ADD CONSTRAINT {STATUS_CHECK} "
            "CHECK (cover_status IN ('ok', 'dead', 'unverified'))"
        )
    if not constraint_exists("manga", SOURCE_CHECK):
        op.execute(
            f"ALTER TABLE manga ADD CONSTRAINT {SOURCE_CHECK} "
            "CHECK (cover_source IS NULL OR cover_source IN "
            "('anilist', 'kitsu', 'mangadex', 'none'))"
        )

    if not index_exists(PENDING_INDEX):
        # `CONCURRENTLY` needs its own transaction; the catalog stays writable.
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY {PENDING_INDEX} "
                "ON manga (cover_checked_at) WHERE cover_status <> 'ok'"
            )

    # Gated on remaining work, not on "the column was just added": a retry after
    # a partial run must still classify rows, and a re-run on a fully classified
    # table must do nothing.
    pending = op.get_bind().execute(
        sa.text("SELECT count(*) FROM manga WHERE cover_status = 'unverified'")
    ).scalar()
    if not pending:
        print("0007_cover_health: nothing to classify")
        return

    dead = ", ".join(f"'{h}'" for h in DEAD_HOSTS)
    safe = ", ".join(f"'{h}'" for h in BROWSER_SAFE_HOSTS)
    stmt = sa.text(BATCH_SQL.format(dead=dead, safe=safe))

    lo, hi = op.get_bind().execute(
        sa.text("SELECT coalesce(min(id), 0), coalesce(max(id), 0) + 1 FROM manga")
    ).one()

    total = 0
    # autocommit_block puts each batch in its own transaction, so no single
    # statement can trip the client command timeout and the lock is released
    # between batches.
    with op.get_context().autocommit_block():
        for start in range(lo, hi, BATCH):
            result = op.get_bind().execute(
                stmt, {"lo": start, "hi": min(start + BATCH, hi)}
            )
            total += result.rowcount or 0
    print(f"0007_cover_health: classified {total} rows")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {PENDING_INDEX}")
    op.execute(f"ALTER TABLE manga DROP CONSTRAINT IF EXISTS {STATUS_CHECK}")
    op.execute(f"ALTER TABLE manga DROP CONSTRAINT IF EXISTS {SOURCE_CHECK}")
    op.execute("ALTER TABLE manga DROP COLUMN IF EXISTS cover_checked_at")
    op.execute("ALTER TABLE manga DROP COLUMN IF EXISTS cover_source")
    op.execute("ALTER TABLE manga DROP COLUMN IF EXISTS cover_status")
