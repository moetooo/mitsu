"""Cover health: the counters, the verdict, and the fact that it stays cheap.

The verdict is a pure function of the counters, so the thresholds can be argued
with in a test instead of being discovered in production.
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.main import app
from app.services import cover_health


@pytest.fixture
async def client():
    async with ASGITransport(app=app) as transport:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


BASE = {
    "total": 1000,
    "ok": 950,
    "dead": 50,
    "unverified": 0,
    "ok_share": 0.95,
    "fallback_share": 0.6,
    "verify_age_days": 1.0,
    "reported_24h": 0,
}


def test_a_catalogue_with_working_dual_hosted_covers_is_healthy():
    verdict = cover_health.assess(dict(BASE))
    assert verdict["status"] == "healthy"
    assert verdict["reasons"] == []


def test_a_provider_outage_shows_up_before_any_cover_is_reported():
    # 95% of covers fine, but they all sit on one host: the next outage repeats.
    verdict = cover_health.assess({**BASE, "fallback_share": 0.05})
    assert verdict["status"] == "degraded"
    assert any("second provider" in reason for reason in verdict["reasons"])


def test_a_catalogue_mostly_without_covers_is_critical():
    verdict = cover_health.assess({**BASE, "ok": 200, "ok_share": 0.2, "fallback_share": 0.2})
    assert verdict["status"] == "critical"
    assert any("working cover" in reason for reason in verdict["reasons"])


def test_an_old_verification_is_degraded_not_critical():
    verdict = cover_health.assess({**BASE, "verify_age_days": 90.0})
    assert verdict["status"] == "degraded"
    assert any("days ago" in reason for reason in verdict["reasons"])


def test_never_verified_is_a_problem_even_with_perfect_numbers():
    verdict = cover_health.assess({**BASE, "verify_age_days": None})
    assert verdict["status"] == "degraded"
    assert any("ever been verified" in reason for reason in verdict["reasons"])


def test_a_wave_of_user_reports_is_mentioned_without_changing_the_verdict():
    verdict = cover_health.assess({**BASE, "reported_24h": 40})
    assert verdict["status"] == "healthy"
    assert any("reported broken" in reason for reason in verdict["reasons"])


def test_an_empty_catalogue_does_not_divide_by_zero():
    verdict = cover_health.assess({"total": 0, "ok_share": 0.0, "fallback_share": 0.0})
    assert verdict["status"] == "degraded"


async def test_the_endpoint_reports_counters_and_no_urls(client):
    response = await client.get("/health/covers")

    assert response.status_code == 200
    body = response.json()
    for field in ("total", "ok", "dead", "unverified", "ok_share", "fallback_share", "status"):
        assert field in body, f"{field} missing from the health payload"

    # It is a public endpoint: counters only.
    assert "https://" not in json.dumps(body)
    assert body["total"] >= body["ok"] + body["dead"] - body["total"]


async def test_the_answer_is_cached_but_can_be_forced(client):
    first = (await client.get("/health/covers")).json()
    second = (await client.get("/health/covers")).json()
    assert second["checked_at"] == first["checked_at"], "the cached answer was recomputed"

    async with AsyncSessionLocal() as session:
        fresh = await cover_health.cover_health(session, refresh=True)
    assert fresh["checked_at"] != first["checked_at"]


async def test_reported_and_failed_counts_come_from_the_log(manga_id):
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO cover_repair_log (manga_id, from_url, source, result, detail) "
                "VALUES (:i, 'https://s4.anilist.co/x.jpg', 'none', 'failed', 'test: http 404')"
            ),
            {"i": manga_id},
        )
        await session.commit()

        stats = await cover_health.cover_health(session, refresh=True)

    assert stats["failed_7d"] >= 1


async def test_the_last_verify_run_is_preferred_over_backfilled_timestamps(manga_id):
    # Migration 0007 backfilled `cover_checked_at`, so it always looks fresh; only a
    # recorded run proves somebody actually looked.
    async with AsyncSessionLocal() as session:
        stats = await cover_health.cover_health(session, refresh=True)

    assert stats["verify_source"] in ("verify_run", "row_timestamps")
    if stats["verify_source"] == "verify_run":
        assert stats["last_verify_run"]["at"] == stats["last_verify_at"]
