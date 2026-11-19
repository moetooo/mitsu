"""Weekly probe: is MangaDex's cover CDN serving images to browsers again?

Why a canary and not a nightly verification pass: the block that cost this
catalogue 10,463 covers was a host-level decision. Checking one real MangaDex
cover once a week answers the only question that matters - "is this host worth
re-enabling?" - for **one HTTP request per week**, with no scheduler to install
and nothing on the request path blocking on it.

The verdict is recorded rather than acted on. Re-enabling MangaDex is a policy
change (`COVER_ALLOWED_HOSTS` / source order, task 16), so a lifted block logs
loudly and waits for a human; nothing here silently starts writing MangaDex URLs
back into the catalogue.

How it is scheduled: `app.main`'s lifespan starts `canary_loop()`, which probes
and then sleeps. A Redis key (`SET NX EX 7d`) makes sure exactly one worker
probes per week no matter how many replicas are running, and survives restarts -
so a boot loop cannot hammer the host. If Redis is unavailable the loop falls
back to an in-process timestamp, which is weaker but still bounded.

Verdicts:
  ok      200 + `content-type: image/*`  -> the block has lifted
  blocked 200 with a non-image body, or 401/403/429 -> still blocking browsers
  error   timeout / connection failure / 5xx -> unknown, do not act on it
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from ..config import settings
from .cache import redis_client

logger = logging.getLogger("mitsu.covers.canary")

# A real cover path taken from the catalogue. Anything on the host would do; this
# one is a title the site actually showed, so "it works again" means it works for
# real rows too.
CANARY_URL = (
    "https://uploads.mangadex.org/covers/"
    "789642f8-ca89-4e4e-8f7b-eee4d17ea08b/60530e72-f76f-45d5-b6f9-f95e05058fc3.png"
)

# One probe a week is enough: a host block is not a minutes-scale event, and the
# answer changes policy, not traffic.
CANARY_INTERVAL_SECONDS = 7 * 24 * 3600

# How often the sleeping loop wakes to ask whether the week is up. Cheap: the
# Redis SET NX decides, so waking often costs nothing but a round trip.
CHECK_INTERVAL_SECONDS = 6 * 3600

LOCK_KEY = "cover:canary:due"
STATE_KEY = "cover:canary:state"

# A browser's own headers. Without these the probe measures a different endpoint
# than the one users hit - which is exactly how the original block was misread as
# "a few bad rows" instead of a host-level challenge page.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

TIMEOUT = httpx.Timeout(connect=8.0, read=10.0, write=5.0, pool=5.0)

# Fallback when Redis cannot be reached. Per-process, so several replicas would
# each probe once a week - acceptable, since the alternative is not probing at all.
_last_probe_at: Optional[float] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def probe(url: Optional[str] = None, *, transport: Optional[httpx.AsyncBaseTransport] = None) -> Dict[str, Any]:
    """One browser-like GET, reduced to a verdict. Never raises."""
    target = url or CANARY_URL
    result: Dict[str, Any] = {
        "url": target,
        "verdict": "error",
        "status": None,
        "content_type": None,
        "checked_at": _now(),
    }

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            headers=BROWSER_HEADERS,
            transport=transport,
            follow_redirects=True,
        ) as client:
            response = await client.get(target)
    except Exception as exc:
        # Timeouts and connection resets say nothing about the block: the host may
        # simply be slow today. Recorded as `error`, never as "still blocked".
        result["detail"] = f"{type(exc).__name__}: {exc}"
        return result

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    result["status"] = response.status_code
    result["content_type"] = content_type or None

    if response.status_code == 200 and content_type.startswith("image/"):
        result["verdict"] = "ok"
    elif response.status_code in (401, 403, 429, 503) or response.status_code == 200:
        # 200 with an HTML body is the exact shape of the original block.
        result["verdict"] = "blocked"
        result["detail"] = f"http {response.status_code} {content_type or 'no content-type'}"
    else:
        result["detail"] = f"http {response.status_code}"
    return result


async def _claim_week(force: bool) -> bool:
    """True when this caller is the one that may probe now."""
    global _last_probe_at

    if force:
        return True

    try:
        claimed = await redis_client.set(LOCK_KEY, _now(), nx=True, ex=CANARY_INTERVAL_SECONDS)
        if claimed is None:  # Redis reachable, key already held
            return False
        return True
    except Exception as exc:
        logger.debug("Redis unavailable (%s); using the in-process throttle", exc)
        if _last_probe_at is not None and (time.monotonic() - _last_probe_at) < CANARY_INTERVAL_SECONDS:
            return False
        return True


async def run_canary(
    *,
    force: bool = False,
    url: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Dict[str, Any]:
    """Probe once per week (or now, with `force`) and record the verdict."""
    global _last_probe_at

    if not await _claim_week(force):
        return {"skipped": True, "reason": "checked within the last week"}

    _last_probe_at = time.monotonic()
    result = await probe(url, transport=transport)

    try:
        await redis_client.set(STATE_KEY, json.dumps(result), ex=CANARY_INTERVAL_SECONDS * 4)
    except Exception as exc:
        logger.debug("Could not store the verdict: %s", exc)

    if result["verdict"] == "ok":
        # Loud on purpose: this is the signal that MangaDex may be reinstated, and
        # without it a lifted block is indistinguishable from a permanent one.
        logger.warning(
            "MangaDex covers are loadable again (200 %s) - the block has lifted; "
            "re-enabling it is a config change (COVER_ALLOWED_HOSTS / source order)",
            result["content_type"],
        )
    elif result["verdict"] == "blocked":
        # Expected state; debug only so it never trains anyone to ignore warnings.
        logger.debug("Still blocked: %s", result.get("detail"))
    else:
        logger.warning("Inconclusive probe (%s); will retry", result.get("detail"))

    return result


async def audit_health() -> None:
    """Log a warning if the cover picture is not healthy.

    The canary already wakes once a week, so it doubles as the alarm: no second
    scheduler, and a regression is noticed even if nobody opens the health endpoint.
    """
    try:
        from ..db import AsyncSessionLocal
        from .cover_health import cover_health, log_if_unhealthy

        async with AsyncSessionLocal() as session:
            stats = await cover_health(session, refresh=True)
        await log_if_unhealthy(stats)
    except Exception as exc:  # an audit must never be the reason the loop dies
        logger.debug("Health audit skipped: %s", exc)


async def canary_loop(
    stop: asyncio.Event,
    *,
    check_interval: float = CHECK_INTERVAL_SECONDS,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> None:
    """Probe, then sleep. Started from the application lifespan."""
    while not stop.is_set():
        try:
            result = await run_canary(transport=transport)
            # Only audit after a real probe: the "checked within the last week"
            # answer means nothing changed, so it must not wake the database.
            if result and not result.get("skipped"):
                await audit_health()
        except Exception as exc:  # a canary must never take the app down
            logger.warning("Probe failed unexpectedly: %s", exc)

        try:
            await asyncio.wait_for(stop.wait(), timeout=check_interval)
        except asyncio.TimeoutError:
            continue


async def last_state() -> Optional[Dict[str, Any]]:
    """The last recorded verdict, or None when the canary has not run."""
    try:
        raw = await redis_client.get(STATE_KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def canary_enabled() -> bool:
    """Settings flag, exposed for tests and health reporting."""
    return bool(settings.COVER_CANARY_ENABLED)
