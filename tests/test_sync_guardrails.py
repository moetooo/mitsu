import uuid
from datetime import datetime

import pytest
from sqlalchemy import delete

from app.config import settings
from app.db import AsyncSessionLocal
from app.db_models import SyncApiUsage, SyncRun
from app.sync import guardrails
from app.core.budget import BudgetExceeded, consume, get_usage, usage_summary
from app.sync.service import sync_status


def test_override_cannot_exceed_hard_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "ANILIST_DAILY_REQUEST_BUDGET", 30)
    monkeypatch.setattr(settings, "SYNC_HARD_DAILY_CEILING", 60)
    monkeypatch.setattr(settings, "SYNC_BACKFILL_RESERVE", 5)

    assert guardrails.effective_daily_limit("anilist") == 30
    assert guardrails.effective_daily_limit("anilist", 9999) == 60
    assert guardrails.effective_daily_limit("anilist", 10) == 10
    assert guardrails.backfill_request_limit() == 25
    assert guardrails.backfill_request_limit(9999) == 55


def test_ceiling_never_lowers_the_daily_budget(monkeypatch):
    monkeypatch.setattr(settings, "ANILIST_DAILY_REQUEST_BUDGET", 100)
    monkeypatch.setattr(settings, "SYNC_HARD_DAILY_CEILING", 60)
    assert guardrails.effective_daily_limit("anilist", 9999) == 100


@pytest.mark.asyncio
async def test_budget_is_capped_and_summary_has_progress_fields():
    source = f"unit-{uuid.uuid4().hex[:12]}"
    try:
        assert await consume(source, 2) == 1
        assert await get_usage(source) == 1

        summary = await usage_summary(source, 2)
        assert summary["used"] == 1
        assert summary["remaining"] == 1
        assert summary["percent"] == 50.0
        assert summary["seconds_to_reset"] > 0
        assert summary["reset_at"].endswith("+00:00")
        assert summary["hard_ceiling"] >= 2

        with pytest.raises(BudgetExceeded):
            await consume(source, 1)
        assert await get_usage(source) == 1
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(SyncApiUsage).where(SyncApiUsage.source == source))
            await session.commit()


async def _insert_run(mode: str, status: str = "success") -> str:
    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        session.add(SyncRun(run_id=run_id, mode=mode, status=status, dry_run=False))
        await session.commit()
    return run_id


async def _delete_run(run_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(SyncRun).where(SyncRun.run_id == run_id))
        await session.commit()


@pytest.mark.asyncio
async def test_daily_run_limit_blocks_before_any_request(monkeypatch):
    monkeypatch.setattr(settings, "SYNC_DAILY_RUN_LIMIT", 1)
    monkeypatch.setattr(settings, "SYNC_MANUAL_COOLDOWN_SECONDS", 0)
    run_id = await _insert_run("auto")
    try:
        with pytest.raises(guardrails.GuardrailError) as exc:
            await guardrails.preflight_trigger("auto")
        assert exc.value.code == "daily_run_limit"
        assert exc.value.retry_after and exc.value.retry_after > 0
    finally:
        await _delete_run(run_id)


@pytest.mark.asyncio
async def test_manual_cooldown_blocks_manual_but_not_auto(monkeypatch):
    monkeypatch.setattr(settings, "SYNC_DAILY_RUN_LIMIT", 10_000)
    monkeypatch.setattr(settings, "SYNC_MANUAL_COOLDOWN_SECONDS", 600)
    run_id = await _insert_run("manual")
    try:
        with pytest.raises(guardrails.GuardrailError) as exc:
            await guardrails.preflight_trigger("manual")
        assert exc.value.code == "manual_cooldown"

        guard = await guardrails.preflight_trigger("auto")
        assert guard["daily_run_limit"] == 10_000
    finally:
        await _delete_run(run_id)


@pytest.mark.asyncio
async def test_status_exposes_budget_and_backfill_progress():
    status = await sync_status(limit=1)
    for key in ("budgets", "guardrails", "backfill"):
        assert key in status
    al = status["budgets"]["anilist"]
    for key in ("used", "limit", "remaining", "percent", "reset_at", "seconds_to_reset"):
        assert key in al
    assert status["guardrails"]["daily_run_limit"] >= 1
    assert "complete" in status["backfill"]
    assert "limit" in status["backfill"]


def test_dashboard_uses_prefix_safe_api_urls():
    from pathlib import Path

    # The dashboard is a Vite build; it is not committed, so skip when the
    # build has not been run (the endpoint 503s in that state anyway).
    assets = Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard" / "assets"
    bundles = sorted(assets.glob("dashboard-*.js")) if assets.is_dir() else []
    if not bundles:
        pytest.skip("dashboard build is missing; run npm run build:dashboard in frontend/")

    bundle = "\n".join(path.read_text(encoding="utf-8") for path in bundles)
    assert "fetch('/admin/" not in bundle
    assert "fetch(`/admin/" not in bundle
    # Resolved against the page URL, so a /api-style proxy prefix still works.
    assert "new URL(`./`" in bundle


@pytest.mark.asyncio
async def test_status_paginates_runs_and_reports_progress(monkeypatch):
    # The cutoff is a setting, so the test pins it instead of quoting whatever
    # value the last deployed environment happened to use (QA-14).
    monkeypatch.setattr(settings, "SYNC_BACKFILL_CUTOFF", "2026-08-06T19:43:15+00:00")

    first = await sync_status(limit=1, offset=0)
    assert len(first["runs"]) <= 1
    assert first["runs_total"] >= len(first["runs"])
    assert first["has_more"] == (0 + len(first["runs"]) < first["runs_total"])
    assert 0.0 <= first["backfill"]["percent"] <= 100.0

    cutoff = first["backfill"]["cutoff_at"]
    # Shape, not a snapshot: the payload must stay a timezone-aware timestamp.
    assert cutoff is not None and cutoff.endswith("+00:00")
    assert datetime.fromisoformat(cutoff) == datetime.fromisoformat(settings.SYNC_BACKFILL_CUTOFF)

    second = await sync_status(limit=1, offset=1)
    assert second["runs_offset"] == 1
    if first["runs"] and second["runs"]:
        assert second["runs"][0]["run_id"] != first["runs"][0]["run_id"]


@pytest.mark.asyncio
async def test_auto_switch_persists_in_database():
    from app.db_models import SyncSetting
    from app.sync.control import auto_state, get_auto_enabled, set_auto_enabled

    try:
        await set_auto_enabled(False)
        assert await get_auto_enabled() is False
        assert (await auto_state())["source"] == "database"

        await set_auto_enabled(True)
        assert await get_auto_enabled() is True
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(SyncSetting).where(SyncSetting.key == "auto_enabled")
            )
            await session.commit()


@pytest.mark.asyncio
async def test_auto_mode_is_skipped_when_switch_is_off(monkeypatch):
    from app.sync import service as sync_service

    async def fake_auto() -> bool:
        return False

    monkeypatch.setattr(sync_service, "get_auto_enabled", fake_auto)
    run_id = str(uuid.uuid4())
    summary = await sync_service.run_sync(
        mode="auto",
        run_id=run_id,
        include_anilist=False,
        include_mangadex=False,
    )
    try:
        assert summary["status"] == "skipped"
        assert "auto sync is turned off" in summary["errors"]
    finally:
        await _delete_run(run_id)


def test_trigger_limits_keep_the_daily_sync_reserve(monkeypatch):
    monkeypatch.setattr(settings, "ANILIST_DAILY_REQUEST_BUDGET", 30)
    monkeypatch.setattr(settings, "SYNC_BACKFILL_RESERVE", 5)

    healthy = guardrails.limits_from_usage({"remaining": 20, "seconds_to_reset": 90})
    assert healthy["manual_pages"] == 20
    assert healthy["backfill_pages"] == 15

    almost_spent = guardrails.limits_from_usage({"remaining": 4, "seconds_to_reset": 90})
    assert almost_spent["manual_pages"] == 4
    assert almost_spent["backfill_pages"] == 0

    exhausted = guardrails.limits_from_usage({"remaining": 0, "seconds_to_reset": 90})
    assert exhausted["manual_pages"] == 0
    assert exhausted["backfill_pages"] == 0
