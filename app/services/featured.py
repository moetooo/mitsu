"""The featured rail, served from the catalogue (ARCH-07).

The router used to hold four ORM queries, a seeded shuffle and the badge
assignment, all in the request handler: 120 lines of catalogue reading in the
layer that is supposed to only translate HTTP. The queries moved here; the
router now validates its arguments, calls `get_featured()` and wraps the payload.

The mix is three curated pools plus a fallback, picked with a `random.Random`
seeded by the current 15-minute slot. That seed is what makes a rail that looks
hand-picked today still look hand-picked on the next request, while rotating on
its own without a scheduler or a stored snapshot.

Every pool goes through `services/safety.py` like every other public read; the
old hand-written predicates here were one of the reasons that module exists.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence, Tuple

from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..db_models import Manga
from .cache import get_cached, set_cached
from .safety import safety_filter

logger = logging.getLogger("mitsu.services.featured")

#: Rotating on a 15-minute boundary keeps the rail stable across a page session
#: (and across a cache miss) without a scheduled job.
SLOT_MINUTES = 15

CACHE_TTL_SECONDS = 900

#: How many rows each pool offers before the seeded pick chooses from it.
POOL_SIZE = 25

#: (pool, badge, how many cards that pool contributes).
POOL_QUOTA: Tuple[Tuple[str, int], ...] = (
    ("popular", 2),
    ("underrated", 2),
    ("acclaimed", 2),
)

FALLBACK_BADGE = "Featured Title"

POOL_BADGES = {
    "popular": "Popular Pick",
    "underrated": "Hidden Gem",
    "acclaimed": "Critically Acclaimed",
}


def slot_key(now: datetime | None = None) -> str:
    """`2026-11-14-19-15` -- stable inside a 15-minute window."""
    now = now or datetime.now(timezone.utc)
    slot_minute = (now.minute // SLOT_MINUTES) * SLOT_MINUTES
    return f"{now.strftime('%Y-%m-%d-%H')}-{slot_minute:02d}"


def cache_key(slot: str, limit: int) -> str:
    return f"manga:featured_mix:{slot}:{limit}"


def _per_pool_queries() -> Dict[str, Any]:
    """One statement per pool. Ordered so the seed picks from the best rows first."""
    return {
        "popular": (
            select(Manga)
            .options(defer(Manga.embedding))
            .where(Manga.cover_image_url.isnot(None), sa_text(safety_filter()))
            .order_by(Manga.popularity.desc().nullslast())
            .limit(POOL_SIZE)
        ),
        "underrated": (
            select(Manga)
            .options(defer(Manga.embedding))
            .where(
                Manga.cover_image_url.isnot(None),
                Manga.average_score >= 78,
                (Manga.popularity < 500) | (Manga.popularity.is_(None)),
                sa_text(safety_filter()),
            )
            .order_by(Manga.average_score.desc().nullslast())
            .limit(POOL_SIZE)
        ),
        "acclaimed": (
            select(Manga)
            .options(defer(Manga.embedding))
            .where(
                Manga.cover_image_url.isnot(None),
                Manga.average_score >= 84,
                sa_text(safety_filter()),
            )
            .order_by(Manga.average_score.desc().nullslast())
            .limit(POOL_SIZE)
        ),
        "fallback": (
            select(Manga)
            .options(defer(Manga.embedding))
            .where(Manga.cover_image_url.isnot(None), sa_text(safety_filter()))
            .limit(2 * POOL_SIZE)
        ),
    }


async def load_pools(session: AsyncSession) -> Dict[str, List[Manga]]:
    """Every pool in one round of queries. No cache, no shuffle."""
    pools: Dict[str, List[Manga]] = {}
    for name, stmt in _per_pool_queries().items():
        pools[name] = list((await session.execute(stmt)).scalars().all())
    return pools


def select_items(
    pools: Dict[str, Sequence[Manga]],
    limit: int,
    rng: random.Random,
) -> List[Tuple[Manga, str]]:
    """Pick the rail: the quota from each pool, then fill from the fallback.

    Pure and seeded on purpose -- the same pools, limit and RNG always produce
    the same rail, so a cache miss and a cache hit agree with each other.
    """
    selected: List[Tuple[Manga, str]] = []
    seen: set[Any] = set()

    def pick(pool_name: str, count: int) -> None:
        badge = POOL_BADGES[pool_name]
        shuffled = list(pools.get(pool_name, ()))
        rng.shuffle(shuffled)
        picked = 0
        for manga in shuffled:
            if manga.id in seen:
                continue
            seen.add(manga.id)
            selected.append((manga, badge))
            picked += 1
            if picked >= count:
                break

    for pool_name, count in POOL_QUOTA:
        pick(pool_name, count)

    if len(selected) < limit:
        fallback = list(pools.get("fallback", ()))
        rng.shuffle(fallback)
        for manga in fallback:
            if manga.id in seen:
                continue
            seen.add(manga.id)
            selected.append((manga, FALLBACK_BADGE))
            if len(selected) >= limit:
                break

    rng.shuffle(selected)
    return selected


def payload_for(manga: Manga, badge: str) -> Dict[str, Any]:
    return {
        "id": manga.id,
        "anilist_id": manga.anilist_id,
        "mal_id": manga.mal_id,
        "title": manga.title_english or manga.title_romaji or manga.title_native or "Unknown",
        "cover_image_url": manga.cover_image_url,
        "banner_image": manga.banner_image,
        "synopsis": manga.synopsis,
        "genres": manga.genres,
        "tags": manga.tags,
        "status": manga.status,
        "start_year": manga.start_year,
        "chapters": manga.chapters,
        "volumes": manga.volumes,
        "average_score": manga.average_score,
        # A curated row answers no query, so it has no similarity to report.
        # This used to be a hardcoded 0.95, rendered as a fabricated "95% match".
        "similarity_score": None,
        "llm_reasoning": None,
        "is_nsfw": manga.is_nsfw,
        "category_badge": badge,
    }


async def get_featured(session: AsyncSession, limit: int = 6) -> List[Dict[str, Any]]:
    """Cached featured rail, as plain dicts ready for `RecommendationResult`."""
    slot = slot_key()
    key = cache_key(slot, limit)
    cached = await get_cached(key)
    if cached is not None:
        return cached

    pools = await load_pools(session)
    # The seed is the slot, so the pick is reproducible inside the window.
    selected = select_items(pools, limit, random.Random(slot))
    payload = [payload_for(manga, badge) for manga, badge in selected]

    await set_cached(key, payload, ttl=CACHE_TTL_SECONDS)
    logger.info("Featured rail built from the catalogue (%d rows, slot=%s)", len(payload), slot)
    return payload
