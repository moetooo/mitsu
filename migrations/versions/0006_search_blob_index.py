"""One trigram index for everything `/search` matches on (API-08).

`/search` was a sequential scan. It ORed four predicates:

    title_english ILIKE '%q%' OR title_romaji ILIKE '%q%'
    OR title_native ILIKE '%q%'
    OR array_to_string(alternative_titles, ' ') ILIKE '%q%'

Three of the four columns already had a GIN trigram index (revision 0003), but an
OR can only use indexes when *every* branch is indexed, and the
`array_to_string` branch cannot be: PostgreSQL marks `array_to_string(anyarray,
text)` **STABLE** (element output functions may be stable), and an index
expression must be IMMUTABLE. So the planner scanned all 95,626 rows. Measured:
**270-390 ms warm**, 1,737 ms cold, for a jump box that is meant to answer on
keystroke.

Two pieces here:

1. `mitsu_alt_titles_text(text[])` — an IMMUTABLE wrapper over
   `array_to_string(..., ' ')`. For a `text[]` the conversion genuinely has no
   time or locale dependency (text output is immutable), so this is a correct
   declaration rather than a lie told to the planner.
2. `idx_manga_search_blob_trgm` — one GIN trigram index over the concatenation
   of the four sources, lower-cased, wrapped in a `CONCURRENTLY` build so the
   catalog stays writable. The same expression is defined once in
   `app/db_models.py` (`SEARCH_BLOB`) and used by `catalog.search_titles`, so the
   query and the index cannot drift apart.

Measured after: **3-37 ms**, `Bitmap Index Scan on idx_manga_search_blob_trgm`,
identical row sets for specific titles.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations.helpers import ensure_alt_titles_function, index_exists

revision = "0006_search_blob_index"
down_revision = "0005_format_type"
branch_labels = None
depends_on = None

FUNCTION_NAME = "mitsu_alt_titles_text"
INDEX_NAME = "idx_manga_search_blob_trgm"

#: Kept byte-identical to `SEARCH_BLOB` in `app/db_models.py`.
SEARCH_BLOB_SQL = (
    "lower(coalesce(title_english, '') || ' ' || coalesce(title_romaji, '') "
    "|| ' ' || coalesce(title_native, '') || ' ' "
    "|| coalesce(mitsu_alt_titles_text(alternative_titles), ''))"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    ensure_alt_titles_function()

    if index_exists(INDEX_NAME):
        return

    # `CREATE INDEX CONCURRENTLY` cannot run inside a transaction, and Alembic
    # runs each revision in one (revision 0003 does the same).
    connection = op.get_bind()
    connection.execute(sa.text("COMMIT"))
    connection.execute(
        sa.text(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
            f"ON manga USING gin ({SEARCH_BLOB_SQL} gin_trgm_ops)"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("COMMIT"))
    if index_exists(INDEX_NAME):
        connection.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}"))
    connection.execute(sa.text(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}(text[])"))
