"""Allow `mal` as a cover source.

`cover_source` was constrained to `anilist | kitsu | mangadex | none` in 0007,
when AniList was the only provider a repair could reach. A repair now re-sources
MangaDex-dead covers from MyAnimeList (via the Tenrai mirror), so the column has
to be able to record `mal` - otherwise every repaired row is rejected by the
constraint and the repair cannot be written at all.

The constraint is replaced rather than dropped: it is what keeps a typo or a new
provider from being stored as free text that no code understands.

Revision ID: 0009_cover_source_mal
Revises: 0008_cover_candidates
"""

import logging

from alembic import op

from migrations.helpers import constraint_exists

revision = "0009_cover_source_mal"
down_revision = "0008_cover_candidates"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

SOURCE_CHECK = "ck_manga_cover_source"

ALLOWED_WITH_MAL = "('anilist', 'kitsu', 'mangadex', 'mal', 'none')"
ALLOWED_WITHOUT_MAL = "('anilist', 'kitsu', 'mangadex', 'none')"


def _replace(allowed: str) -> None:
    op.execute(f"ALTER TABLE manga DROP CONSTRAINT IF EXISTS {SOURCE_CHECK}")
    op.execute(
        f"ALTER TABLE manga ADD CONSTRAINT {SOURCE_CHECK} "
        f"CHECK (cover_source IS NULL OR cover_source IN {allowed})"
    )


def upgrade() -> None:
    logger.info("migration 0009: widening %s to accept 'mal'", SOURCE_CHECK)
    _replace(ALLOWED_WITH_MAL)


def downgrade() -> None:
    # Rows a repair already set to `mal` would violate the narrower constraint, so
    # they are relabelled rather than left to make the downgrade fail. `none` keeps
    # the status meaningful (the URL itself is still recorded and still served).
    op.execute("UPDATE manga SET cover_source = 'none' WHERE cover_source = 'mal'")
    if constraint_exists("manga", SOURCE_CHECK):
        _replace(ALLOWED_WITHOUT_MAL)
