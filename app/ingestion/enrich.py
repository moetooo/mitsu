import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from ..db import AsyncSessionLocal
from ..db_models import DiscoveryQueue, Manga
from .mangadex_client import fetch_detail as fetch_mangadex_detail
from .normalize import mangadex_to_record
from ..services.embedding import generate_embedding

from .upsert import smart_upsert_manga

logger = logging.getLogger("mitsu.ingestion.enrich")


async def upsert_manga_by_source(session, record: dict, source: str):
    await smart_upsert_manga(session, record)


async def enrich_batch(batch_size: int = 50) -> int:
    async with AsyncSessionLocal() as session:
        # Fetch pending rows with row-level lock to avoid concurrent processing
        stmt = (
            select(DiscoveryQueue)
            .where(DiscoveryQueue.enriched == False, DiscoveryQueue.enrich_attempts < 5)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        res = await session.execute(stmt)
        pending_rows = res.scalars().all()

        if not pending_rows:
            logger.info("[Enrich] No pending items in queue.")
            return 0

        logger.info("[Enrich] Processing batch of %d items...", len(pending_rows))

        async def process_queue_row(row: DiscoveryQueue):
            try:
                if row.source == "mangadex":
                    raw = await fetch_mangadex_detail(row.external_id)
                    if not raw:
                        row.last_error = "Empty response from MangaDex"
                        return None
                    record = mangadex_to_record(raw)
                else:
                    return None

                # Generate vector embedding (per-item try to isolate failures)
                try:
                    tags = [t['name'] for t in record.get('tags', [])]
                    text_to_embed = f"{record.get('synopsis', '')} Tags: {', '.join(tags)}"
                    record['embedding'] = await generate_embedding(text_to_embed)
                except Exception as e:
                    logger.warning("[Enrich] Embedding failed for %s/%s: %s", row.source, row.external_id, e)
                    row.last_error = f"Embedding error: {e}"
                    return None

                return (row, record)
            except Exception as e:
                row.last_error = str(e)
                logger.warning("[Enrich Error] Source %s ID %s: %s", row.source, row.external_id, e, exc_info=True)
                return None

        tasks = [process_queue_row(row) for row in pending_rows]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched_count = 0
        for res_tuple in results:
            if isinstance(res_tuple, Exception):
                logger.error("[Enrich] Task raised exception: %s", res_tuple, exc_info=True)
                continue
            if res_tuple:
                row, record = res_tuple
                try:
                    await upsert_manga_by_source(session, record, row.source)
                    row.enriched = True
                    row.enriched_at = datetime.now(timezone.utc)
                    enriched_count += 1
                except Exception as err:
                    row.last_error = f"DB Upsert error: {err}"
                    row.enrich_attempts += 1
                    logger.warning("[Enrich] Upsert failed for %s/%s: %s", row.source, row.external_id, err, exc_info=True)

        await session.commit()
        logger.info("[Enrich] Batch complete. Enriched %d/%d items.", enriched_count, len(pending_rows))
        return enriched_count


async def run_enrichment(batch_size: int = 50, max_iterations: int = 0):
    """Run enrichment loop. max_iterations=0 means infinite."""
    iteration = 0
    while max_iterations == 0 or iteration < max_iterations:
        count = await enrich_batch(batch_size=batch_size)
        if count == 0:
            break
        iteration += 1
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(run_enrichment(batch_size=50))
