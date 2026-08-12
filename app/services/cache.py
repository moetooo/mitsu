import redis.asyncio as redis
import json
import hashlib
from ..config import settings
from typing import Optional, Any

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
