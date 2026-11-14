from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import AsyncSessionLocal
from ..db_models import SyncApiUsage


class BudgetExceeded(RuntimeError):
    def __init__(self, source: str, used: int, limit: int):
        self.source = source
        self.used = used
        self.limit = limit
        super().__init__(f"{source} daily request budget exhausted ({used}/{limit})")


def utc_day() -> date:
    """Application-clock day. Only used for tests/display; real calls use DB time."""
    return datetime.now(timezone.utc).date()


def reset_at(day: date) -> datetime:
    """UTC midnight that ends `day` and starts a fresh counter."""
    return datetime.combine(day + timedelta(days=1), dt_time.min, tzinfo=timezone.utc)


async def db_utc_day(session: AsyncSession) -> date:
    """Authoritative day: the database UTC date.

    Using the database clock means changing the application or container clock
    cannot roll the daily budget over early.
    """
    value = await session.scalar(text("SELECT (now() AT TIME ZONE 'utc')::date"))
    return value


async def _db_now(session: AsyncSession) -> datetime:
    return await session.scalar(text("SELECT now()"))


async def get_usage(source: str, day: date | None = None) -> int:
    async with AsyncSessionLocal() as session:
        day = day or await db_utc_day(session)
        value = await session.scalar(
            select(SyncApiUsage.requests).where(
                SyncApiUsage.day == day,
                SyncApiUsage.source == source,
            )
        )
        return int(value or 0)


async def remaining(source: str, limit: int, day: date | None = None) -> int:
    used = await get_usage(source, day)
    return max(0, limit - used)


async def consume(
    source: str,
    limit: int,
    day: date | None = None,
    *,
    spend: bool = True,
) -> int:
    """Atomically reserve one provider request for today.

    A single INSERT ... ON CONFLICT ... WHERE requests < limit ... RETURNING is
    atomic, so two concurrent callers can never spend the same last request.
    An explicit `day` is only for tests; real callers use the database UTC date.

    ``spend=False`` is the dry-run path: it enforces exactly the same limit but
    does not increment the counter, so a rehearsal never costs a real request
    (or blocks the real run later in the day).
    """
    if limit <= 0:
        raise BudgetExceeded(source, 0, limit)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            day = day or await db_utc_day(session)
            if not spend:
                used = await session.scalar(
                    select(SyncApiUsage.requests).where(
                        SyncApiUsage.day == day,
                        SyncApiUsage.source == source,
                    )
                )
                used = int(used or 0)
                if used >= limit:
                    raise BudgetExceeded(source, used, limit)
                return used + 1
            value = await session.scalar(
                text(
                    """
                    INSERT INTO sync_api_usage (day, source, requests)
                    VALUES (:day, :source, 1)
                    ON CONFLICT (day, source) DO UPDATE
                       SET requests = sync_api_usage.requests + 1,
                           updated_at = now()
                     WHERE sync_api_usage.requests < :limit
                    RETURNING requests
                    """
                ),
                {"day": day, "source": source, "limit": limit},
            )
            if value is None:
                used = await session.scalar(
                    select(SyncApiUsage.requests).where(
                        SyncApiUsage.day == day,
                        SyncApiUsage.source == source,
                    )
                )
                raise BudgetExceeded(source, int(used or limit), limit)
            return int(value)


async def usage_summary(source: str, limit: int) -> dict[str, int | float | str]:
    """Today's usage plus everything the status UI needs to draw a progress bar."""
    async with AsyncSessionLocal() as session:
        day = await db_utc_day(session)
        now = await _db_now(session)
        used = await session.scalar(
            select(SyncApiUsage.requests).where(
                SyncApiUsage.day == day,
                SyncApiUsage.source == source,
            )
        )
        used = int(used or 0)
        limit = max(0, int(limit))
        ends_at = reset_at(day)
        return {
            "day": day.isoformat(),
            "source": source,
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "percent": round((used / limit) * 100, 1) if limit else 0.0,
            "reset_at": ends_at.isoformat(),
            "seconds_to_reset": max(0, int((ends_at - now).total_seconds())),
            "hard_ceiling": max(limit, int(settings.SYNC_HARD_DAILY_CEILING)),
        }
