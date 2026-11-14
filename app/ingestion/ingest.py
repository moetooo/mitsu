import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .anilist_client import fetch_page
from .normalize import anilist_to_record
from .upsert import smart_upsert_manga
from ..core.schema import verify_schema
from ..db import AsyncSessionLocal
from ..db_models import Manga
from ..services.embedding import generate_embedding

logger = logging.getLogger("mitsu.ingestion.ingest")

# A single year never legitimately needs more pages than this; the loop used to
# be unbounded, so a provider that kept answering with a stale `hasNextPage`
# could hammer the API (and the budget) forever.
MAX_PAGES_PER_YEAR = 200

async def upsert_manga(session, record: dict):
    await smart_upsert_manga(session, record)


async def get_existing_anilist_ids(session) -> set:
    result = await session.execute(select(Manga.anilist_id).where(Manga.anilist_id.isnot(None)))
    return set(result.scalars().all())


def _tag_names(record: dict) -> list[str]:
    """Tag names, tolerating the shapes AniList media objects arrive in.

    A single malformed tag used to raise through `t['name']` and take the whole
    record down with it.
    """
    names: list[str] = []
    for tag in record.get("tags") or []:
        if isinstance(tag, dict):
            name = tag.get("name")
        else:
            name = tag
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


async def run_ingestion(
    start_year: int = 2000,
    end_year: int | None = None,
    max_pages_per_year: int = MAX_PAGES_PER_YEAR,
):
    # Schema changes are Alembic's job (ARCH-03/PIPE-10). This used to build the
    # HNSW and trigram indexes and rewrite columns on every ingestion run.
    await verify_schema()
    end_year = datetime.now().year if end_year is None else end_year

    # Nothing is dropped silently any more: every record that cannot be
    # normalised, embedded or upserted lands in one of these counters and is
    # reported at the end of the run.
    skipped = {"invalid": 0, "already_present": 0, "embed_failed": 0, "upsert_failed": 0}

    async with AsyncSessionLocal() as session:
        existing_ids = await get_existing_anilist_ids(session)
        logger.info("Database currently contains %d AniList manga.", len(existing_ids))

        for year in range(start_year, end_year + 1):
            logger.info("==================== Ingesting Year %d ====================", year)
            # Filter specifically for startDate in `year`
            start_date_greater = (year - 1) * 10000 + 1231  # e.g. 19991231 for 2000
            start_date_lesser = (year + 1) * 10000 + 101    # e.g. 20010101 for 2000
            
            page = 1
            per_page = 50
            
            while page <= max_pages_per_year:
                try:
                    data = await fetch_page(
                        page=page, 
                        per_page=per_page, 
                        start_date_greater=start_date_greater, 
                        start_date_lesser=start_date_lesser
                    )
                except Exception as e:
                    logger.error("Error fetching year %d page %d: %s. Moving to next year.", year, page, e, exc_info=True)
                    break
                
                items = data.get("media", [])
                if not items:
                    break

                async def process_raw(raw):
                    anilist_id = raw.get("id") if isinstance(raw, dict) else None
                    if not anilist_id:
                        skipped["invalid"] += 1
                        return None
                    if anilist_id in existing_ids:
                        skipped["already_present"] += 1
                        return None

                    try:
                        record = anilist_to_record(raw)
                    except Exception as err:
                        skipped["invalid"] += 1
                        logger.warning("  [Warning] Cannot normalise manga ID %s: %s", anilist_id, err, exc_info=True)
                        return None

                    tags = _tag_names(record)
                    text_to_embed = f"{record.get('synopsis', '')} Tags: {', '.join(tags)}"
                    try:
                        record['embedding'] = await generate_embedding(text_to_embed)
                    except Exception as err:
                        # Keep the row. A record without an embedding is still
                        # useful and the sync run embeds rows whose vector is
                        # missing; dropping it here lost the whole title.
                        skipped["embed_failed"] += 1
                        logger.warning("  [Warning] Error embedding manga ID %s (keeping row without a vector): %s", anilist_id, err, exc_info=True)
                    return record

                tasks = [process_raw(raw) for raw in items]
                processed_records = await asyncio.gather(*tasks)
                
                new_count = 0
                for record in processed_records:
                    if record:
                        try:
                            await upsert_manga(session, record)
                            existing_ids.add(record['anilist_id'])
                            new_count += 1
                        except Exception as err:
                            skipped["upsert_failed"] += 1
                            logger.warning("  [Warning] Error DB upsert for manga ID %s: %s", record.get('anilist_id'), err, exc_info=True)

                await session.commit()
                logger.info("[%d] Page %d: Ingested %d new entries (Total in DB: %d)", year, page, new_count, len(existing_ids))

                if not data.get("pageInfo", {}).get("hasNextPage"):
                    break

                page += 1
                await asyncio.sleep(1.5)

        logger.info(
            "Ingestion finished. Skipped: %d already present, %d invalid, "
            "%d without an embedding, %d failed to upsert.",
            skipped["already_present"],
            skipped["invalid"],
            skipped["embed_failed"],
            skipped["upsert_failed"],
        )
        return skipped

if __name__ == "__main__":
    asyncio.run(run_ingestion(2000, datetime.now().year))
