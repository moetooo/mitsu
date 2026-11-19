import json
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


def test_page_depth_cap_is_recognised():
    import httpx

    request = httpx.Request("POST", "https://graphql.anilist.co")
    capped = httpx.HTTPStatusError(
        "Client error '400 Bad Request'",
        request=request,
        response=httpx.Response(
            400,
            request=request,
            json={"errors": [{"message": "Page depth exceeds maximum allowed for API requests (5000 entries)"}]},
        ),
    )
    assert sync_service._is_page_depth_cap(capped)

    server_error = httpx.HTTPStatusError(
        "Server error '500'",
        request=request,
        response=httpx.Response(500, request=request),
    )
    assert not sync_service._is_page_depth_cap(server_error)
    assert not sync_service._is_page_depth_cap(RuntimeError("network down"))


def _anilist_summary() -> dict:
    return {
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


def _fake_media(anilist_id: int, updated_epoch: int) -> dict:
    return {
        "id": anilist_id,
        "idMal": None,
        "updatedAt": updated_epoch,
        "title": {"romaji": "Backlog Test", "english": "Backlog Test", "native": None},
        "description": "backlog",
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
    }


@pytest.mark.asyncio
async def test_run_anilist_counts_every_request_attempt(monkeypatch):
    """The run must report its own requests, not just the day snapshot."""
    attempts = {"n": 0}

    async def fake_fetch(page, per_page, **kwargs):
        before = kwargs.get("before_request")
        # Two hook calls on one page mimic a retried request.
        for _ in range(2):
            if before is not None:
                await before()
                attempts["n"] += 1
        return {
            "pageInfo": {"hasNextPage": False},
            "media": [_fake_media(9_999_9820, int(datetime(2100, 1, 1, tzinfo=timezone.utc).timestamp()))],
        }

    async def fake_consume(source, limit, **kwargs):
        return 1

    async def fake_get_state(source):
        return None

    async def fake_save_state(source, **fields):
        return None

    async def fake_apply(records, summary, **kwargs):
        summary["rows_inserted"] += len(records)

    monkeypatch.setattr(sync_service, "fetch_updated_page", fake_fetch)
    monkeypatch.setattr(sync_service, "consume", fake_consume)
    monkeypatch.setattr(sync_service, "_get_state", fake_get_state)
    monkeypatch.setattr(sync_service, "_save_state", fake_save_state)
    monkeypatch.setattr(sync_service, "_apply_anilist_page", fake_apply)

    summary = _anilist_summary()
    await sync_service._run_anilist(
        summary,
        max_pages=3,
        since=None,
        dry_run=True,
        generate_embeddings=False,
    )

    assert attempts["n"] == 2
    assert summary["details"]["anilist"]["requests_attempted"] == 2
    # A dry run must still report attempts even though it spends no budget.
    assert summary["pages_fetched"] == 1


@pytest.mark.asyncio
async def test_run_anilist_reports_backlog_when_max_pages_stops_early(monkeypatch):
    async def fake_fetch(page, per_page, **kwargs):
        return {
            "pageInfo": {"hasNextPage": True},
            "media": [_fake_media(9_999_9802, int(datetime(2100, 1, 1, tzinfo=timezone.utc).timestamp()))],
        }

    async def fake_consume(source, limit, day=None):
        return 1

    monkeypatch.setattr(sync_service, "fetch_updated_page", fake_fetch)
    monkeypatch.setattr(sync_service, "consume", fake_consume)

    summary = _anilist_summary()
    await sync_service._run_anilist(
        summary,
        max_pages=1,
        since=datetime(2000, 1, 1, tzinfo=timezone.utc),
        dry_run=True,
        generate_embeddings=False,
    )

    anilist = summary["details"]["anilist"]
    assert anilist["reached_watermark"] is False
    assert anilist["backlog_remaining"] is True
    assert anilist["pages_fetched"] == 1


@pytest.mark.asyncio
async def test_run_anilist_reports_caught_up_at_the_end_of_the_feed(monkeypatch):
    async def fake_fetch(page, per_page, **kwargs):
        return {
            "pageInfo": {"hasNextPage": False},
            "media": [_fake_media(9_999_9803, int(datetime(2100, 1, 1, tzinfo=timezone.utc).timestamp()))],
        }

    async def fake_consume(source, limit, day=None):
        return 1

    monkeypatch.setattr(sync_service, "fetch_updated_page", fake_fetch)
    monkeypatch.setattr(sync_service, "consume", fake_consume)

    summary = _anilist_summary()
    await sync_service._run_anilist(
        summary,
        max_pages=3,
        since=datetime(2000, 1, 1, tzinfo=timezone.utc),
        dry_run=True,
        generate_embeddings=False,
    )

    anilist = summary["details"]["anilist"]
    assert anilist["reached_watermark"] is True
    assert anilist["backlog_remaining"] is False


@pytest.mark.asyncio
async def test_completed_walk_advances_the_watermark(monkeypatch):
    """Crossing the old floor is what lets the floor move forward."""
    floor = datetime(2026, 11, 15, tzinfo=timezone.utc)
    newest = int(datetime(2026, 11, 16, 10, tzinfo=timezone.utc).timestamp())
    crossing = int(datetime(2026, 11, 14, tzinfo=timezone.utc).timestamp())

    async def fake_fetch(page, per_page, **kwargs):
        if page == 1:
            return {"pageInfo": {"hasNextPage": True}, "media": [_fake_media(9_999_9810, newest)]}
        return {"pageInfo": {"hasNextPage": True}, "media": [_fake_media(9_999_9811, crossing)]}

    async def fake_get_state(source):
        return None

    async def fake_consume(source, limit, **kwargs):
        return 1

    async def fake_apply(records, summary, **kwargs):
        summary["rows_inserted"] += len(records)

    saved: dict = {}

    async def fake_save_state(source, **fields):
        saved.update(fields)

    monkeypatch.setattr(sync_service, "fetch_updated_page", fake_fetch)
    monkeypatch.setattr(sync_service, "_get_state", fake_get_state)
    monkeypatch.setattr(sync_service, "_save_state", fake_save_state)
    monkeypatch.setattr(sync_service, "_apply_anilist_page", fake_apply)
    monkeypatch.setattr(sync_service, "consume", fake_consume)

    summary = _anilist_summary()
    await sync_service._run_anilist(
        summary,
        max_pages=5,
        since=floor,
        dry_run=False,
        generate_embeddings=False,
    )

    anilist = summary["details"]["anilist"]
    assert anilist["reached_watermark"] is True
    assert anilist["backlog_remaining"] is False
    assert saved["checkpoint_at"] == datetime(2026, 11, 16, 10, tzinfo=timezone.utc)
    assert saved["checkpoint_value"] == str(newest)


@pytest.mark.asyncio
async def test_partial_walk_never_moves_the_watermark(monkeypatch):
    """A short run must not mark the unread tail as done."""
    floor = datetime(2026, 11, 15, tzinfo=timezone.utc)
    newer = int(datetime(2026, 11, 16, 10, tzinfo=timezone.utc).timestamp())

    async def fake_fetch(page, per_page, **kwargs):
        return {"pageInfo": {"hasNextPage": True}, "media": [_fake_media(9_999_9820 + page, newer)]}

    async def fake_get_state(source):
        return None

    async def fake_consume(source, limit, **kwargs):
        return 1

    async def fake_apply(records, summary, **kwargs):
        summary["rows_inserted"] += len(records)

    saved: list[dict] = []

    async def fake_save_state(source, **fields):
        saved.append(fields)

    monkeypatch.setattr(sync_service, "fetch_updated_page", fake_fetch)
    monkeypatch.setattr(sync_service, "_get_state", fake_get_state)
    monkeypatch.setattr(sync_service, "_save_state", fake_save_state)
    monkeypatch.setattr(sync_service, "_apply_anilist_page", fake_apply)
    monkeypatch.setattr(sync_service, "consume", fake_consume)

    summary = _anilist_summary()
    await sync_service._run_anilist(
        summary,
        max_pages=2,
        since=floor,
        dry_run=False,
        generate_embeddings=False,
    )

    anilist = summary["details"]["anilist"]
    assert anilist["reached_watermark"] is False
    assert anilist["backlog_remaining"] is True
    assert anilist["watermark"] == floor.isoformat()
    assert not any("checkpoint_at" in fields for fields in saved)

def test_progress_file_writes_snapshot(tmp_path, monkeypatch):
    target = tmp_path / "progress.json"
    monkeypatch.setenv("MITSU_SYNC_PROGRESS_FILE", str(target))
    summary = {
        "run_id": "run-1",
        "mode": "auto",
        "dry_run": False,
        "status": "running",
        "pages_fetched": 2,
        "rows_seen": 100,
        "rows_inserted": 3,
        "rows_updated": 4,
        "rows_unchanged": 93,
        "rows_embedded": 0,
        "errors": [],
    }

    sync_service._write_progress(summary, "anilist", page=2, pages_target=10)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["phase"] == "anilist"
    assert payload["page"] == 2
    assert payload["pages_target"] == 10
    assert payload["rows_seen"] == 100
    assert not (tmp_path / "progress.json.tmp").exists()

    # Without the env var it is a no-op: the CLI must never depend on it.
    monkeypatch.delenv("MITSU_SYNC_PROGRESS_FILE")
    sync_service._write_progress(summary, "done")
    assert json.loads(target.read_text(encoding="utf-8"))["phase"] == "anilist"
