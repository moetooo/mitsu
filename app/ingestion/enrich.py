import asyncio
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from ..db import AsyncSessionLocal
from ..db_models import DiscoveryQueue, Manga
from .jikan_client import fetch_detail as fetch_jikan_detail
from .mangadex_client import fetch_detail as fetch_mangadex_detail
from .normalize import jikan_to_record, mangadex_to_record
from ..services.embedding import generate_embedding

from .upsert import smart_upsert_manga

async def upsert_manga_by_source(session, record: dict, source: str):
    await smart_upsert_manga(session, record)

async def enrich_batch(batch_size: int = 50):
    async with AsyncSessionLocal() as session:
        # Fetch pending rows
        stmt = (
            select(DiscoveryQueue)
            .where(DiscoveryQueue.enriched == False, DiscoveryQueue.enrich_attempts < 5)
            .limit(batch_size)
        )
        res = await session.execute(stmt)
        pending_rows = res.scalars().all()

        if not pending_rows:
            print("[Enrich] No pending items in queue.", flush=True)
            return 0

        print(f"[Enrich] Processing batch of {len(pending_rows)} items...", flush=True)

        async def process_queue_row(row: DiscoveryQueue):
            row.enrich_attempts += 1
            try:
                if row.source == "jikan":
                    raw = await fetch_jikan_detail(int(row.external_id))
                    if not raw:
                        row.last_error = "Empty response from Jikan"
                        return None
                    record = jikan_to_record(raw)
                elif row.source == "mangadex":
                    raw = await fetch_mangadex_detail(row.external_id)
                    if not raw:
                        row.last_error = "Empty response from MangaDex"
                        return None
                    record = mangadex_to_record(raw)
                else:
                    return None

                # Generate vector embedding
                tags = [t['name'] for t in record.get('tags', [])]
                text_to_embed = f"{record.get('synopsis', '')} Tags: {', '.join(tags)}"
                record['embedding'] = await generate_embedding(text_to_embed)
                
                return (row, record)
            except Exception as e:
                row.last_error = str(e)
                print(f"[Enrich Error] Source {row.source} ID {row.external_id}: {e}", flush=True)
                return None

        tasks = [process_queue_row(row) for row in pending_rows]
        results = await asyncio.gather(*tasks)

        enriched_count = 0
        for res_tuple in results:
            if res_tuple:
                row, record = res_tuple
                try:
                    await upsert_manga_by_source(session, record, row.source)
                    row.enriched = True
                    row.enriched_at = datetime.utcnow()
                    enriched_count += 1
                except Exception as err:
                    row.last_error = f"DB Upsert error: {err}"

        await session.commit()
        print(f"[Enrich] Batch complete. Enriched {enriched_count}/{len(pending_rows)} items.", flush=True)
        return enriched_count

async def run_enrichment(batch_size: int = 50):
    while True:
        count = await enrich_batch(batch_size=batch_size)
        if count == 0:
            break
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(run_enrichment(batch_size=50))
