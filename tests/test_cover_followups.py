"""Open cover work, tracked where it will actually be seen.

This repository does not track `docs/`, `scripts/` or `*.md` (see `.gitignore`), so a
notes file would not survive a clone. These skipped tests are the tracked copy of
what is left: they show up in every `pytest` run, each one names the exact command or
query that closes it, and the long write-up is in `docs/cover-followups.md` (local,
like every other document here).

A skipped test is a promise with a date on it. When one of these is done, delete it
rather than un-skipping it - the work is covered by the seam and verifier tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import AsyncSessionLocal

APP_ROOT = Path(__file__).resolve().parent.parent
FOLLOWUPS = APP_ROOT / "docs" / "cover-followups.md"

#: Every command the follow-up document is expected to mention.
DOCUMENTED_COMMANDS = (
    "python scripts/resolve_covers.py --source anilist --apply --limit 917",
    "python scripts/resolve_covers.py --mode verify --apply",
    "python scripts/cover_probe.py",
)


@pytest.mark.skip(
    reason="917 dead rows have an anilist_id but no AniList cover; closing them needs a "
    "free AniList budget (19 requests): "
    "python scripts/resolve_covers.py --source anilist --apply --limit 917"
)
def test_anilist_only_dead_rows_are_repaired():
    """Blocked on `ANILIST_DAILY_REQUEST_BUDGET`, not on code."""


@pytest.mark.skip(
    reason="5,439 dead rows have no provider id at all, so no provider can answer for "
    "them; repairing needs identity matching (an ingestion problem) or deletion"
)
def test_rows_with_no_provider_id_are_resolved_or_deleted():
    """Options are listed in docs/cover-followups.md section 3."""


@pytest.mark.skip(
    reason="3 dead rows have a mal_id that Tenrai has no cover for; they stay tile-only "
    "unless a third provider (Kitsu, which needs kitsu_id) is added"
)
def test_the_three_uncoverable_mal_rows_are_closed():
    """SELECT id FROM manga WHERE cover_status = 'dead' AND mal_id IS NOT NULL;"""


@pytest.mark.skip(
    reason="cover_color (AniList coverImage.color) is not persisted: needs a column, a "
    "backfill and a client change, so the fallback tile cannot use the cover's colour"
)
def test_cover_colour_is_used_by_the_fallback_tile():
    """Feature, not a defect. Nothing is broken while it is missing."""


def test_the_followup_document_matches_these_commands():
    """A skipped test and a document that disagree are worse than either alone."""
    if not FOLLOWUPS.exists():
        pytest.skip("docs/ is not tracked in this repository; nothing to compare")

    document = FOLLOWUPS.read_text(encoding="utf-8")
    missing = [command for command in DOCUMENTED_COMMANDS if command not in document]
    assert not missing, "docs/cover-followups.md no longer documents: " + "; ".join(missing)


async def test_the_catalogue_keeps_the_seam_invariant():
    """`cover_image_url` is exactly `cover_candidates[0]` - the whole point of the seam.

    This is the check that would have caught the original bug: it compares the stored
    columns with each other rather than trusting any single write path.
    """
    async with AsyncSessionLocal() as session:
        total = (await session.execute(text("SELECT count(*) FROM manga"))).scalar()
        if not total:
            pytest.skip("test catalogue is empty")

        broken = (
            await session.execute(
                text(
                    """
                    SELECT count(*) FROM manga
                    WHERE cover_candidates <> '[]'::jsonb
                      AND cover_image_url IS DISTINCT FROM (cover_candidates->0->>'url')
                    """
                )
            )
        ).scalar()
        served = (
            await session.execute(
                text(
                    "SELECT count(*) FROM manga "
                    "WHERE cover_status = 'ok' AND cover_image_url LIKE '%mangadex%'"
                )
            )
        ).scalar()

    assert broken == 0, f"{broken} row(s) disagree with their own candidate list"
    assert served == 0, f"{served} row(s) claim a cover on a blocked host"
