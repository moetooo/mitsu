"""Cover health as a number, not an anecdote.

The cover outage was invisible for months because nothing asked the question.
This module answers it in one query and one verdict:

    total / ok / dead / unverified        how much of the catalogue renders
    ok with 2+ providers                  how much survives one provider dying
    how recently a run actually looked    whether the answer is current
    reported / failed in the window       whether users are hitting rot

The verdict is deliberately about *risk*, not about a single broken URL: a
catalogue where every cover is on one host is one host away from the last outage,
so redundancy is part of "healthy" even when nothing is broken today.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .cache import redis_client

logger = logging.getLogger("mitsu.covers.health")

CACHE_KEY = "cover:health:v1"
#: Written by `scripts/resolve_covers.py --mode verify --apply`. `cover_checked_at`
#: cannot serve this purpose: migration 0007 backfilled it, so it always looks fresh.
LAST_VERIFY_KEY = "cover:verify:last_run"
CACHE_SECONDS = 30

#: A title with no provider id cannot be repaired automatically, so those rows cap
#: the achievable "share of the catalogue that renders" at 100% minus their share.
MIN_OK_SHARE = 0.90
MIN_FALLBACK_SHARE = 0.40
MAX_VERIFY_AGE_DAYS = 21

STATS_SQL = text(
    """
    SELECT
        count(*)                                                            AS total,
        count(*) FILTER (WHERE cover_status = 'ok')                          AS ok,
        count(*) FILTER (WHERE cover_status = 'dead')                        AS dead,
        count(*) FILTER (WHERE cover_status = 'unverified')                  AS unverified,
        count(*) FILTER (
            WHERE cover_status = 'ok' AND jsonb_array_length(cover_candidates) >= 2
        )                                                                    AS ok_with_fallback,
        count(*) FILTER (
            WHERE cover_status = 'ok' AND jsonb_array_length(cover_candidates) = 1
        )                                                                    AS ok_single,
        count(*) FILTER (WHERE cover_checked_at IS NOT NULL)                  AS ever_checked,
        count(*) FILTER (WHERE cover_checked_at > now() - interval '7 days')  AS checked_7d,
        max(cover_checked_at)                                                 AS last_checked
    FROM manga
    """
)

LOG_SQL = text(
    """
    SELECT
        count(*) FILTER (
            WHERE result = 'reported' AND created_at > now() - interval '24 hours'
        )                                                                    AS reported_24h,
        count(*) FILTER (
            WHERE result = 'failed' AND created_at > now() - interval '7 days'
        )                                                                    AS failed_7d,
        max(created_at) FILTER (WHERE result IN ('resolved', 'fallback'))      AS last_repair
    FROM cover_repair_log
    """
)


def _share(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def assess(stats: dict) -> dict:
    """Turn the counters into a verdict plus the reasons for it.

    Pure function: the thresholds are the policy, and a policy that cannot be
    tested without a database is a policy nobody will change.
    """
    reasons: list[str] = []
    total = stats.get("total", 0) or 0
    ok_share = stats.get("ok_share", 0.0)
    fallback_share = stats.get("fallback_share", 0.0)
    age = stats.get("verify_age_days")

    severity = "healthy"

    if total and ok_share < 0.75:
        severity = "critical"
        reasons.append(f"only {ok_share:.1%} of titles have a working cover")
    elif total and ok_share < MIN_OK_SHARE:
        severity = "degraded"
        reasons.append(f"{1 - ok_share:.1%} of titles have no working cover")

    if total and fallback_share < MIN_FALLBACK_SHARE:
        # Not broken today - one provider away from being broken tomorrow.
        severity = "critical" if severity == "critical" else "degraded"
        reasons.append(
            f"only {fallback_share:.1%} of covers have a second provider "
            "(one host failure repeats the outage)"
        )

    if age is None:
        if severity == "healthy":
            severity = "degraded"
        reasons.append("no cover has ever been verified")
    elif age > MAX_VERIFY_AGE_DAYS:
        if severity == "healthy":
            severity = "degraded"
        reasons.append(f"last verification was {age:.0f} days ago")

    reported = stats.get("reported_24h", 0) or 0
    if reported >= 10:
        reasons.append(f"{reported} covers reported broken in the last 24h")

    return {"status": severity, "reasons": reasons}


async def _host_breakers() -> dict:
    """Which cover hosts a recent verify run gave up on."""
    try:
        keys = [k async for k in redis_client.scan_iter("cover:verify:hostdown:*")]
    except Exception:
        return {}
    return {k.rsplit(":", 1)[-1]: "open" for k in keys}


def _policy() -> dict:
    """The live cover policy: which hosts may be shown, in which order."""
    try:
        from ..core.covers import (
            allowed_hosts,
            blocked_hosts,
            max_candidates,
            source_order,
            validate_cover_config,
        )

        return {
            "allowed_hosts": list(allowed_hosts()),
            "blocked_hosts": list(blocked_hosts()),
            "source_order": list(source_order()),
            "max_candidates": max_candidates(),
            "problems": validate_cover_config(),
        }
    except Exception:
        return {}


async def _last_verify() -> Optional[dict]:
    try:
        raw = await redis_client.get(LAST_VERIFY_KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def _canary_state() -> Optional[dict]:
    try:
        from .cover_canary import last_state

        state = await last_state()
    except Exception:
        return None
    if not state:
        return None
    return {k: state.get(k) for k in ("verdict", "status", "content_type", "checked_at")}


async def cover_health(db: AsyncSession, *, refresh: bool = False) -> dict:
    """The whole picture, cached briefly so a dashboard cannot scan 96k rows."""
    if not refresh:
        try:
            cached = await redis_client.get(CACHE_KEY)
            if cached:
                stats = json.loads(cached)
                # Counters may be 30 s old; the policy is free to read and must be
                # current, or a config change looks like it did nothing.
                stats["policy"] = _policy()
                return stats
        except Exception:
            pass

    row = (await db.execute(STATS_SQL)).mappings().first() or {}
    log = (await db.execute(LOG_SQL)).mappings().first() or {}

    total = int(row.get("total") or 0)
    ok = int(row.get("ok") or 0)
    last_checked = row.get("last_checked")

    last_verify = await _last_verify()
    verify_at = last_checked if isinstance(last_checked, datetime) else None
    verify_source = "row_timestamps"
    if last_verify and last_verify.get("at"):
        try:
            verify_at = datetime.fromisoformat(last_verify["at"])
            verify_source = "verify_run"
        except Exception:
            pass

    age_days = None
    if isinstance(verify_at, datetime):
        age_days = round((datetime.now(timezone.utc) - verify_at).total_seconds() / 86400, 1)

    stats = {
        "total": total,
        "ok": ok,
        "dead": int(row.get("dead") or 0),
        "unverified": int(row.get("unverified") or 0),
        "ok_share": _share(ok, total),
        "ok_with_fallback": int(row.get("ok_with_fallback") or 0),
        "ok_single_provider": int(row.get("ok_single") or 0),
        "fallback_share": _share(int(row.get("ok_with_fallback") or 0), ok),
        "ever_checked": int(row.get("ever_checked") or 0),
        "checked_7d": int(row.get("checked_7d") or 0),
        "last_checked_at": last_checked.isoformat() if isinstance(last_checked, datetime) else None,
        "last_verify_at": verify_at.isoformat() if isinstance(verify_at, datetime) else None,
        "verify_source": verify_source,
        "last_verify_run": last_verify,
        "verify_age_days": age_days,
        "reported_24h": int(log.get("reported_24h") or 0),
        "failed_7d": int(log.get("failed_7d") or 0),
        "last_repair_at": (
            log["last_repair"].isoformat()
            if isinstance(log.get("last_repair"), datetime)
            else None
        ),
        "hosts_down": await _host_breakers(),
        "policy": _policy(),
        "canary": await _canary_state(),
    }
    stats.update(assess(stats))
    stats["checked_at"] = datetime.now(timezone.utc).isoformat()

    try:
        await redis_client.set(CACHE_KEY, json.dumps(stats), ex=CACHE_SECONDS)
    except Exception:
        pass
    return stats


async def log_if_unhealthy(stats: dict) -> None:
    """One warning line, from whichever periodic task is already running.

    No scheduler: the canary wakes weekly and the verify script runs by hand, and
    both call this, so a health regression that nobody asked about still lands in
    the logs.
    """
    if stats.get("status") == "healthy":
        return
    logger.warning(
        "Cover health %s: %s (ok %.1f%%, fallback %.1f%%)",
        stats.get("status"),
        "; ".join(stats.get("reasons") or []) or "no reason recorded",
        (stats.get("ok_share") or 0) * 100,
        (stats.get("fallback_share") or 0) * 100,
    )
