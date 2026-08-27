from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
import httpx
from ..db import get_db
from ..db_models import Manga
from ..models import MangaDetail, RecommendationResult
from ..services.retrieval import retrieve_similar_manga
from ..services.cache import get_cached, set_cached

import random
from datetime import datetime

router = APIRouter()

@router.get("/manga/featured", response_model=List[RecommendationResult])
async def get_featured_manga(limit: int = 6, db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()
    slot_minute = (now.minute // 15) * 15
    time_slot_str = f"{now.strftime('%Y-%m-%d-%H')}-{slot_minute:02d}"
    cache_key = f"manga:featured_mix:{time_slot_str}:{limit}"
    
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    # Pool 1: Top Popular Hits
    stmt_pop = select(Manga).where(Manga.cover_image_url.isnot(None)).order_by(Manga.popularity.desc().nullslast()).limit(25)
    res_pop = list((await db.execute(stmt_pop)).scalars().all())

    # Pool 2: Underrated / Hidden Gems (High average_score >= 78, but lower popularity)
    stmt_underrated = (
        select(Manga)
        .where(
            Manga.cover_image_url.isnot(None),
            Manga.average_score >= 78,
            (Manga.popularity < 500) | (Manga.popularity.is_(None))
        )
        .order_by(Manga.average_score.desc().nullslast())
        .limit(25)
    )
    res_underrated = list((await db.execute(stmt_underrated)).scalars().all())

    # Pool 3: Critically Acclaimed / High Score (average_score >= 84)
    stmt_acclaimed = (
        select(Manga)
        .where(Manga.cover_image_url.isnot(None), Manga.average_score >= 84)
        .order_by(Manga.average_score.desc().nullslast())
        .limit(25)
    )
    res_acclaimed = list((await db.execute(stmt_acclaimed)).scalars().all())

    # Fallback pool if DB is small
    stmt_all = select(Manga).where(Manga.cover_image_url.isnot(None)).limit(50)
    res_all = list((await db.execute(stmt_all)).scalars().all())

    rng = random.Random(time_slot_str)
    
    selected_items = []
    seen_ids = set()

    def pick_from_pool(pool, badge_label, count=2):
        picked = 0
        pool_shuffled = pool.copy()
        rng.shuffle(pool_shuffled)
        for m in pool_shuffled:
            if m.id not in seen_ids:
                seen_ids.add(m.id)
                selected_items.append((m, badge_label))
                picked += 1
                if picked >= count:
                    break

    # Pick 2 from Popular, 2 from Underrated Gems, 2 from Critically Acclaimed
    pick_from_pool(res_pop, "Popular Pick", 2)
    pick_from_pool(res_underrated, "Hidden Gem", 2)
    pick_from_pool(res_acclaimed, "Critically Acclaimed", 2)

    # Fill remaining up to limit if pools had overlaps
    if len(selected_items) < limit:
        rng.shuffle(res_all)
        for m in res_all:
            if m.id not in seen_ids:
                seen_ids.add(m.id)
                selected_items.append((m, "Featured Title"))
                if len(selected_items) >= limit:
                    break

    rng.shuffle(selected_items)

    response = [
        RecommendationResult(
            id=m.id,
            anilist_id=m.anilist_id,
            mal_id=m.mal_id,
            title=m.title_english or m.title_romaji or m.title_native or "Unknown",
            cover_image_url=m.cover_image_url,
            banner_image=m.banner_image,
            synopsis=m.synopsis,
            genres=m.genres,
            tags=m.tags,
            status=m.status,
            start_year=m.start_year,
            chapters=m.chapters,
            volumes=m.volumes,
            average_score=m.average_score,
            similarity_score=0.95,
            llm_reasoning=None,
            category_badge=badge
        ) for m, badge in selected_items
    ]
    
    await set_cached(cache_key, [r.model_dump() for r in response], ttl=900)
    return response

@router.get("/manga/trending", response_model=List[RecommendationResult])
async def get_trending_manga(
    limit: int = 12,
    page: int = 1,
    format_type: Optional[str] = None,
    genre: Optional[str] = None,
    top10_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    fmt = (format_type or "all").lower()
    genre_clean = genre.strip() if genre and genre.strip() and genre.strip().lower() != "all" else None
    
    if top10_only:
        limit = 10
        page = 1

    cache_key = f"manga:trending:{fmt}:{genre_clean or 'all'}:{page}:{limit}"
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    # Map format_type to AniList countryOfOrigin code
    country_map = {
        "manga": "JP",
        "manhwa": "KR",
        "manhua": "CN"
    }
    country_code = country_map.get(fmt)

    trending_results: List[RecommendationResult] = []

    # Attempt to fetch live trending from AniList GraphQL API
    try:
        query = """
        query ($page: Int, $perPage: Int, $countryOfOrigin: String, $genre: String) {
          Page(page: $page, perPage: $perPage) {
            media(type: MANGA, sort: TRENDING_DESC, countryOfOrigin: $countryOfOrigin, genre: $genre) {
              id
              idMal
              title { romaji english native }
              description(asHtml: false)
              genres
              tags { name rank }
              status
              startDate { year }
              chapters
              volumes
              averageScore
              popularity
              coverImage { extraLarge large }
              bannerImage
              siteUrl
            }
          }
        }
        """
        variables = {"page": page, "perPage": limit}
        if country_code:
            variables["countryOfOrigin"] = country_code
        if genre_clean:
            variables["genre"] = genre_clean

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post("https://graphql.anilist.co", json={"query": query, "variables": variables})
            if resp.status_code == 200:
                data = resp.json()
                media_list = data.get("data", {}).get("Page", {}).get("media", [])
                
                for item in media_list:
                    t = item.get("title", {})
                    title_str = t.get("english") or t.get("romaji") or t.get("native") or "Unknown Title"
                    cover = item.get("coverImage", {})
                    cover_url = cover.get("extraLarge") or cover.get("large")
                    synopsis_clean = item.get("description")
                    if synopsis_clean:
                        import re
                        synopsis_clean = re.sub(r'<[^>]+>', '', synopsis_clean)

                    trending_results.append(RecommendationResult(
                        id=item.get("id"),
                        anilist_id=item.get("id"),
                        mal_id=item.get("idMal"),
                        title=title_str,
                        cover_image_url=cover_url,
                        banner_image=item.get("bannerImage"),
                        synopsis=synopsis_clean,
                        genres=item.get("genres") or [],
                        tags=item.get("tags") or [],
                        status=item.get("status"),
                        start_year=item.get("startDate", {}).get("year") if item.get("startDate") else None,
                        chapters=item.get("chapters"),
                        volumes=item.get("volumes"),
                        average_score=item.get("averageScore"),
                        similarity_score=None,
                        llm_reasoning=None
                    ))
    except Exception as e:
        # Fallback to DB if network / AniList API is unreachable
        pass

    # If AniList request failed or returned empty results, query local database
    if not trending_results:
        from sqlalchemy import text as sa_text
        where_clauses = [
            Manga.cover_image_url.isnot(None),
            (Manga.start_year >= 2020) | (Manga.status == "RELEASING")
        ]

        if fmt == "manhwa":
            where_clauses.append(sa_text("(tags::text ILIKE '%Long Strip%' OR tags::text ILIKE '%Manhwa%' OR tags::text ILIKE '%Korean%' OR genres @> ARRAY['Manhwa'] OR site_url ILIKE '%manhwa%')"))
        elif fmt == "manhua":
            where_clauses.append(sa_text("(tags::text ILIKE '%Manhua%' OR tags::text ILIKE '%Chinese%' OR tags::text ILIKE '%Ancient China%' OR genres @> ARRAY['Manhua'] OR site_url ILIKE '%manhua%')"))
        elif fmt == "manga":
            where_clauses.append(sa_text("NOT (tags::text ILIKE '%Long Strip%' OR tags::text ILIKE '%Manhwa%' OR tags::text ILIKE '%Manhua%' OR tags::text ILIKE '%Chinese%' OR site_url ILIKE '%manhwa%' OR site_url ILIKE '%manhua%')"))

        if genre_clean:
            where_clauses.append(sa_text(f"genres @> ARRAY['{genre_clean}']"))

        offset = (page - 1) * limit
        stmt = (
            select(Manga)
            .where(*where_clauses)
            .order_by((Manga.popularity * Manga.average_score).desc().nullslast())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        mangas = result.scalars().all()

        trending_results = [
            RecommendationResult(
                id=m.id,
                anilist_id=m.anilist_id,
                mal_id=m.mal_id,
                title=m.title_english or m.title_romaji or m.title_native or "Unknown Title",
                cover_image_url=m.cover_image_url,
                banner_image=m.banner_image,
                synopsis=m.synopsis,
                genres=m.genres,
                tags=m.tags,
                status=m.status,
                start_year=m.start_year,
                chapters=m.chapters,
                volumes=m.volumes,
                average_score=m.average_score,
                similarity_score=None,
                llm_reasoning=None
            ) for m in mangas
        ]

    await set_cached(cache_key, [r.model_dump() for r in trending_results], ttl=14400)
    return trending_results

@router.get("/manga/{manga_id}", response_model=MangaDetail)
async def get_manga(manga_id: int, db: AsyncSession = Depends(get_db)):
    cache_key = f"manga:detail:{manga_id}"
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    stmt = select(Manga).where(Manga.id == manga_id)
    result = await db.execute(stmt)
    manga = result.scalar_one_or_none()
    
    if not manga:
        raise HTTPException(status_code=404, detail="Manga not found")
        
    detail = MangaDetail.model_validate(manga)
    await set_cached(cache_key, detail.model_dump(), ttl=3600)
    return detail

@router.get("/manga/{manga_id}/similar", response_model=List[RecommendationResult])
async def get_similar_manga(manga_id: int, limit: int = 6, allow_nsfw: bool = False, db: AsyncSession = Depends(get_db)):
    cache_key = f"manga:similar:{manga_id}:{limit}:{allow_nsfw}"
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    stmt = select(Manga).where(Manga.id == manga_id)
    result = await db.execute(stmt)
    manga = result.scalar_one_or_none()
    
    if not manga or manga.embedding is None:
        raise HTTPException(status_code=404, detail="Manga or embedding not found")
        
    candidates = await retrieve_similar_manga(
        session=db,
        query_embedding=manga.embedding,
        filters={"nsfw": allow_nsfw},
        limit=limit + 1
    )
    
    # Filter out the source manga itself and format as RecommendationResult
    results = []
    for c in candidates:
        m = c["manga"]
        if m.id == manga_id:
            continue
            
        results.append(RecommendationResult(
            id=m.id,
            anilist_id=m.anilist_id,
            title=m.title_english or m.title_romaji or m.title_native or "Unknown",
            cover_image_url=m.cover_image_url,
            synopsis=m.synopsis,
            genres=m.genres,
            similarity_score=c["similarity_score"],
            llm_reasoning=None  # No LLM for this fast endpoint
        ))
        
        if len(results) >= limit:
            break
            
    await set_cached(cache_key, [r.model_dump() for r in results], ttl=3600)
    return results
