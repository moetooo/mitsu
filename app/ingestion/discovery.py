import asyncio
from sqlalchemy.dialects.postgresql import insert
from ..db import AsyncSessionLocal
from ..db_models import DiscoveryQueue
from .mangadex_client import fetch_list_page as fetch_mangadex_page

from datetime import datetime
from sqlalchemy import select
from ..db_models import Manga

async def get_existing_mangadex_ids(session):
    res_md = await session.execute(select(Manga.mangadex_id).where(Manga.mangadex_id.isnot(None)))
    return set(res_md.scalars().all())

async def discover_mangadex(start_year: int = 2000, end_year: int = datetime.now().year, max_batches_per_year: int = 5):
    print(f"Starting MangaDex discovery ({start_year} - {end_year})...", flush=True)
    limit = 100
    async with AsyncSessionLocal() as session:
        existing_mangadex_ids = await get_existing_mangadex_ids(session)
        print(f"[MangaDex Discovery] Found {len(existing_mangadex_ids)} existing MangaDex IDs in database.", flush=True)

        for year in range(start_year, end_year + 1):
            print(f"[MangaDex Discovery] Processing year {year}...", flush=True)
            for i in range(max_batches_per_year):
                offset = i * limit
                try:
                    res = await fetch_mangadex_page(offset=offset, limit=limit, year=year)
                    items = res.get("data", [])
                    if not items:
                        break

                    inserted = 0
                    for item in items:
                        md_id = item.get("id")
                        if not md_id or md_id in existing_mangadex_ids:
                            continue

                        attributes = item.get("attributes", {})
                        title_dict = attributes.get("title", {})
                        title = title_dict.get("en") or next(iter(title_dict.values()), "Unknown")

                        stmt = insert(DiscoveryQueue).values(
                            source="mangadex",
                            external_id=md_id,
                            title=title,
                            start_year=year,
                            enriched=False,
                            enrich_attempts=0
                        ).on_conflict_do_nothing(constraint="uq_source_external_id")
                        
                        await session.execute(stmt)
                        inserted += 1

                    await session.commit()
                    print(f"  [{year}] Offset {offset}: Processed {len(items)} items ({inserted} new queued).", flush=True)
                    
                    total = res.get("total", 0)
                    if offset + limit >= total:
                        break
                except Exception as e:
                    print(f"  [{year}] Error at offset {offset}: {e}", flush=True)
                    break

async def run_discovery(start_year: int = 2000, end_year: int = datetime.now().year):
    await discover_mangadex(start_year=start_year, end_year=end_year)

if __name__ == "__main__":
    asyncio.run(run_discovery(2000, datetime.now().year))
