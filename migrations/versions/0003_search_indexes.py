"""Search indexes: trigram title matching and the HNSW vector index.

These were previously built by `app/ingestion/ingest.py` (`init_db`) and by
`scripts/migrate_p3_indexes.py`, i.e. someone had to remember to run them, and
one of the two did `DROP INDEX IF EXISTS idx_manga_embedding` on every ingestion
run (PIPE-10).

Building an index on a populated catalog takes minutes, so this revision builds
them with `CONCURRENTLY` where possible. Alembic runs each revision inside a
transaction, and `CREATE INDEX CONCURRENTLY` cannot run in one, so the two heavy
indexes are built in an autocommit block.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations.helpers import index_exists

revision = "0003_search_indexes"
down_revision = "0002_sync_schema"
branch_labels = None
depends_on = None

TRGM_INDEXES = (
    ("idx_manga_title_english_trgm", "title_english"),
    ("idx_manga_title_romaji_trgm", "title_romaji"),
    ("idx_manga_title_native_trgm", "title_native"),
)

HNSW_INDEX = "idx_manga_embedding_hnsw"


def _build_concurrently(statements: tuple[str, ...]) -> None:
    """Build heavy indexes outside a transaction, without blocking writers."""
    connection = op.get_bind()
    connection.execute(sa.text("COMMIT"))
    for statement in statements:
        connection.execute(sa.text(statement))


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    statements: list[str] = []
    for name, column in TRGM_INDEXES:
        if not index_exists(name):
            statements.append(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON manga USING gin ({column} gin_trgm_ops)"
            )
    if not index_exists(HNSW_INDEX):
        statements.append(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {HNSW_INDEX} "
            "ON manga USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )

    if statements:
        _build_concurrently(tuple(statements))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("COMMIT"))
    for name in (HNSW_INDEX, *(name for name, _ in TRGM_INDEXES)):
        connection.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
