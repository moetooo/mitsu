"""Discovery-queue enrichment.

Two invariants this module keeps:

1. The MangaDex daily budget is spent through ``core.budget.consume`` for every
   request, so enrichment cannot outspend the sync job. (The quota lives in
   ``app.core`` because both this module and ``app.sync`` spend from it.)
2. No row lock is held across a network call. Rows are claimed in a short
   transaction (bumping ``enrich_attempts``), fetched with no locks held, then
   written back in a second short transaction. A crashed worker therefore
   cannot leave ``FOR UPDATE`` locks open, and a poison row stops after
   ``MAX_ENRICH_ATTEMPTS`` instead of retrying forever.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from ..config import settings
from ..core.budget import BudgetExceeded, consume
from ..db import AsyncSessionLocal
from ..db_models import DiscoveryQueue
from ..services.embedding import generate_embedding
from .mangadex_client import fetch_detail as fetch_mangadex_detail
from .normalize import mangadex_to_record
from .upsert import smart_upsert_manga

logger = logging.getLogger("mitsu.ingestion.enrich")

MAX_ENRICH_ATTEMPTS = 5


async def _claim_batch(batch_size: int) -> list[tuple[int, str, str]]:
    """Reserve pending rows without holding the lock past this transaction."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    select(DiscoveryQueue)
                    .where(
                        DiscoveryQueue.enriched == False,  # noqa: E712 - SQLAlchemy comparison
                        DiscoveryQueue.enrich_attempts < MAX_ENRICH_ATTEMPTS,
                    )
                    .order_by(DiscoveryQueue.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            claimed = [(row.id, row.source, row.external_id) for row in rows]
            if claimed:
                await session.execute(
                    update(DiscoveryQueue)
                    .where(DiscoveryQueue.id.in_([row_id for row_id, _, _ in claimed]))
                    .values(enrich_attempts=DiscoveryQueue.enrich_attempts + 1)
                )
        return claimed


async def _build_record(external_id: str) -> dict:
    raw = await fetch_mangadex_detail(external_id)
    if not raw:
        raise RuntimeError("Empty response from MangaDex")
    record = mangadex_to_record(raw)
    tags = [t["name"] for t in record.get("tags", []) if isinstance(t, dict)]
    text_to_embed = f"{record.get('synopsis', '')} Tags: {', '.join(tags)}"
    record["embedding"] = await generate_embedding(text_to_embed)
    return record


async def enrich_batch(batch_size: int = 50) -> int:
    claimed = await _claim_batch(batch_size)
    if not claimed:
        logger.info("[Enrich] No pending items in queue.")
        return 0

    logger.info("[Enrich] Processing batch of %d items...", len(claimed))

    records: dict[int, dict] = {}
    errors: dict[int, str] = {}
    unmatched: set[int] = set()
    budget_error: str | None = None

    for row_id, source, external_id in claimed:
        if source != "mangadex":
            errors[row_id] = f"Unsupported enrichment source: {source}"
            continue
        if budget_error:
            # The row was never actually attempted, so give the attempt back.
            unmatched.add(row_id)
            continue
        try:
            await consume("mangadex", settings.MANGADEX_DAILY_REQUEST_BUDGET)
        except BudgetExceeded as exc:
            budget_error = str(exc)
            logger.warning("[Enrich] Stopping batch: %s", exc)
            unmatched.add(row_id)
            continue

        try:
            records[row_id] = await _build_record(external_id)
        except Exception as exc:  # network, normalization or embedding
            errors[row_id] = str(exc)
            logger.warning(
                "[Enrich] %s/%s failed: %s", source, external_id, exc, exc_info=True
            )

    # Short write transaction: only database work happens under these locks.
    enriched = 0
    async with AsyncSessionLocal() as session:
        async with session.begin():
            pending = {
                row.id: row
                for row in (
                    await session.execute(
                        select(DiscoveryQueue)
                        .where(DiscoveryQueue.id.in_(list(records) + list(errors) + list(unmatched)))
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            }

            for row_id in unmatched:
                row = pending.get(row_id)
                if row is not None and not row.enriched:
                    row.enrich_attempts = max(0, (row.enrich_attempts or 0) - 1)

            for row_id, message in errors.items():
                row = pending.get(row_id)
                if row is not None and not row.enriched:
                    row.last_error = message[:500]

            for row_id, record in records.items():
                row = pending.get(row_id)
                if row is None or row.enriched:
                    continue
                try:
                    await smart_upsert_manga(session, record)
                    row.enriched = True
                    row.enriched_at = datetime.now(timezone.utc)
                    row.last_error = None
                    enriched += 1
                except Exception as exc:
                    row.last_error = f"DB Upsert error: {exc}"[:500]
                    logger.warning(
                        "[Enrich] Upsert failed for %s/%s: %s",
                        row.source,
                        row.external_id,
                        exc,
                        exc_info=True,
                    )

    logger.info("[Enrich] Batch complete. Enriched %d/%d items.", enriched, len(claimed))
    return enriched


async def run_enrichment(batch_size: int = 50, max_iterations: int = 0):
    """Run enrichment loop. max_iterations=0 means until the queue is empty."""
    import asyncio

    iteration = 0
    while max_iterations == 0 or iteration < max_iterations:
        count = await enrich_batch(batch_size=batch_size)
        if count == 0:
            break
        iteration += 1
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_enrichment(batch_size=50))
