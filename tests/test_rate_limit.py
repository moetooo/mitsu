"""Behaviour tests for the rate limiter's Redis-down path (QA-17, API-07).

The limiter is the only thing standing between a burst and `/recommend`,
`/search` and `/roulette`. Its documented behaviour is a sliding window in Redis
with an in-memory fallback, so the two things that must never happen are:

* Redis being unavailable meaning *no* limit at all,
* a Redis error mid-request turning into a 500 instead of a fallback.

Both are tested with the Redis handle forced to None or to a stub that raises, so
no real Redis is required.
"""

from __future__ import annotations

import pytest

from app.middleware.rate_limit import RateLimitMiddleware, SlidingWindowRateLimiter


def limiter_without_redis(requests_per_minute: int = 2) -> SlidingWindowRateLimiter:
    limiter = SlidingWindowRateLimiter(requests_per_minute=requests_per_minute, window_seconds=60)
    limiter.redis_client = None
    return limiter


class ExplodingRedis:
    """A Redis handle that fails the way a dead connection does: on execute()."""

    def pipeline(self) -> "ExplodingPipeline":
        return ExplodingPipeline()


class ExplodingPipeline:
    def zremrangebyscore(self, *args, **kwargs):
        return self

    def zadd(self, *args, **kwargs):
        return self

    def zcard(self, *args, **kwargs):
        return self

    def expire(self, *args, **kwargs):
        return self

    def execute(self):
        raise ConnectionError("redis connection reset")


@pytest.mark.asyncio
async def test_in_memory_fallback_still_enforces_the_limit():
    limiter = limiter_without_redis(requests_per_minute=2)

    first = await limiter.is_rate_limited("203.0.113.7", "/search")
    second = await limiter.is_rate_limited("203.0.113.7", "/search")
    third = await limiter.is_rate_limited("203.0.113.7", "/search")

    assert first == (False, 1, 60)
    assert second == (False, 0, 60)
    assert third[0] is True          # over the cap -> limited
    assert third[1] == 0


@pytest.mark.asyncio
async def test_limit_is_per_client_and_per_route():
    limiter = limiter_without_redis(requests_per_minute=1)

    await limiter.is_rate_limited("203.0.113.7", "/search")
    over = await limiter.is_rate_limited("203.0.113.7", "/search")
    other_client = await limiter.is_rate_limited("203.0.113.8", "/search")
    other_route = await limiter.is_rate_limited("203.0.113.7", "/recommend")

    assert over[0] is True
    assert other_client[0] is False
    assert other_route[0] is False


@pytest.mark.asyncio
async def test_redis_error_falls_back_instead_of_raising():
    limiter = SlidingWindowRateLimiter(requests_per_minute=5, window_seconds=60)
    limiter.redis_client = ExplodingRedis()

    is_limited, remaining, _reset = await limiter.is_rate_limited("203.0.113.9", "/roulette")

    assert is_limited is False
    assert remaining == 4            # the in-memory store counted this request
    assert limiter.redis_client is None  # the dead handle is dropped once


@pytest.mark.asyncio
async def test_expired_timestamps_leave_the_window():
    limiter = limiter_without_redis(requests_per_minute=1)
    key = "rate_limit:/search:203.0.113.10"

    await limiter.is_rate_limited("203.0.113.10", "/search")
    assert (await limiter.is_rate_limited("203.0.113.10", "/search"))[0] is True

    # Age the stored timestamps past the window: the client is allowed again.
    limiter.memory_store[key] = [ts - 120 for ts in limiter.memory_store[key]]

    assert (await limiter.is_rate_limited("203.0.113.10", "/search"))[0] is False


@pytest.mark.asyncio
async def test_middleware_only_limits_the_expensive_routes():
    class DummyApp:
        pass

    middleware = RateLimitMiddleware(DummyApp())

    assert middleware.rate_limited_routes == {"/recommend", "/search", "/roulette", "/roulette/batch"}
    # /health and the catalogue endpoints must never be throttled behind the app.
    assert not any("/health".startswith(route) for route in middleware.rate_limited_routes)
    assert not any("/manga".startswith(route) for route in middleware.rate_limited_routes)
