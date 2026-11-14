import asyncio
import logging
# pyrefly: ignore [missing-import]
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from .anilist_client import fetch_page
from .normalize import anilist_to_record
from ..db import AsyncSessionLocal, engine, Base
from ..db_models import Manga
from ..services.embedding import generate_embedding

logger = logging.getLogger("mitsu.ingestion.ingest")

async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        await conn.execute(text("ALTER TABLE manga ADD COLUMN IF NOT EXISTS mal_id INTEGER UNIQUE;"))
        await conn.execute(text("ALTER TABLE manga ADD COLUMN IF NOT EXISTS mangadex_id VARCHAR UNIQUE;"))
        await conn.execute(text("ALTER TABLE manga ALTER COLUMN anilist_id DROP NOT NULL;"))
        await conn.run_sync(Base.metadata.create_all)
        # Drop legacy IVFFlat index if present
        await conn.execute(text("DROP INDEX IF EXISTS idx_manga_embedding;"))
        # HNSW index on vector embeddings for sub-5ms cosine similarity
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_manga_embedding_hnsw ON manga USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);")
        )
        # GIN Trigram indexes on titles for sub-millisecond similarity and ILIKE search
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_manga_title_english_trgm ON manga USING gin (title_english gin_trgm_ops);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_manga_title_romaji_trgm ON manga USING gin (title_romaji gin_trgm_ops);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_manga_title_native_trgm ON manga USING gin (title_native gin_trgm_ops);"))


from .upsert import smart_upsert_manga

async def upsert_manga(session, record: dict):
    await smart_upsert_manga(session, record)

from sqlalchemy import select
from datetime import datetime

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


async def run_ingestion(start_year: int = 2000, end_year: int = datetime.now().year):
    await init_db()

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
            
            while True:
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
