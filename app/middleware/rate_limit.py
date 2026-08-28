import time
import logging
from collections import defaultdict
from typing import Dict, List, Optional
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from ..config import settings

logger = logging.getLogger("mitsu.rate_limit")

class SlidingWindowRateLimiter:
    """
    Distributed Sliding Window Rate Limiter using Redis sorted sets (ZSET),
    with automatic in-memory fallback if Redis is unavailable.
    """
    def __init__(self, requests_per_minute: int = 60, window_seconds: int = 60):
        self.requests_per_minute = requests_per_minute
        self.window_seconds = window_seconds
        self.memory_store: Dict[str, List[float]] = defaultdict(list)
        self.redis_client = None
        self._init_redis()

    def _init_redis(self):
        try:
            import redis
            self.redis_client = redis.Redis.from_url(
                settings.REDIS_URL, 
                decode_responses=True,
                socket_timeout=1.0
            )
            self.redis_client.ping()
            logger.info("Rate limiter successfully connected to Redis.")
        except Exception as e:
            logger.warning(f"Redis unavailable for rate limiter ({e}). Using in-memory sliding window fallback.")
            self.redis_client = None

    async def is_rate_limited(self, client_ip: str, route: str) -> tuple[bool, int, int]:
        """
        Check if request exceeds sliding-window limit.
        Returns: (is_limited, remaining_requests, reset_seconds)
        """
        now = time.time()
        window_start = now - self.window_seconds
        key = f"rate_limit:{route}:{client_ip}"

        if self.redis_client:
            try:
                pipe = self.redis_client.pipeline()
                # Clean old entries
                pipe.zremrangebyscore(key, 0, window_start)
                # Add current request timestamp
                pipe.zadd(key, {f"{now}": now})
                # Count total requests in window
                pipe.zcard(key)
                # Set TTL on key
                pipe.expire(key, self.window_seconds)
                results = pipe.execute()

                request_count = results[2]
                remaining = max(0, self.requests_per_minute - request_count)
                is_limited = request_count > self.requests_per_minute
                return is_limited, remaining, self.window_seconds
            except Exception as err:
                logger.warning(f"Redis rate limit error ({err}), falling back to in-memory store.")
                self.redis_client = None

        # Fallback: In-memory sliding window calculation
        timestamps = self.memory_store[key]
        # Remove expired timestamps
        self.memory_store[key] = [ts for ts in timestamps if ts > window_start]
        self.memory_store[key].append(now)

        request_count = len(self.memory_store[key])
        remaining = max(0, self.requests_per_minute - request_count)
        is_limited = request_count > self.requests_per_minute
        return is_limited, remaining, self.window_seconds


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI Middleware enforcing sliding-window rate limiting on critical endpoints (/recommend, /search, /roulette).
    """
    def __init__(self, app, requests_per_minute: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.limiter = SlidingWindowRateLimiter(requests_per_minute, window_seconds)
        self.rate_limited_routes = {"/recommend", "/search", "/roulette", "/roulette/batch"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # Only rate-limit specific computationally heavy search / recommendation API routes
        if any(path.startswith(route) for route in self.rate_limited_routes):
            client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "127.0.0.1")
            client_ip = client_ip.split(",")[0].strip()

            is_limited, remaining, reset_secs = await self.limiter.is_rate_limited(client_ip, path)

            if is_limited:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded. Too many requests. Please wait before retrying.",
                        "retry_after": reset_secs
                    },
                    headers={
                        "Retry-After": str(reset_secs),
                        "X-RateLimit-Limit": str(self.limiter.requests_per_minute),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset_secs)
                    }
                )

            response: Response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self.limiter.requests_per_minute)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset_secs)
            return response

        return await call_next(request)
