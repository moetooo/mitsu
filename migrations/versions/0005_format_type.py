"""Store the publication format instead of re-deriving it on every query.

ARCH-05. `format_type` existed in three places and was stored in none:

* `infer_format_type(...)` — a Python classifier used for result payloads;
* `build_format_sql_condition(...)` — a ~120-line SQL predicate that re-ran the
  same classification against `title_native` character ranges, JSON tag
  containment, `site_url` substrings and `inferred_tags` on *every* filtered
  query, so a manhwa filter was a 30-term boolean expression over the largest
  table in the database;
* `RecommendationResult.format_type` — always `None` for database-backed rows,
  because there was no column to read.

The column is added here and backfilled with a SQL expression that mirrors
`app/services/format.py::infer_format_type` precedence exactly: explicit inferred
tags first, then Korean markers, then Chinese markers, then MANGA. The predicate
is copied rather than imported on purpose — a migration must not change meaning
when application code changes.

Existing rows are classified once here; rows written afterwards are classified in
`normalize.py` on insert and recomputed in `upsert._merge_into` when a later
source adds tag evidence.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations.helpers import add_column_if_missing, index_exists

revision = "0005_format_type"
down_revision = "0004_constraint_names"
branch_labels = None
depends_on = None

INDEX_NAME = "idx_manga_format_type"

# Korean evidence: Hangul in the native title, or a Korean/Webtoon marker. The
# character range is spelled out because a migration cannot import regexes.
HANGUL_RANGE = "[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]"
KANA_RANGE = "[\u3040-\u309f\u30a0-\u30ff]"
HANZI_RANGE = "[\u4e00-\u9fff]"

BACKFILL_SQL = f"""
UPDATE manga
SET format_type = CASE
    WHEN inferred_tags @> '[{{"slug": "manhwa"}}]' THEN 'MANHWA'
    WHEN inferred_tags @> '[{{"slug": "manhua"}}]' THEN 'MANHUA'
    WHEN inferred_tags @> '[{{"slug": "manga"}}]' THEN 'MANGA'
    WHEN title_native ~ '{HANGUL_RANGE}'
         OR genres @> ARRAY['Manhwa']
         OR tags::text LIKE '%Manhwa%'
         OR tags::text LIKE '%Webtoon%'
         OR tags::text LIKE '%Korean%'
         OR site_url ILIKE '%manhwa%' THEN 'MANHWA'
    WHEN genres @> ARRAY['Manhua']
         OR tags::text LIKE '%Manhua%'
         OR tags::text LIKE '%Chinese%'
         OR tags::text LIKE '%Ancient China%'
         OR site_url ILIKE '%manhua%'
         OR (
             title_native ~ '{HANZI_RANGE}'
             AND NOT title_native ~ '{KANA_RANGE}'
             AND NOT title_native ~ '{HANGUL_RANGE}'
             AND (tags::text LIKE '%Long Strip%' OR tags::text LIKE '%Full Color%')
         ) THEN 'MANHUA'
    ELSE 'MANGA'
END
WHERE format_type IS NULL
"""


def upgrade() -> None:
    added = add_column_if_missing("manga", "format_type", "VARCHAR(16)")
    if not index_exists(INDEX_NAME):
        op.execute(f"CREATE INDEX {INDEX_NAME} ON manga (format_type)")

    if added:
        # One pass over the catalog: this writes a new column and its index, not
        # the whole row, but the default 15s statement timeout is still tight on
        # a large table.
        op.execute("SET statement_timeout = '300s'")
        result = op.get_bind().execute(sa.text(BACKFILL_SQL))
        op.execute("SET statement_timeout TO DEFAULT")
        print(f"0005_format_type: classified {result.rowcount or 0} rows")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    op.execute("ALTER TABLE manga DROP COLUMN IF EXISTS format_type")
