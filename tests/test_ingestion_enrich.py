"""Behaviour tests for the discovery-queue enrichment worker (QA-17).

The worker's two invariants are about *failure*, which is why they had no test:

1. A poison row stops being retried after `MAX_ENRICH_ATTEMPTS` instead of
   being fetched forever.
2. A row that was never actually attempted — because the MangaDex budget ran out
   before the network call — gets its attempt back, so an exhausted budget does
   not silently consume the queue.

Network, embedding and upsert are patched; the queue rows are real (the suite
runs against its own database).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.budget import BudgetExceeded
from app.db import AsyncSessionLocal
from app.db_models import DiscoveryQueue
from app.ingestion import enrich as enrich_module


async def add_queue_rows(*rows: dict) -> list[int]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            objects = [
                DiscoveryQueue(
                    source=row.get("source", "mangadex"),
                    external_id=row["external_id"],
                    enriched=row.get("enriched", False),
                    enrich_attempts=row.get("enrich_attempts", 0),
                )
                for row in rows
            ]
            session.add_all(objects)
            await session.flush()
            return [obj.id for obj in objects]


async def load_rows(ids: list[int]) -> dict[int, DiscoveryQueue]:
    async with AsyncSessionLocal() as session:
        found = (
            await session.execute(select(DiscoveryQueue).where(DiscoveryQueue.id.in_(ids)))
        ).scalars().all()
        return {row.id: row for row in found}


@pytest.mark.asyncio
async def test_poison_row_is_not_claimed_again(monkeypatch):
    """A row at the attempt ceiling is skipped before any network call."""
    fetched: list[str] = []

    async def fake_build(external_id: str) -> dict:
        fetched.append(external_id)
        return {}

    monkeypatch.setattr(enrich_module, "_build_record", fake_build)
    ids = await add_queue_rows(
        {"external_id": "poison", "enrich_attempts": enrich_module.MAX_ENRICH_ATTEMPTS}
    )

    assert await enrich_module.enrich_batch(batch_size=10) == 0
    assert fetched == []

    row = (await load_rows(ids))[ids[0]]
    assert row.enriched is False
    assert row.enrich_attempts == enrich_module.MAX_ENRICH_ATTEMPTS


@pytest.mark.asyncio
async def test_exhausted_budget_gives_the_attempt_back(monkeypatch):
    """A budget refusal must not look like a failed enrichment attempt."""

    async def fake_consume(source: str, limit: int, *_args, **_kwargs) -> int:
        raise BudgetExceeded(source, used=limit, limit=limit)

    async def fake_build(external_id: str) -> dict:  # pragma: no cover - must not run
        raise AssertionError("the network must not be called without budget")

    monkeypatch.setattr(enrich_module, "consume", fake_consume)
    monkeypatch.setattr(enrich_module, "_build_record", fake_build)
    ids = await add_queue_rows({"external_id": "starved"})

    assert await enrich_module.enrich_batch(batch_size=10) == 0

    row = (await load_rows(ids))[ids[0]]
    assert row.enriched is False
    # Claimed (attempts 0 -> 1) and then released by the budget guard.
    assert row.enrich_attempts == 0
    assert row.last_error is None


@pytest.mark.asyncio
async def test_one_failing_row_does_not_lose_the_rest_of_the_batch(monkeypatch):
    """A fetch failure records the error and the sibling row still enriches."""
    upserted: list[str] = []

    async def fake_consume(source: str, limit: int, *_args, **_kwargs) -> int:
        return 1

    async def fake_build(external_id: str) -> dict:
        if external_id == "broken":
            raise RuntimeError("MangaDex returned 503")
        return {"title_romaji": f"Title {external_id}", "external_id": external_id}

    async def fake_upsert(session, record: dict) -> None:
        upserted.append(record["external_id"])

    monkeypatch.setattr(enrich_module, "consume", fake_consume)
    monkeypatch.setattr(enrich_module, "_build_record", fake_build)
    monkeypatch.setattr(enrich_module, "smart_upsert_manga", fake_upsert)

    ids = await add_queue_rows({"external_id": "broken"}, {"external_id": "good"})

    assert await enrich_module.enrich_batch(batch_size=10) == 1

    rows = await load_rows(ids)
    by_external_id = {row.external_id: row for row in rows.values()}
    assert upserted == ["good"]
    assert by_external_id["good"].enriched is True
    assert by_external_id["good"].last_error is None
    assert by_external_id["broken"].enriched is False
    assert "503" in by_external_id["broken"].last_error


@pytest.mark.asyncio
async def test_unsupported_source_is_recorded_without_spending_budget(monkeypatch):
    """A queue row that this worker cannot enrich says so; it is not retried as
    a network failure."""
    calls: list[tuple[str, int]] = []

    async def fake_consume(source: str, limit: int, *_args, **_kwargs) -> int:
        calls.append((source, limit))
        return 1

    monkeypatch.setattr(enrich_module, "consume", fake_consume)
    ids = await add_queue_rows({"source": "anilist", "external_id": "42"})

    assert await enrich_module.enrich_batch(batch_size=10) == 0
    assert calls == []

    row = (await load_rows(ids))[ids[0]]
    assert row.enriched is False
    assert "Unsupported enrichment source: anilist" in row.last_error