"""Baseline: the schema this project had before migrations existed.

Fresh installs get every table from the current model definitions, so a new
environment is created by one command (`alembic upgrade head`) instead of by
whichever startup path happened to run first.

An existing deployment already has this schema and must NOT replay it: run
`alembic stamp head` once against it (see docs/MIGRATIONS.md). The later
revisions are written to be no-ops on a database that is already current, so a
stamp that is missed is recoverable rather than destructive.

Note on `create_all` in a migration: it is acceptable exactly here, because this
revision is the frozen starting point. Every later revision is explicit DDL —
do not add tables to the baseline after the fact.
"""

from __future__ import annotations

from alembic import op

from app.db import Base
import app.db_models  # noqa: F401 - registers every table on Base.metadata
from migrations.helpers import ensure_alt_titles_function

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Extensions first: the models use vector(384) and trigram indexes.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # The models also declare an index whose expression calls this function, so
    # it has to exist before create_all() - see ensure_alt_titles_function().
    ensure_alt_titles_function()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
