from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update

from ..config import settings
from ..db import AsyncSessionLocal
from ..db_models import SyncRun
from ..core.budget import db_utc_day, reset_at, usage_summary

# Statuses that represent a real attempt and therefore count toward the day.
# A rejected trigger never reached a provider, so counting it would let one
# refusal push the day's counter further over the limit and lock the user out.
COUNTED_STATUSES = ("running", "success", "partial", "failed")
# A local-day auto slot is only spent once the run actually starts working.
# A failure may be retried; rejections never consume it.
AUTO_COUNTED_STATUSES = ("running", "success", "partial")
STALE_AFTER = timedelta(hours=2)
COOLDOWN_MODES = ("manual", "backfill")


class GuardrailError(RuntimeError):
    def __init__(self, code: str, message: str, retry_after: int | None = None):
        self.code = code
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "retry_after": self.retry_after,
        }


def daily_budget(source: str) -> int:
    if source == "anilist":
        return max(1, int(settings.ANILIST_DAILY_REQUEST_BUDGET))
    if source == "mangadex":
        return max(1, int(settings.MANGADEX_DAILY_REQUEST_BUDGET))
    return 0


def _hard_ceiling(base: int) -> int:
    # A ceiling below the configured daily budget would be a foot-gun, so the
    # base budget always wins. Overrides may only narrow usage.
    return max(base, int(settings.SYNC_HARD_DAILY_CEILING))


def effective_daily_limit(source: str, override: int | None = None) -> int:
    """Resolve a per-day cap, clamping one-off overrides to the deploy ceiling."""
    base = daily_budget(source)
    if base <= 0:
        return 0
    ceiling = _hard_ceiling(base)
    if override is None or int(override) <= 0:
        return base
    return min(max(1, int(override)), ceiling)


def backfill_request_limit(override: int | None = None) -> int:
    """Backfill's share of the AniList budget, keeping a reserve for daily sync."""
    cap = effective_daily_limit("anilist", override)
    reserve = max(0, int(settings.SYNC_BACKFILL_RESERVE))
    return max(0, cap - reserve)


def limits_from_usage(usage: dict) -> dict:
    """Per-trigger page caps that never spend the daily-sync reserve.

    Manual/auto sync may use whatever is left. Backfill may only use what
    remains after the reserve, so it can never starve the normal daily run.
    """
    remaining = max(0, int(usage.get("remaining") or 0))
    reserve = max(0, int(settings.SYNC_BACKFILL_RESERVE))
    backfill_cap = backfill_request_limit()
    return {
        "anilist_remaining": remaining,
        "manual_pages": remaining,
        "backfill_pages": max(0, min(backfill_cap, remaining - reserve)),
        "backfill_reserve": reserve,
        "backfill_limit": backfill_cap,
        "seconds_to_reset": max(0, int(usage.get("seconds_to_reset") or 0)),
    }


async def trigger_limits() -> dict:
    usage = await usage_summary("anilist", effective_daily_limit("anilist"))
    return limits_from_usage(usage)


async def reap_stale_runs() -> int:
    """Mark runs stuck in `running` after a crash as failed so they stop counting."""
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                update(SyncRun)
                .where(SyncRun.status == "running", SyncRun.started_at < cutoff)
                .values(
                    status="failed",
                    finished_at=datetime.now(timezone.utc),
                    error="stale run reaped by guardrail",
                )
            )
            return result.rowcount or 0


def _local_day_window(now_utc: datetime | None = None) -> tuple[str, datetime, datetime]:
    """Local-day bounds for the auto gate, returned as aware UTC datetimes."""
    zone = ZoneInfo(settings.SYNC_AUTO_DAY_TZ)
    now_local = (now_utc or datetime.now(timezone.utc)).astimezone(zone)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.date().isoformat(),
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


async def _today_state() -> dict:
    async with AsyncSessionLocal() as session:
        day = await db_utc_day(session)
        now = await session.scalar(select(func.now()))
        runs_today = await session.scalar(
            select(func.count())
            .select_from(SyncRun)
            .where(
                func.date(func.timezone("utc", SyncRun.started_at)) == day,
                SyncRun.status.in_(COUNTED_STATUSES),
                # A rehearsal spends no budget, so it must not consume one of
                # the day's real run slots (same rule as the auto gate).
                SyncRun.dry_run.is_(False),
            )
        )
        last_trigger = await session.scalar(
            select(func.max(SyncRun.started_at)).where(
                SyncRun.mode.in_(COOLDOWN_MODES),
                # A rejected or skipped trigger never ran, so it must not arm a
                # cooldown that blocks the next real attempt.
                SyncRun.status.in_(COUNTED_STATUSES),
            )
        )
        auto_day, auto_day_start, auto_next_at = _local_day_window()
        auto_runs_today = await session.scalar(
            select(func.count())
            .select_from(SyncRun)
            .where(
                SyncRun.mode == "auto",
                SyncRun.status.in_(AUTO_COUNTED_STATUSES),
                SyncRun.dry_run.is_(False),
                SyncRun.started_at >= auto_day_start,
            )
        )
    cooldown = max(0, int(settings.SYNC_MANUAL_COOLDOWN_SECONDS))
    next_manual_at = last_trigger + timedelta(seconds=cooldown) if last_trigger and cooldown else None
    return {
        "day": day,
        "now": now,
        "runs_today": int(runs_today or 0),
        "daily_run_limit": max(1, int(settings.SYNC_DAILY_RUN_LIMIT)),
        "cooldown_seconds": cooldown,
        "next_manual_at": next_manual_at,
        "auto_day": auto_day,
        "auto_day_start": auto_day_start,
        "auto_next_at": auto_next_at,
        "auto_runs_today": int(auto_runs_today or 0),
        "auto_daily_limit": max(1, int(settings.SYNC_AUTO_DAILY_RUN_LIMIT)),
    }


async def preflight_trigger(mode: str) -> dict:
    """Reject a trigger before any provider request is spent.

    Raised errors are safe to surface to the caller and are also recorded as a
    `rejected` run by the caller so repeated attempts stay auditable.
    """
    await reap_stale_runs()
    state = await _today_state()
    now: datetime = state["now"]

    if state["runs_today"] >= state["daily_run_limit"]:
        ends_at = reset_at(state["day"])
        retry_after = max(1, int((ends_at - now).total_seconds()))
        raise GuardrailError(
            "daily_run_limit",
            f"daily sync run limit reached ({state['runs_today']}/{state['daily_run_limit']})",
            retry_after=retry_after,
        )

    next_manual_at: datetime | None = state["next_manual_at"]
    if mode == "auto" and state["auto_runs_today"] >= state["auto_daily_limit"]:
        auto_ends_at: datetime = state["auto_next_at"]
        retry_after = max(1, int((auto_ends_at - now).total_seconds()))
        raise GuardrailError(
            "auto_daily_limit",
            f"auto sync already ran today ({state['auto_runs_today']}/"
            f"{state['auto_daily_limit']} in {settings.SYNC_AUTO_DAY_TZ}); "
            "next prompt after local midnight",
            retry_after=retry_after,
        )
    if mode in COOLDOWN_MODES and next_manual_at and now < next_manual_at:
        retry_after = max(1, int((next_manual_at - now).total_seconds()))
        raise GuardrailError(
            "manual_cooldown",
            f"manual sync is cooling down; retry in {retry_after}s",
            retry_after=retry_after,
        )

    limits = await trigger_limits()
    mode_limit = limits["backfill_pages"] if mode == "backfill" else limits["manual_pages"]
    if mode_limit <= 0:
        if mode == "backfill":
            code = "backfill_budget"
            message = (
                "backfill paused: not enough AniList requests left to keep the "
                f"{limits['backfill_reserve']}-request daily-sync reserve"
            )
        else:
            code = "budget_exhausted"
            message = "AniList daily request budget exhausted; resets at 00:00 UTC"
        raise GuardrailError(
            code,
            message,
            retry_after=max(1, limits["seconds_to_reset"]),
        )

    return {
        "day": state["day"].isoformat(),
        "runs_today": state["runs_today"],
        "daily_run_limit": state["daily_run_limit"],
        "cooldown_seconds": state["cooldown_seconds"],
        "max_pages": mode_limit,
        "anilist_remaining": limits["anilist_remaining"],
        "auto_runs_today": state["auto_runs_today"],
        "auto_daily_limit": state["auto_daily_limit"],
    }


async def guard_status() -> dict:
    await reap_stale_runs()
    state = await _today_state()
    now: datetime = state["now"]
    ends_at = reset_at(state["day"])
    next_manual_at: datetime | None = state["next_manual_at"]
    return {
        "day": state["day"].isoformat(),
        "day_reset_at": ends_at.isoformat(),
        "seconds_to_reset": max(0, int((ends_at - now).total_seconds())),
        "runs_today": state["runs_today"],
        "daily_run_limit": state["daily_run_limit"],
        "cooldown_seconds": state["cooldown_seconds"],
        "next_manual_at": next_manual_at.isoformat() if next_manual_at and now < next_manual_at else None,
        "auto_day": state["auto_day"],
        "auto_day_tz": settings.SYNC_AUTO_DAY_TZ,
        "auto_next_at": state["auto_next_at"].isoformat(),
        "auto_runs_today": state["auto_runs_today"],
        "auto_daily_limit": state["auto_daily_limit"],
        "auto_ran_today": state["auto_runs_today"] >= state["auto_daily_limit"],
    }
