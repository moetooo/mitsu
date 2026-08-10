import asyncio
# pyrefly: ignore [missing-import]
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from .anilist_client import fetch_page
from .normalize import anilist_to_record
from ..db import AsyncSessionLocal, engine, Base
from ..db_models import Manga
from ..services.embedding import generate_embedding

async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.execute(text("ALTER TABLE manga ADD COLUMN IF NOT EXISTS mal_id INTEGER UNIQUE;"))
        await conn.execute(text("ALTER TABLE manga ADD COLUMN IF NOT EXISTS mangadex_id VARCHAR UNIQUE;"))
        await conn.execute(text("ALTER TABLE manga ALTER COLUMN anilist_id DROP NOT NULL;"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_manga_embedding ON manga USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);")
        )

from .upsert import smart_upsert_manga

async def upsert_manga(session, record: dict):
    await smart_upsert_manga(session, record)

from sqlalchemy import select
from datetime import datetime

async def get_existing_anilist_ids(session) -> set:
    result = await session.execute(select(Manga.anilist_id).where(Manga.anilist_id.isnot(None)))
    return set(result.scalars().all())

async def run_ingestion(start_year: int = 2000, end_year: int = datetime.now().year):
    await init_db()
    
    async with AsyncSessionLocal() as session:
        existing_ids = await get_existing_anilist_ids(session)
        print(f"Database currently contains {len(existing_ids)} AniList manga.", flush=True)

        for year in range(start_year, end_year + 1):
            print(f"\n==================== Ingesting Year {year} ====================", flush=True)
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
                    print(f"Error fetching year {year} page {page}: {e}. Moving to next year.", flush=True)
                    break
                
                items = data.get("media", [])
                if not items:
                    break

                async def process_raw(raw):
                    anilist_id = raw.get("id")
                    if not anilist_id or anilist_id in existing_ids:
                        return None
                    
                    try:
                        record = anilist_to_record(raw)
                        tags = [t['name'] for t in record.get('tags', [])]
                        text_to_embed = f"{record.get('synopsis', '')} Tags: {', '.join(tags)}"
                        record['embedding'] = await generate_embedding(text_to_embed)
                        return record
                    except Exception as err:
                        print(f"  [Warning] Error embedding manga ID {anilist_id}: {err}", flush=True)
                        return None

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
                            print(f"  [Warning] Error DB upsert for manga ID {record.get('anilist_id')}: {err}", flush=True)

                await session.commit()
                print(f"[{year}] Page {page}: Ingested {new_count} new entries (Total in DB: {len(existing_ids)})", flush=True)

                if not data.get("pageInfo", {}).get("hasNextPage"):
                    break

                page += 1
                await asyncio.sleep(1.5)

if __name__ == "__main__":
    asyncio.run(run_ingestion(2000, datetime.now().year))
