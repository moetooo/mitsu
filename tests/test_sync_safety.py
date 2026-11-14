import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select, text

from app.db import AsyncSessionLocal, engine
from app.db_models import Manga, SyncApiUsage, SyncRun
from app.sync import service as sync_service
from app.core.budget import BudgetExceeded, consume, utc_day


@pytest.mark.asyncio
async def test_budget_is_hard_capped():
    source = f"unit-{uuid.uuid4().hex[:12]}"
    day = utc_day()
    async with AsyncSessionLocal() as session:
        await session.execute(delete(SyncApiUsage).where(SyncApiUsage.source == source))
        await session.commit()

    try:
        assert await consume(source, 1) == 1
        with pytest.raises(BudgetExceeded):
            await consume(source, 1)
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(SyncApiUsage).where(SyncApiUsage.source == source))
            await session.commit()


@pytest.mark.asyncio
async def test_second_run_is_skipped_while_lock_is_held():
    run_id = str(uuid.uuid4())
    async with engine.connect() as lock_conn:
        acquired = await lock_conn.scalar(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": sync_service.settings.SYNC_LOCK_KEY},
        )
        assert acquired
        try:
            summary = await sync_service.run_sync(
                mode="manual",
                run_id=run_id,
                include_anilist=False,
                include_mangadex=False,
            )
        finally:
            await lock_conn.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": sync_service.settings.SYNC_LOCK_KEY},
            )

    try:
        assert summary["status"] == "skipped"
        assert any("already running" in error for error in summary["errors"])
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(SyncRun).where(SyncRun.run_id == run_id))
            await session.commit()


@pytest.mark.asyncio
async def test_dry_run_fetches_but_rolls_back(monkeypatch):
    test_anilist_id = 9_999_9801
    now_epoch = int(datetime(2100, 1, 1, tzinfo=timezone.utc).timestamp())

    async def fake_fetch(page, per_page, **kwargs):
        return {
            "pageInfo": {"hasNextPage": False},
            "media": [{
                "id": test_anilist_id,
                "idMal": None,
                "updatedAt": now_epoch,
                "title": {"romaji": "Sync Dry Run Test", "english": "Sync Dry Run Test", "native": None},
                "description": "dry run",
                "genres": ["Action"],
                "tags": [{"name": "Test", "rank": 10}],
                "status": "FINISHED",
                "startDate": {"year": 2095},
                "chapters": 1,
                "volumes": 1,
                "averageScore": 50,
                "popularity": 1,
                "synonyms": [],
                "coverImage": {"large": None},
                "bannerImage": None,
                "siteUrl": None,
            }],
        }

    async def fake_consume(source, limit, day=None):
        return 1

    monkeypatch.setattr(sync_service, "fetch_updated_page", fake_fetch)
    monkeypatch.setattr(sync_service, "consume", fake_consume)

    summary = {
        "pages_fetched": 0,
        "rows_seen": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_unchanged": 0,
        "rows_embedded": 0,
        "rows_conflicted": 0,
        "details": {},
        "errors": [],
    }
    await sync_service._run_anilist(
        summary,
        max_pages=1,
        since=None,
        dry_run=True,
        generate_embeddings=False,
    )

    async with AsyncSessionLocal() as session:
        count = await session.scalar(
            select(func.count()).select_from(Manga).where(Manga.anilist_id == test_anilist_id)
        )
        assert count == 0
        await session.execute(delete(Manga).where(Manga.anilist_id == test_anilist_id))
        await session.commit()

    assert summary["rows_inserted"] == 1
    assert summary["errors"] == []
