"""Small introspection helpers for idempotent migrations.

This project is brownfield: a real catalog already contains most of what the
early revisions add, and it was stamped rather than replayed. These helpers let a
revision express "make sure X exists" so it is safe both on a database that is
already current (the pre-migration deployment) and on a fresh one.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


def _scalar(sql: str, **params):
    return op.get_bind().execute(sa.text(sql), params).scalar()


def column_exists(table: str, column: str) -> bool:
    return bool(_scalar(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :table AND column_name = :column
        )
        """,
        table=table,
        column=column,
    ))


def index_exists(name: str) -> bool:
    return bool(_scalar(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() AND indexname = :name)",
        name=name,
    ))


def trigger_exists(table: str, name: str) -> bool:
    return bool(_scalar(
        "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = CAST(:table AS regclass) AND tgname = :name AND NOT tgisinternal)",
        table=table,
        name=name,
    ))


def constraint_exists(table: str, name: str) -> bool:
    return bool(_scalar(
        """
        SELECT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = CAST(:table AS regclass) AND conname = :name
        )
        """,
        table=table,
        name=name,
    ))


def add_column_if_missing(table: str, column: str, sql_type: str, *, default: str | None = None) -> bool:
    if column_exists(table, column):
        return False
    statement = f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
    if default is not None:
        statement += f" DEFAULT {default}"
    op.execute(statement)
    return True
