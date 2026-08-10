import asyncio
from sqlalchemy.dialects.postgresql import insert
from ..db import AsyncSessionLocal
from ..db_models import DiscoveryQueue
from .jikan_client import fetch_list_page as fetch_jikan_page
from .mangadex_client import fetch_list_page as fetch_mangadex_page

from datetime import datetime
from sqlalchemy import select
from ..db_models import Manga

async def get_existing_source_ids(session):
    res_mal = await session.execute(select(Manga.mal_id).where(Manga.mal_id.isnot(None)))
    mal_ids = set(res_mal.scalars().all())

    res_md = await session.execute(select(Manga.mangadex_id).where(Manga.mangadex_id.isnot(None)))
    mangadex_ids = set(res_md.scalars().all())

    return mal_ids, mangadex_ids

async def discover_jikan(start_year: int = 2000, end_year: int = datetime.now().year, max_pages_per_year: int = 5):
    print(f"Starting Jikan discovery ({start_year} - {end_year})...", flush=True)
    async with AsyncSessionLocal() as session:
        existing_mal_ids, _ = await get_existing_source_ids(session)
        print(f"[Jikan Discovery] Found {len(existing_mal_ids)} existing MAL IDs in database.", flush=True)

        for year in range(start_year, end_year + 1):
            print(f"[Jikan Discovery] Processing year {year}...", flush=True)
            start_date = f"{year}-01-01"
            end_date = f"{year}-12-31"

            for page in range(1, max_pages_per_year + 1):
                try:
                    res = await fetch_jikan_page(page=page, start_date=start_date, end_date=end_date)
                    items = res.get("data", [])
                    if not items:
                        break

                    inserted = 0
                    for item in items:
                        mal_id = item.get("mal_id")
                        if not mal_id or mal_id in existing_mal_ids:
                            continue

                        title = item.get("title") or item.get("title_english")

                        stmt = insert(DiscoveryQueue).values(
                            source="jikan",
                            external_id=str(mal_id),
                            title=title,
                            start_year=year,
                            enriched=False,
                            enrich_attempts=0
                        ).on_conflict_do_nothing(constraint="uq_source_external_id")
                        
                        await session.execute(stmt)
                        inserted += 1

                    await session.commit()
                    print(f"  [{year}] Page {page}: Processed {len(items)} items ({inserted} new queued).", flush=True)
                    
                    has_next = res.get("pagination", {}).get("has_next_page", False)
                    if not has_next:
                        break
                except Exception as e:
                    if "504" in str(e):
                        print(f"  [Jikan Discovery] Jikan API server error (504 Gateway Timeout: MAL backend unavailable). Skipping Jikan discovery for now.", flush=True)
                        return
                    print(f"  [{year}] Error on page {page}: {e}", flush=True)
                    break

async def discover_mangadex(start_year: int = 2000, end_year: int = datetime.now().year, max_batches_per_year: int = 5):
    print(f"Starting MangaDex discovery ({start_year} - {end_year})...", flush=True)
    limit = 100
    async with AsyncSessionLocal() as session:
        _, existing_mangadex_ids = await get_existing_source_ids(session)
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
    await discover_jikan(start_year=start_year, end_year=end_year)
    await discover_mangadex(start_year=start_year, end_year=end_year)

if __name__ == "__main__":
    asyncio.run(run_discovery(2000, datetime.now().year))
