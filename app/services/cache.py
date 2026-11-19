import logging
import redis.asyncio as redis
import json
import hashlib
from ..config import settings
from typing import Optional, Any, List, Set

logger = logging.getLogger("mitsu.cache")

#: How long a browser may reuse a catalogue response without asking again.
#:
#: This is a *transport* hint, not a second cache. The shared copy of a page
#: lives in Redis, and `invalidate_catalog_caches()` empties those namespaces on
#: every catalogue write, so an operator can always reach the truth. A browser
#: copy cannot be recalled, which is why the long `max-age` values this replaces
#: (900 s on trending/featured, 3600 s on detail/similar, 300 s on search) were a
#: liability and not a cache: they kept a stale row on screen for up to an hour
#: after a sync that had already updated it.
#:
#: A minute is the whole policy. The catalogue changes only when an operator
#: inserts titles by hand, so a one-minute window costs nothing measurable while
#: a five-second one only bought re-fetch chatter on back/forward. It also keeps
#: a shield over `/manga/{id}/similar`, whose cold path is a live similarity
#: calculation measured at ~3.5 s.
BROWSER_CACHE_SECONDS = 60

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

def generate_cache_key(prefix: str, data: Any) -> str:
    data_str = json.dumps(data, sort_keys=True)
    hash_obj = hashlib.md5(data_str.encode())
    return f"{prefix}:{hash_obj.hexdigest()}"

async def get_cached(key: str) -> Optional[Any]:
    try:
        val = await redis_client.get(key)
        if val:
            return json.loads(val)
    except Exception as e:
        logger.warning("Redis get error for key '%s': %s", key, e, exc_info=True)
    return None

async def set_cached(key: str, data: Any, ttl: int = 3600):
    try:
        await redis_client.set(key, json.dumps(data), ex=ttl)
    except Exception as e:
        logger.warning("Redis set error for key '%s': %s", key, e, exc_info=True)

# ==========================================
# ROULETTE REDIS CANDIDATE POOL SYSTEM
# ==========================================

async def push_roulette_pool(filter_hash: str, items: List[dict], ttl: int = 3600):
    """Pushes candidate JSON objects into Redis list roulette:pool:{filter_hash}"""
    if not items:
        return
    key = f"roulette:pool:{filter_hash}"
    try:
        encoded_items = [json.dumps(item) for item in items]
        await redis_client.rpush(key, *encoded_items)
        await redis_client.expire(key, ttl)
    except Exception as e:
        logger.warning("Redis push_roulette_pool error: %s", e)

async def pop_roulette_pool(filter_hash: str, count: int = 1) -> List[dict]:
    """Pops up to `count` items from Redis list roulette:pool:{filter_hash}"""
    key = f"roulette:pool:{filter_hash}"
    results = []
    try:
        for _ in range(count):
            val = await redis_client.lpop(key)
            if isinstance(val, (str, bytes)):
                results.append(json.loads(val))
            else:
                break
    except Exception as e:
        logger.warning("Redis pop_roulette_pool error: %s", e)
    return results

async def get_roulette_pool_size(filter_hash: str) -> int:
    """Returns the current number of queued items in roulette:pool:{filter_hash}"""
    key = f"roulette:pool:{filter_hash}"
    try:
        return await redis_client.llen(key)
    except Exception as e:
        logger.warning("Redis get_roulette_pool_size error: %s", e)
        return 0

async def acquire_refill_lock(filter_hash: str, ttl: int = 10) -> bool:
    """Concurrency lock to prevent multiple workers from refilling the same pool simultaneously"""
    lock_key = f"roulette:refill-lock:{filter_hash}"
    try:
        acquired = await redis_client.set(lock_key, "locked", nx=True, ex=ttl)
        return bool(acquired)
    except Exception as e:
        logger.warning("Redis acquire_refill_lock error: %s", e)
        return False

async def release_refill_lock(filter_hash: str):
    """Releases the refill concurrency lock"""
    lock_key = f"roulette:refill-lock:{filter_hash}"
    try:
        await redis_client.delete(lock_key)
    except Exception as e:
        logger.warning("Redis release_refill_lock error: %s", e)

async def add_session_seen(session_id: str, manga_ids: List[int], ttl: int = 86400):
    """Stores shown manga IDs into Redis set roulette:seen:{session_id}"""
    if not session_id or not manga_ids:
        return
    key = f"roulette:seen:{session_id}"
    try:
        await redis_client.sadd(key, *manga_ids)
        await redis_client.expire(key, ttl)
    except Exception as e:
        logger.warning("Redis add_session_seen error: %s", e)

async def get_session_seen(session_id: str) -> Set[int]:
    """Retrieves server-authoritative set of seen manga IDs for a session"""
    if not session_id:
        return set()
    key = f"roulette:seen:{session_id}"
    try:
        members = await redis_client.smembers(key)
        return {int(m) for m in members if m}
    except Exception as e:
        logger.warning("Redis get_session_seen error: %s", e)
        return set()


# Catalog writes invalidate these namespaces. TTL remains the backstop.
_CATALOG_CACHE_PATTERNS = (
    "recommend:*",
    "search:*",
    # The spelling vocabulary is derived from the catalog too (ARCH-14): it used
    # to be a process global that no sync could refresh.
    "catalog:vocab:*",
    "manga:featured_mix:*",
    "manga:trending:*",
    "manga:detail:*",
    "manga:similar:*",
    "roulette:pool:*",
)


async def invalidate_catalog_caches() -> int:
    """Delete recommendation/search/roulette keys after a catalog change.

    Uses SCAN, not KEYS, so a large Redis instance is not blocked.
    """
    deleted = 0
    try:
        for pattern in _CATALOG_CACHE_PATTERNS:
            batch: list[str] = []
            async for key in redis_client.scan_iter(match=pattern, count=500):
                batch.append(key)
                if len(batch) >= 500:
                    deleted += await redis_client.delete(*batch)
                    batch.clear()
            if batch:
                deleted += await redis_client.delete(*batch)
    except Exception as e:
        logger.warning("Catalog cache invalidation failed: %s", e, exc_info=True)
    return deleted
