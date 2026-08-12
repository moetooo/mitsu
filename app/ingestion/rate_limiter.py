import asyncio
import time
import random
import httpx
from typing import Callable, Any

class RateLimitError(Exception):
    def __init__(self, retry_after=None):
        self.retry_after = retry_after

class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int = 1):
        self.rate = rate_per_sec
        self.tokens = burst
        self.max_tokens = burst
        self.last_check = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_check
            self.tokens = min(self.max_tokens, self.tokens + elapsed * self.rate)
            self.last_check = now
            if self.tokens < 1:
                wait = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait)
                self.tokens = 0
            else:
                self.tokens -= 1

# Shared singleton bucket instances
anilist_bucket = TokenBucket(rate_per_sec=0.5, burst=2)
jikan_bucket = TokenBucket(rate_per_sec=0.9, burst=1)
mangadex_bucket = TokenBucket(rate_per_sec=2, burst=3)

async def fetch_with_retry(bucket: TokenBucket, fetch_fn: Callable[..., Any], *args, max_retries: int = 6, **kwargs):
    for attempt in range(max_retries):
        await bucket.acquire()
        try:
            response = await fetch_fn(*args, **kwargs)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                raise RateLimitError(retry_after)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.RequestError, RateLimitError) as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code != 429:
                # Re-raise 4xx and 5xx errors immediately (e.g. 504 Gateway Timeout when MAL bridge is down)
                if e.response.status_code in (400, 404, 500, 502, 503, 504):
                    raise e
            base_delay = 2 ** attempt
            jitter = random.uniform(0, 1)
            retry_after_val = float(getattr(e, "retry_after", 0) or 0)
            delay = max(base_delay + jitter, retry_after_val)
            print(f"[RateLimiter] Exception ({e}). Retrying attempt {attempt + 1}/{max_retries} in {delay:.2f}s...")
            await asyncio.sleep(delay)
    raise RuntimeError(f"Exceeded retries for {fetch_fn.__name__}")
