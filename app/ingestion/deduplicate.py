import asyncio
from sqlalchemy import select, func, or_
from ..db import AsyncSessionLocal
from ..db_models import Manga

async def run_deduplication():
    print("[Deduplication] Scanning database for duplicate entries...")
    async with AsyncSessionLocal() as session:
        # Fetch all records
        res = await session.execute(select(Manga).order_by(Manga.id))
        all_manga = res.scalars().all()

        seen_ids = set()
        to_delete = set()
        merged_count = 0

        # Map by unique external IDs first
        anilist_map = {}
        mal_map = {}
        mangadex_map = {}

        for m in all_manga:
            # Check ID collisions
            master = None
            if m.anilist_id and m.anilist_id in anilist_map:
                master = anilist_map[m.anilist_id]
            elif m.mal_id and m.mal_id in mal_map:
                master = mal_map[m.mal_id]
            elif m.mangadex_id and m.mangadex_id in mangadex_map:
                master = mangadex_map[m.mangadex_id]

            if master and master.id != m.id:
                # Merge m into master
                master.anilist_id = master.anilist_id or m.anilist_id
                master.mal_id = master.mal_id or m.mal_id
                master.mangadex_id = master.mangadex_id or m.mangadex_id
                master.synopsis = master.synopsis or m.synopsis
                master.cover_image_url = master.cover_image_url or m.cover_image_url
                
                await session.delete(m)
                merged_count += 1
            else:
                if m.anilist_id:
                    anilist_map[m.anilist_id] = m
                if m.mal_id:
                    mal_map[m.mal_id] = m
                if m.mangadex_id:
                    mangadex_map[m.mangadex_id] = m

        await session.commit()
        print(f"[Deduplication] Merged and cleaned {merged_count} duplicate records.")

if __name__ == "__main__":
    asyncio.run(run_deduplication())
