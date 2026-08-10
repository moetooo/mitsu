import asyncio
from collections import defaultdict
from difflib import SequenceMatcher
from sqlalchemy import select, delete
from ..db import AsyncSessionLocal
from ..db_models import Manga

def similarity_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    l1, l2 = len(a), len(b)
    if abs(l1 - l2) / max(l1, l2) > 0.10:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

def clean_title(t: str) -> str:
    if not t:
        return ""
    return t.lower().strip()

async def run_merge_pass():
    print("[Merge Pass] Starting fast cross-source deduplication...", flush=True)
    async with AsyncSessionLocal() as session:
        # 1. Load lightweight tuples (excluding heavy embedding vectors)
        stmt = select(
            Manga.id,
            Manga.title_english,
            Manga.title_romaji,
            Manga.start_year,
            Manga.anilist_id,
            Manga.mal_id,
            Manga.mangadex_id
        )
        res = await session.execute(stmt)
        rows = res.all()
        print(f"[Merge Pass] Loaded {len(rows)} lightweight records.", flush=True)

        # 2. Fast mal_id matching
        mal_map = {}
        linked_mal = 0
        to_delete = set()

        for r in rows:
            m_id, t_eng, t_rom, year, anilist_id, mal_id, md_id = r
            if mal_id and anilist_id:
                mal_map[mal_id] = m_id

        for r in rows:
            m_id, t_eng, t_rom, year, anilist_id, mal_id, md_id = r
            if mal_id and not anilist_id and mal_id in mal_map:
                to_delete.add(m_id)
                linked_mal += 1

        if to_delete:
            await session.execute(delete(Manga).where(Manga.id.in_(list(to_delete))))
            await session.commit()
        print(f"[Merge Pass] Linked & merged {linked_mal} entries via mal_id matching.", flush=True)

        # 3. Reload lightweight tuples
        res = await session.execute(stmt)
        remaining = res.all()

        # 4. Fast O(1) Exact Title + Year Match
        title_year_map = {}
        exact_to_delete = set()
        exact_linked = 0

        for r in remaining:
            m_id, t_eng, t_rom, year, anilist_id, mal_id, md_id = r
            t = clean_title(t_eng or t_rom)
            if not t or not year:
                continue

            key = (t, year)
            if key in title_year_map:
                exact_to_delete.add(m_id)
                exact_linked += 1
            else:
                title_year_map[key] = m_id

        if exact_to_delete:
            await session.execute(delete(Manga).where(Manga.id.in_(list(exact_to_delete))))
            await session.commit()
        print(f"[Merge Pass] Linked & merged {exact_linked} entries via exact title+year matching.", flush=True)

        # 5. Year-bucketed Fast Fuzzy Title Matching
        res = await session.execute(stmt)
        unlinked = res.all()

        year_buckets = defaultdict(list)
        for r in unlinked:
            year = r[3]
            if year:
                year_buckets[year].append(r)

        fuzzy_to_delete = set()
        fuzzy_linked = 0
        sorted_years = sorted(year_buckets.keys())
        print(f"[Merge Pass] Running fast fuzzy comparison across {len(sorted_years)} years...", flush=True)

        for year in sorted_years:
            items = year_buckets[year]
            n = len(items)
            if n < 2:
                continue

            year_linked = 0
            for i in range(n):
                r1 = items[i]
                if not r1 or r1[0] in fuzzy_to_delete:
                    continue
                t1 = clean_title(r1[1] or r1[2])
                if not t1:
                    continue

                for j in range(i + 1, n):
                    r2 = items[j]
                    if not r2 or r2[0] in fuzzy_to_delete:
                        continue
                    t2 = clean_title(r2[1] or r2[2])
                    if not t2:
                        continue

                    if similarity_ratio(t1, t2) >= 0.90:
                        fuzzy_to_delete.add(r2[0])
                        year_linked += 1

            fuzzy_linked += year_linked
            if year_linked > 0:
                print(f"  [{year}] Found & merged {year_linked} fuzzy duplicates (Total merged so far: {fuzzy_linked})", flush=True)

        if fuzzy_to_delete:
            await session.execute(delete(Manga).where(Manga.id.in_(list(fuzzy_to_delete))))
            await session.commit()
        print(f"[Merge Pass] Done! Linked & merged {fuzzy_linked} total entries via fuzzy title matching.", flush=True)

if __name__ == "__main__":
    asyncio.run(run_merge_pass())
