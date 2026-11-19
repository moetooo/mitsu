"""Cover lookups from Tenrai - a Jikan-v4-shaped mirror of the MAL catalogue.

Why this exists: the catalogue's primary cover host is AniList, and AniList's
self-imposed daily budget (`ANILIST_DAILY_REQUEST_BUDGET`) is already spent by
ingestion before any repair runs. Tenrai serves the same titles from MyAnimeList
with no daily cap, so a dead cover can still be re-sourced on the day it breaks.

Three things this module is careful about, each learned from the live API:

* **Never trust ordering.** A batch of 50 ids returns 48 entries - MAL ids 5 and 6
  do not exist - so anything that pairs the Nth response with the Nth request
  would shift every cover by one. Entries are keyed by the `mal_id` the server
  sends back, and ids outside the requested set are dropped.
* **One batched request per 50 ids.** 50 ids answer in ~1.2 s and ~180 KB, so a
  4,000-title repair is ~83 requests rather than 4,000.
* **Only MyAnimeList's CDN is accepted.** The URL is hotlinked straight into an
  `<img>`; a mirror that starts returning a differently-hosted or non-https URL
  must not reach the browser, so everything else is filtered out here.

A failure is per chunk, not per run: one 502 from a beta service must not throw
away the 3,900 covers that did resolve.
"""

import asyncio
import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

from .rate_limiter import fetch_with_retry, tenrai_bucket

logger = logging.getLogger("mitsu.ingestion.tenrai")

# `/manga` answers 301 to `/v1/manga`; calling the versioned path directly avoids
# a redirect on every request.
TENRAI_API_URL = "https://api.tenrai.org/v1/manga"

# 50 is both the documented ceiling and the size the API answers in one batch.
TENRAI_BATCH_SIZE = 50

# The only hosts whose images may be handed to a browser. Suffix-matched so a
# regional host such as `cdn.myanimelist.net` subdomains still passes.
COVER_HOST_ALLOWLIST = ("cdn.myanimelist.net",)

USER_AGENT = "mitsu-cover-repair/1.0 (+https://github.com/mitsu)"

# Per-phase timeouts rather than one flat number: a batch reply is ~180 KB, so a
# healthy read is under 2 s. A connect that hangs for 20 s is a dead host, and a
# read that hangs for 20 s is a stalled body - both must give up long before a
# repair run of 80+ batches would notice.
TENRAI_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)

# The rate limiter's own default is 6 attempts with exponential backoff (~60 s of
# stalling for a single chunk). Three is enough for a beta service that answers
# 502 while it restarts, and bounds the worst case per chunk at ~6 s.
TENRAI_MAX_RETRIES = 3

# The bucket already paces requests (1.5 rps). This is an extra breath between
# batches so a burst of retries cannot stack into the published 4 rps ceiling.
TENRAI_BATCH_GAP_SECONDS = 0.25

# After a failed chunk, wait longer before the next one: if the service is down,
# answering 83 batches at full speed only adds to its load.
TENRAI_FAILURE_BACKOFF_SECONDS = 2.0


def chunks(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    """Split `items` into slices of at most `size`."""
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _is_allowed(url: Optional[str]) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = httpx.URL(url)
    except Exception:  # httpx raises InvalidURL for junk; treat it as unusable
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.host or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in COVER_HOST_ALLOWLIST)


def pick_cover_urls(entry: Dict[str, Any]) -> List[str]:
    """Cover candidates for one Tenrai entry, best first, de-duplicated.

    `jpg.image_url` is the ~14-50 KB card-sized render measured on the live CDN;
    the `large_image_url` variants are several times heavier and only worth having
    as a later fallback. webp comes before large jpg because it is smaller than it.
    """
    images = entry.get("images") or {}
    jpg = images.get("jpg") or {}
    webp = images.get("webp") or {}

    ordered = [
        jpg.get("image_url"),
        webp.get("image_url"),
        jpg.get("large_image_url"),
        jpg.get("small_image_url"),
    ]

    urls: List[str] = []
    for url in ordered:
        if _is_allowed(url) and url not in urls:
            urls.append(url)
    return urls


async def fetch_entries(
    mal_ids: Sequence[int],
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    batch_size: int = TENRAI_BATCH_SIZE,
) -> Dict[int, Dict[str, Any]]:
    """Raw Tenrai entries for `mal_ids`, keyed by the `mal_id` they came back as.

    Ids that Tenrai does not know (deleted MAL records, ids from another provider)
    are simply absent from the result - callers must not assume one entry per id.
    """
    requested = {int(i) for i in mal_ids if i}
    if not requested:
        return {}

    found: Dict[int, Dict[str, Any]] = {}
    ordered_ids = sorted(requested)
    total_batches = (len(ordered_ids) + batch_size - 1) // batch_size
    failed_batches = 0

    async with httpx.AsyncClient(
        timeout=TENRAI_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        transport=transport,
        # Our own bucket paces the calls; let httpx follow a future redirect anyway.
        follow_redirects=True,
    ) as client:
        for index, batch in enumerate(chunks(ordered_ids, batch_size), start=1):
            if index > 1:
                await asyncio.sleep(TENRAI_BATCH_GAP_SECONDS)
            params = {"ids": ",".join(str(i) for i in batch), "limit": str(len(batch))}

            def raw_get(params=params):
                # Timeout repeated per request so the value stays visible next to
                # the call that has to honour it, not only at client construction.
                return client.get(TENRAI_API_URL, params=params, timeout=TENRAI_TIMEOUT)

            started = time.monotonic()
            try:
                payload = await fetch_with_retry(
                    tenrai_bucket, raw_get, max_retries=TENRAI_MAX_RETRIES
                )
            except Exception as exc:  # per-chunk isolation, see module docstring
                failed_batches += 1
                logger.warning(
                    "batch %d/%d failed after %.1fs (%s); continuing with the rest",
                    index, total_batches, time.monotonic() - started, exc,
                )
                await asyncio.sleep(TENRAI_FAILURE_BACKOFF_SECONDS)
                continue

            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                failed_batches += 1
                logger.warning("Batch %d/%d returned no data list", index, total_batches)
                continue

            accepted = 0
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                mal_id = entry.get("mal_id")
                if not isinstance(mal_id, int) or mal_id not in requested:
                    # Wrong id: the server answered about a different title than we
                    # asked for. Dropping it is the whole point of keying by id.
                    continue
                found[mal_id] = entry
                accepted += 1

            logger.info(
                "batch %d/%d: %d/%d ids resolved in %.2fs",
                index, total_batches, accepted, len(batch), time.monotonic() - started,
            )

    if failed_batches:
        logger.warning(
            "%d/%d batches failed; %d entries resolved",
            failed_batches, total_batches, len(found),
        )
    return found


async def fetch_covers(
    mal_ids: Sequence[int],
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    batch_size: int = TENRAI_BATCH_SIZE,
) -> Dict[int, List[str]]:
    """`{mal_id: [cover_url, ...]}` for the ids that have an allowlisted cover."""
    entries = await fetch_entries(mal_ids, transport=transport, batch_size=batch_size)
    covers: Dict[int, List[str]] = {}
    for mal_id, entry in entries.items():
        urls = pick_cover_urls(entry)
        if urls:
            covers[mal_id] = urls
    return covers