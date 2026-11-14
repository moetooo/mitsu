"""Align the deployed constraints and indexes with what the models declare.

PIPE-15: the ORM and the database had drifted apart, which is why running
`alembic revision --autogenerate` on this project produced a diff that would have
*dropped and recreated* the uniqueness of `anilist_id`, `mal_id` and
`mangadex_id` on a 95k-row table — for a constraint whose meaning had not
changed, only its name. A autogenerate diff you cannot trust is worse than no
autogenerate at all, so the shapes are reconciled here:

* the three unique constraints get the names the models use
  (`manga_anilist_id_key` -> `uq_manga_anilist_id`, ...);
* the duplicate index on `manga_external_ids (manga_id)` is dropped —
  `index=True` on the column and the explicit index in revision 0002 had built
  the same btree twice;
* the two foreign keys and the two `sync_runs` indexes already present in the
  deployed database are declared in `app/db_models.py`, so a fresh database gets
  them too.

After this revision `alembic check` reports no pending operations, which is what
makes autogenerate safe to use for future work.
"""

from __future__ import annotations

from alembic import op

from migrations.helpers import constraint_exists, index_exists

revision = "0004_constraint_names"
down_revision = "0003_search_indexes"
branch_labels = None
depends_on = None

# (constraint, table, definition) — declared in db_models.py, so a fresh database
# gets them from the baseline; a database created before that declaration needs
# them added here.
FOREIGN_KEYS = (
    (
        "recommendations_edges_manga_id_from_fkey",
        "recommendations_edges",
        "FOREIGN KEY (manga_id_from) REFERENCES manga (id)",
    ),
    (
        "recommendations_edges_manga_id_to_fkey",
        "recommendations_edges",
        "FOREIGN KEY (manga_id_to) REFERENCES manga (id)",
    ),
)

RENAMES = (
    ("manga", "manga_anilist_id_key", "uq_manga_anilist_id"),
    ("manga", "manga_mal_id_key", "uq_manga_mal_id"),
    ("manga", "manga_mangadex_id_key", "uq_manga_mangadex_id"),
)


def upgrade() -> None:
    for table, old, new in RENAMES:
        if constraint_exists(table, old) and not constraint_exists(table, new):
            op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")

    for name, table, definition in FOREIGN_KEYS:
        if not constraint_exists(table, name):
            op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}")

    # Same btree on the same column, built twice by two different code paths.
    op.execute("DROP INDEX IF EXISTS ix_manga_external_ids_manga_id")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_manga_external_ids_manga_id ON manga_external_ids (manga_id)"
    )
    for table, old, new in RENAMES:
        if constraint_exists(table, new) and not constraint_exists(table, old):
            op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}")
