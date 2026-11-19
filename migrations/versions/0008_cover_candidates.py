"""Ordered cover candidates, plus a log of what the resolver changed.

`cover_image_url` assumed one picture per row is either good or absent. MangaDex
disproved that (`cover_unavailable_resolve.md`): a stored URL can look valid and
be unloadable in a browser, and the only recovery the client had was to give up.
Two independent hosts means a dead provider is a fallback, not a broken card.

* `manga.cover_candidates` - `[{"source", "url", "variant"?}]`, best first.
  `cover_image_url` stays the denormalised first entry, so every existing filter
  (`IS NOT NULL`), partial index and API payload keeps working unchanged.
* `cover_repair_log` - one row per decided URL. `cover_status` is a snapshot that
  overwrites itself, so without this a repaired row and a row the run never
  reached are indistinguishable, and the previous URL (the only way to undo a bad
  write) is gone.

The backfill is pure SQL and costs no API calls: every row whose stored URL is
not on a blocked host already has one usable candidate, so it records that fact
instead of leaving the column empty and re-deriving it later.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations.helpers import add_column_if_missing, index_exists

revision = "0008_cover_candidates"
down_revision = "0007_cover_health"
branch_labels = None
depends_on = None

LOG_TABLE = "cover_repair_log"
LOG_MANGA_INDEX = "idx_cover_repair_log_manga"
LOG_CREATED_INDEX = "idx_cover_repair_log_created"

# Rows per UPDATE. The API engine sets asyncpg `command_timeout` (20 s), which a
# single ~96k-row UPDATE exceeds; per-batch statements stay far below it.
BATCH = 5_000

HOST_EXPR = "substring(cover_image_url from '^https?://([^/]+)')"

BACKFILL_SQL = f"""
    UPDATE manga SET cover_candidates = jsonb_build_array(
        jsonb_build_object(
            'source', CASE
                WHEN {HOST_EXPR} LIKE '%anilist.co' THEN 'anilist'
                WHEN {HOST_EXPR} LIKE '%kitsu.app' THEN 'kitsu'
                WHEN {HOST_EXPR} LIKE '%myanimelist.net' THEN 'mal'
                ELSE 'unknown'
            END,
            'url', cover_image_url
        )
    )
    WHERE cover_candidates = '[]'::jsonb
      AND cover_image_url IS NOT NULL
      AND cover_status <> 'dead'
      AND id >= :lo AND id < :hi
"""


def _table_exists(name: str) -> bool:
    return bool(
        op.get_bind().execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :n)"
            ),
            {"n": name},
        ).scalar()
    )


def upgrade() -> None:
    add_column_if_missing(
        "manga", "cover_candidates", "JSONB NOT NULL DEFAULT '[]'::jsonb"
    )

    if not _table_exists(LOG_TABLE):
        op.create_table(
            LOG_TABLE,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "manga_id",
                sa.Integer(),
                sa.ForeignKey("manga.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("from_url", sa.Text(), nullable=True),
            sa.Column("to_url", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=16), nullable=True),
            sa.Column("result", sa.String(length=16), nullable=False),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
    if not index_exists(LOG_MANGA_INDEX):
        op.create_index(LOG_MANGA_INDEX, LOG_TABLE, ["manga_id", "created_at"])
    if not index_exists(LOG_CREATED_INDEX):
        op.create_index(LOG_CREATED_INDEX, LOG_TABLE, ["created_at"])

    pending = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM manga WHERE cover_candidates = '[]'::jsonb "
            "AND cover_image_url IS NOT NULL AND cover_status <> 'dead'"
        )
    ).scalar()
    if not pending:
        print("0008_cover_candidates: nothing to backfill")
        return

    lo, hi = op.get_bind().execute(
        sa.text("SELECT coalesce(min(id), 0), coalesce(max(id), 0) + 1 FROM manga")
    ).one()

    total = 0
    # autocommit_block: each batch is its own transaction, so no statement trips
    # the client command timeout and the lock is released between batches.
    with op.get_context().autocommit_block():
        for start in range(lo, hi, BATCH):
            result = op.get_bind().execute(
                sa.text(BACKFILL_SQL),
                {"lo": start, "hi": min(start + BATCH, hi)},
            )
            total += result.rowcount or 0
    print(f"0008_cover_candidates: backfilled {total} rows")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {LOG_CREATED_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {LOG_MANGA_INDEX}")
    op.drop_table(LOG_TABLE)
    op.execute("ALTER TABLE manga DROP COLUMN IF EXISTS cover_candidates")
