"""Client-reported broken covers.

A cover that 404s for a reader is a fact the reader knows and the server does not:
the URL was fine when it was written. Reporting it puts the row in front of the
next verifier run instead of waiting for a random spot-check to land on it.

What a report deliberately does **not** do: change `cover_status`. Anyone can call
this endpoint, and a stranger must not be able to take a cover off a card. A report
is evidence; two consecutive verifier failures are the verdict.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db_models import CoverRepairLog, Manga

logger = logging.getLogger("mitsu.covers.report")

#: The only reasons accepted. A free-text field would be an unbounded foreign
#: string in our database written by an anonymous caller.
REASONS = ("all_candidates_failed", "broken_image", "wrong_image")
DEFAULT_REASON = "all_candidates_failed"

#: One report per title per window. Without this, a user refreshing a broken card
#: writes a row each time and the verifier's evidence count becomes meaningless.
DEDUPE_HOURS = 24


class CoverNotFound(LookupError):
    """No manga with that id, so there is nothing to report."""


async def _recently_reported(db: AsyncSession, manga_id: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEDUPE_HOURS)
    stmt = (
        select(CoverRepairLog.id)
        .where(
            CoverRepairLog.manga_id == manga_id,
            CoverRepairLog.result == "reported",
            CoverRepairLog.created_at >= cutoff,
        )
        .limit(1)
    )
    return (await db.execute(stmt)).first() is not None


async def record_broken_report(
    db: AsyncSession, manga_id: int, *, reason: str = DEFAULT_REASON
) -> dict:
    """Record one report. Returns `{"recorded": bool, "message": str}`.

    Raises `CoverNotFound` for an id that is not in the catalogue, so the caller
    cannot use this endpoint to probe which ids exist *and* to litter the log.
    """
    if reason not in REASONS:
        reason = DEFAULT_REASON

    row = (
        await db.execute(
            select(Manga.id, Manga.cover_image_url).where(Manga.id == manga_id)
        )
    ).first()
    if row is None:
        raise CoverNotFound(manga_id)

    if await _recently_reported(db, manga_id):
        logger.info("Duplicate report for manga %s ignored", manga_id)
        return {"recorded": False, "message": f"already reported within {DEDUPE_HOURS}h"}

    db.add(
        CoverRepairLog(
            manga_id=manga_id,
            from_url=row.cover_image_url,
            to_url=None,
            source="none",
            result="reported",
            detail=reason,
        )
    )
    await db.commit()
    logger.info("Broken cover reported for manga %s (%s)", manga_id, reason)
    return {"recorded": True, "message": "queued for the next cover check"}


async def reported_ids(db: AsyncSession, limit: int = 200) -> list[int]:
    """Titles reported recently, newest first - the verify run's priority queue."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    stmt = (
        select(CoverRepairLog.manga_id)
        .where(CoverRepairLog.result == "reported", CoverRepairLog.created_at >= cutoff)
        .order_by(CoverRepairLog.created_at.desc())
        .limit(limit)
    )
    return [row[0] for row in (await db.execute(stmt)).all()]
