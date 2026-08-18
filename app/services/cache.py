import redis.asyncio as redis
import json
import hashlib
from ..config import settings
from typing import Optional, Any, List, Set

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

def generate_cache_key(prefix: str, data: Any) -> str:
    data_str = json.dumps(data, sort_keys=True)
    hash_obj = hashlib.md5(data_str.encode())
    return f"{prefix}:{hash_obj.hexdigest()}"

async def get_cached(key: str) -> Optional[dict]:
    try:
        val = await redis_client.get(key)
        if val:
            return json.loads(val)
    except Exception as e:
        print(f"Redis get error: {e}")
    return None

async def set_cached(key: str, data: dict, ttl: int = 3600):
    try:
        await redis_client.set(key, json.dumps(data), ex=ttl)
    except Exception as e:
        print(f"Redis set error: {e}")

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
        print(f"Redis push_roulette_pool error: {e}")

async def pop_roulette_pool(filter_hash: str, count: int = 1) -> List[dict]:
    """Pops up to `count` items from Redis list roulette:pool:{filter_hash}"""
    key = f"roulette:pool:{filter_hash}"
    results = []
    try:
        for _ in range(count):
            val = await redis_client.lpop(key)
            if val:
                results.append(json.loads(val))
            else:
                break
    except Exception as e:
        print(f"Redis pop_roulette_pool error: {e}")
    return results

async def get_roulette_pool_size(filter_hash: str) -> int:
    """Returns the current number of queued items in roulette:pool:{filter_hash}"""
    key = f"roulette:pool:{filter_hash}"
    try:
        return await redis_client.llen(key)
    except Exception as e:
        print(f"Redis get_roulette_pool_size error: {e}")
        return 0

async def acquire_refill_lock(filter_hash: str, ttl: int = 10) -> bool:
    """Concurrency lock to prevent multiple workers from refilling the same pool simultaneously"""
    lock_key = f"roulette:refill-lock:{filter_hash}"
    try:
        acquired = await redis_client.set(lock_key, "locked", nx=True, ex=ttl)
        return bool(acquired)
    except Exception as e:
        print(f"Redis acquire_refill_lock error: {e}")
        return False

async def release_refill_lock(filter_hash: str):
    """Releases the refill concurrency lock"""
    lock_key = f"roulette:refill-lock:{filter_hash}"
    try:
        await redis_client.delete(lock_key)
    except Exception as e:
        print(f"Redis release_refill_lock error: {e}")

async def add_session_seen(session_id: str, manga_ids: List[int], ttl: int = 86400):
    """Stores shown manga IDs into Redis set roulette:seen:{session_id}"""
    if not session_id or not manga_ids:
        return
    key = f"roulette:seen:{session_id}"
    try:
        await redis_client.sadd(key, *manga_ids)
        await redis_client.expire(key, ttl)
    except Exception as e:
        print(f"Redis add_session_seen error: {e}")

async def get_session_seen(session_id: str) -> Set[int]:
    """Retrieves server-authoritative set of seen manga IDs for a session"""
    if not session_id:
        return set()
    key = f"roulette:seen:{session_id}"
    try:
        members = await redis_client.smembers(key)
        return {int(m) for m in members if m}
    except Exception as e:
        print(f"Redis get_session_seen error: {e}")
        return set()
