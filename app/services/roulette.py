"""Discovery Roulette: sampling, the Redis pool, and the draw (ARCH-10).

Split out of `retrieval.py`. Roulette is a different retrieval problem from the
similarity search: it wants an unpredictable, catalogue-wide, repeatable
*absence* of already-seen titles, not a ranked page. That is why the sampler
takes evenly spaced id ranges instead of `ORDER BY random()`, and why the pool
is drained in bounded rounds rather than one pop.

`generate_filter_hash` comes from `query_filters`: the Redis pool key and the
SQL filters must be derived from the same filter set.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import RecommendFilters
from . import cache
from .diversity import apply_diversity_filtering
from .query_filters import apply_filter_criteria, generate_filter_hash
from .safety import safety_filter


ROULETTE_POOL_TARGET = 50
ROULETTE_REFILL_THRESHOLD = 15


async def sample_candidates_from_db(
    session: AsyncSession,
    filters: Optional[RecommendFilters] = None,
    sample_limit: int = 150
) -> List[Any]:
    """Sample candidates from across the whole catalogue, cheaply.

    Ids follow ingestion order, so one contiguous block of them is one ingest
    batch, and therefore one source. Measured: 76% of a draw carried a MangaDex
    id against a 14% catalogue baseline, and every draw came from a single ingest
    day. The year spread did not change -- this catalogue is 99.8% 2000+ -- so
    source, not era, is what the block was skewing.

    This takes one short range from each of several evenly spaced slices of the
    id space instead. Each range is an index range scan, so the work is set by
    `ROULETTE_SAMPLE_BLOCKS` and the per-block width -- not by the table size.
    `ORDER BY random()` was the obvious alternative and was rejected: its cost
    grows with the catalogue and it would silently become the slowest query here
    as the table grows.
    """
    where_clauses = ["cover_image_url IS NOT NULL"]

    allow_nsfw = filters.nsfw if filters and filters.nsfw is not None else False
    nsfw_predicate = safety_filter(allow_nsfw)
    if nsfw_predicate:
        where_clauses.append(nsfw_predicate)

    rand_seed = f"seed_{random.randint(1, 999999999)}_{time.time()}"
    params: Dict[str, Any] = {
        "limit": sample_limit,
        "seed": rand_seed,
    }

    apply_filter_criteria(filters, where_clauses, params)

    where_str = " AND ".join(where_clauses)

    columns = """
          id, anilist_id, mal_id, mangadex_id, title_romaji, title_english, title_native,
          synopsis, genres, tags, status, start_year, chapters, volumes,
          average_score, popularity, cover_image_url, banner_image, site_url"""

    bounds = (await session.execute(text(
        "SELECT COALESCE(MIN(id), 0) AS lo, COALESCE(MAX(id), 0) AS hi FROM manga"
    ))).one()
    lo, hi = int(bounds.lo), int(bounds.hi)

    blocks = max(1, settings.ROULETTE_SAMPLE_BLOCKS)
    span = max(1, (sample_limit * max(1, settings.ROULETTE_SAMPLE_OVERSCAN)) // blocks)

    # One random start per slice, so a draw spans the catalogue instead of an era.
    slot = max(1, (hi - lo + 1) // blocks)
    starts = []
    for i in range(blocks):
        slot_lo = lo + i * slot
        start = slot_lo + random.randint(0, max(0, slot - span))
        starts.append(min(start, hi))

    params["starts"] = starts
    params["span"] = span

    # ORDER BY hashtext() sorts only the sampled ranges (blocks * span rows), so it
    # picks a random subset of them without sorting the table.
    sql = text(f"""
        WITH starts AS (SELECT unnest(CAST(:starts AS bigint[])) AS s)
        SELECT {columns}
        FROM manga, starts
        WHERE manga.id >= starts.s
          AND manga.id < starts.s + :span
          AND {where_str}
        ORDER BY hashtext(manga.id::text || :seed) DESC
        LIMIT :limit;
    """)

    result = await session.execute(sql, params)
    rows = list(result.all())

    if len(rows) < max(1, sample_limit // 4):
        # Selective filters can miss every sampled range. Only now pay for the
        # whole-table hash ordering, which is what the old path always did.
        fb = text(f"""
            SELECT {columns}
            FROM manga
            WHERE {where_str}
            ORDER BY hashtext(id::text || :seed) DESC
            LIMIT :limit;
        """)
        result = await session.execute(fb, params)
        rows = list(result.all())

    random.shuffle(rows)
    return rows


async def refill_roulette_pool(filters: Optional[RecommendFilters], session_id: Optional[str] = None):
    """Background pool refiller: fetches DB candidates, applies diversity, and pushes to Redis"""
    filter_hash = generate_filter_hash(filters)

    # Concurrency Lock: Prevent multiple background workers from refilling simultaneously
    locked = await cache.acquire_refill_lock(filter_hash, ttl=10)
    if not locked:
        return

    try:
        seen_set = set()
        if session_id:
            seen_set = await cache.get_session_seen(session_id)

        from ..db import AsyncSessionLocal
        async with AsyncSessionLocal() as bg_session:
            db_rows = await sample_candidates_from_db(bg_session, filters=filters, sample_limit=150)
            diverse_items = apply_diversity_filtering(db_rows, exclude_ids=seen_set, max_target=ROULETTE_POOL_TARGET)

            if diverse_items:
                random.shuffle(diverse_items)
                await cache.push_roulette_pool(filter_hash, diverse_items, ttl=1800)
    except Exception as e:
        pass
    finally:
        await cache.release_refill_lock(filter_hash)


async def retrieve_roulette_manga(
    session: AsyncSession,
    filters: Optional[RecommendFilters] = None,
    seen_ids: Optional[List[int]] = None,
    pool_limit: int = 1,
    session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Production roulette retriever serving instant results from Redis pool or fast DB fallback"""
    filter_hash = generate_filter_hash(filters)

    # 1. Combine client seen_ids and server session seen set
    server_seen = await cache.get_session_seen(session_id) if session_id else set()
    combined_seen = set(seen_ids or []).union(server_seen)

    # 2. Check current Redis candidate pool size
    pool_size = await cache.get_roulette_pool_size(filter_hash)

    # 3. Asynchronously trigger background pool refill if below threshold and active session
    if pool_size < ROULETTE_REFILL_THRESHOLD and session_id:
        asyncio.create_task(refill_roulette_pool(filters, session_id))

    # 4. Attempt popping from Redis candidate pool.
    #
    # This popped exactly `max(pool_limit, 4)` items. If all of them happened to
    # be in the session's seen set, the loop gave up and went to the database --
    # discarding a pool that might still hold dozens of unseen rows. The pool is
    # drained by LPOP, so those unseen rows were simply thrown away.
    # It now pops in bounded rounds until it has enough unseen rows, the pool is
    # empty, or the budget is spent.
    results = []
    if pool_size > 0:
        wanted = max(pool_limit, 4)
        budget = max(wanted * 4, ROULETTE_POOL_TARGET)
        unseen_items: List[dict] = []
        popped_total = 0
        while len(unseen_items) < pool_limit and popped_total < budget:
            round_size = min(wanted, budget - popped_total)
            popped_items = await cache.pop_roulette_pool(filter_hash, count=round_size)
            if not popped_items:
                break
            popped_total += len(popped_items)
            unseen_items.extend(
                item for item in popped_items if item["id"] not in combined_seen
            )
        if unseen_items:
            random.shuffle(unseen_items)
            results = unseen_items[:pool_limit]

    # 5. Fallback: If Redis empty or popped items were seen, query DB cleanly with dynamic seeds
    if not results:
        db_rows = await sample_candidates_from_db(session, filters=filters, sample_limit=80)
        results = apply_diversity_filtering(db_rows, exclude_ids=combined_seen, max_target=pool_limit)
        if not results:
            # Every row in this draw was already seen. Draw again before relaxing:
            # the sample is 80 rows out of ~95k, so a second draw almost always
            # contains unseen ones, whereas re-filtering the same 80 rows with an
            # empty exclusion set can only re-serve something already shown.
            retry_rows = await sample_candidates_from_db(session, filters=filters, sample_limit=80)
            results = apply_diversity_filtering(retry_rows, exclude_ids=combined_seen, max_target=pool_limit)
        if not results and db_rows:
            # Absolute fallback: the catalogue really is exhausted for this
            # session, so repeat rather than return nothing.
            results = apply_diversity_filtering(db_rows, exclude_ids=set(), max_target=pool_limit)
        if results:
            random.shuffle(results)

    # 6. Update server-authoritative seen set in Redis
    if results and session_id:
        served_ids = [r["id"] for r in results]
        await cache.add_session_seen(session_id, served_ids)

    return results
