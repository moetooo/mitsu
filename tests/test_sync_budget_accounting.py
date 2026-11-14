"""The MangaDex budget must account for exactly the requests the run made.

The review found two accounting bugs that this pins down:

* a run reported a `request_usage` snapshot that could not be reconciled with the
  requests it actually made, and
* a dry run consumed real provider budget, so a rehearsal could starve the real
  run later in the day.

Both are checked the same way: count the provider calls the run performs, then
compare the daily `sync_api_usage` counter delta against them.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select, text

from app.db import AsyncSessionLocal
from app.db_models import Manga, SyncApiUsage
from app.core import budget as budget_module
from app.sync import service as sync_service

# This module seeds and truncates `manga`, so it only runs against the database
# the suite created for itself. A catalog supplied through
# MITSU_TEST_DATABASE_URL (tests/conftest.py) is shared and never wiped.
pytestmark = pytest.mark.skipif(
    bool(os.environ.get("MITSU_TEST_DATABASE_URL")),
    reason="seeds and truncates its own database; run without MITSU_TEST_DATABASE_URL",
)


async def _mangadex_used() -> int:
    async with AsyncSessionLocal() as session:
        day = await budget_module.db_utc_day(session)
        used = await session.scalar(
            select(SyncApiUsage.requests).where(
                SyncApiUsage.day == day, SyncApiUsage.source == "mangadex"
            )
        )
        return int(used or 0)


async def _seed_linkless_rows(count: int = 2) -> None:
    """Rows that only the MangaDex link pass touches.

    They carry a `mangadex_id` but no AniList/MAL id, which is exactly the
    selector `_run_mangadex_links` uses, so the run spends one request per row.
    """
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE manga RESTART IDENTITY CASCADE"))
        for index in range(count):
            session.add(
                Manga(
                    title_english=f"Linkless {index}",
                    title_romaji=f"Linkless {index}",
                    mangadex_id=f"md-budget-{index}",
                    is_nsfw=False,
                )
            )
        await session.commit()


def _fake_fetcher(calls: list[str]):
    async def fetch(mangadex_id: str) -> dict:
        calls.append(mangadex_id)
        return {"id": mangadex_id, "attributes": {"links": {}}}

    return fetch


@pytest.mark.asyncio
async def test_full_sync_request_usage_equals_mangadex_budget_delta(monkeypatch):
    await _seed_linkless_rows(2)
    before = await _mangadex_used()
    calls: list[str] = []
    monkeypatch.setattr(sync_service, "fetch_mangadex_detail", _fake_fetcher(calls))

    summary = await sync_service.run_sync(
        mode="scheduled",
        dry_run=False,
        include_anilist=False,
        include_mangadex=True,
        generate_embeddings=False,
    )

    after = await _mangadex_used()
    assert summary["status"] in {"success", "partial"}, summary["errors"]
    assert len(calls) == 2, "the run should fetch exactly the two seeded rows"
    assert after - before == len(calls), "budget delta must equal real requests made"
    assert summary["request_usage"]["mangadex"]["used"] == after
    assert summary["request_usage"]["mangadex"]["used"] - before == len(calls)


@pytest.mark.asyncio
async def test_dry_run_makes_the_same_requests_without_spending_budget(monkeypatch):
    await _seed_linkless_rows(2)
    before = await _mangadex_used()
    calls: list[str] = []
    monkeypatch.setattr(sync_service, "fetch_mangadex_detail", _fake_fetcher(calls))

    summary = await sync_service.run_sync(
        mode="scheduled",
        dry_run=True,
        include_anilist=False,
        include_mangadex=True,
        generate_embeddings=False,
    )

    after = await _mangadex_used()
    assert summary["status"] in {"success", "partial"}, summary["errors"]
    assert len(calls) == 2
    assert after == before, "a dry run must never consume provider budget"
    assert summary["request_usage"]["mangadex"]["used"] == before
