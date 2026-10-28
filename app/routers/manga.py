from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text as sa_text
from sqlalchemy.orm import defer
from typing import List, Optional, Any, Dict
import httpx
import re
import random
import logging
from datetime import datetime, timezone

from ..db import get_db
from ..db_models import Manga
from ..models import MangaDetail, RecommendationResult, RecommendFilters
from ..services.retrieval import retrieve_similar_manga
from ..services.cache import get_cached, set_cached

logger = logging.getLogger("mitsu.manga")

router = APIRouter()

@router.get("/manga/featured", response_model=List[RecommendationResult])
async def get_featured_manga(response: Response, limit: int = 6, db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=900, stale-while-revalidate=60"
    now = datetime.now(timezone.utc)
    slot_minute = (now.minute // 15) * 15
    time_slot_str = f"{now.strftime('%Y-%m-%d-%H')}-{slot_minute:02d}"
    cache_key = f"manga:featured_mix:{time_slot_str}:{limit}"
    
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    # Pool 1: Top Popular Hits
    stmt_pop = (
        select(Manga)
        .options(defer(Manga.embedding))
        .where(Manga.cover_image_url.isnot(None))
        .order_by(Manga.popularity.desc().nullslast())
        .limit(25)
    )
    res_pop = list((await db.execute(stmt_pop)).scalars().all())

    # Pool 2: Underrated / Hidden Gems (High average_score >= 78, but lower popularity)
    stmt_underrated = (
        select(Manga)
        .options(defer(Manga.embedding))
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
        .options(defer(Manga.embedding))
        .where(Manga.cover_image_url.isnot(None), Manga.average_score >= 84)
        .order_by(Manga.average_score.desc().nullslast())
        .limit(25)
    )
    res_acclaimed = list((await db.execute(stmt_acclaimed)).scalars().all())

    # Fallback pool if DB is small
    stmt_all = (
        select(Manga)
        .options(defer(Manga.embedding))
        .where(Manga.cover_image_url.isnot(None))
        .limit(50)
    )
    res_all = list((await db.execute(stmt_all)).scalars().all())

    rng = random.Random(time_slot_str)
    
    selected_items: List[tuple[Any, str]] = []
    seen_ids = set()

    def pick_from_pool(pool: List[Any], badge_label: str, count: int = 2):
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

    results = [
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
    
    await set_cached(cache_key, [r.model_dump() for r in results], ttl=900)
    return results

@router.get("/manga/trending", response_model=List[RecommendationResult])
async def get_trending_manga(
    response: Response,
    limit: int = 12,
    page: int = 1,
    format_type: Optional[str] = None,
    genre: Optional[str] = None,
    top10_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    response.headers["Cache-Control"] = "public, max-age=1800, stale-while-revalidate=120"
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

    # Check if AniList circuit breaker is currently open (cooldown active from recent failure)
    anilist_circuit_open_raw = await get_cached("manga:anilist_circuit_open")
    anilist_circuit_open = False
    if anilist_circuit_open_raw is True or anilist_circuit_open_raw == "1" or anilist_circuit_open_raw == 1:
        anilist_circuit_open = True
    from_db_fallback = False

    if not anilist_circuit_open:
        # Attempt to fetch live trending from AniList GraphQL API with snappy 2.5s timeout
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
            variables: Dict[str, Any] = {"page": page, "perPage": limit}
            if country_code:
                variables["countryOfOrigin"] = country_code
            if genre_clean:
                low_g = genre_clean.lower()
                if low_g in ['yaoi', 'bl', "boys' love"]:
                    variables["genre"] = "Boys' Love"
                elif low_g in ['yuri', 'gl', "girls' love"]:
                    variables["genre"] = "Girls' Love"
                else:
                    variables["genre"] = genre_clean

            timeout = httpx.Timeout(2.5, connect=1.5, read=2.0, write=1.0, pool=1.0)
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "mitsu/1.0",
            }
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                resp = await client.post("https://graphql.anilist.co", json={"query": query, "variables": variables})
                if resp.status_code == 200:
                    data = resp.json()
                    media_list = data.get("data", {}).get("Page", {}).get("media", []) or []
                    if not media_list:
                        logger.debug("AniList trending returned empty media list for filters (page=%s, limit=%s, country=%s, genre=%s)", page, limit, country_code, genre_clean)
                    else:
                        for item in media_list:
                            t = item.get("title", {})
                            title_str = t.get("english") or t.get("romaji") or t.get("native") or "Unknown Title"
                            cover = item.get("coverImage", {})
                            cover_url = cover.get("extraLarge") or cover.get("large")
                            synopsis_clean = item.get("description")
                            if synopsis_clean:
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
                        logger.info("AniList trending fetched %d results (live)", len(trending_results))
                elif resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    ttl = 60
                    if retry_after:
                        try:
                            parsed = int(retry_after.strip())
                            if parsed > 0:
                                ttl = max(60, parsed)
                        except Exception:
                            pass
                    logger.warning("AniList API returned 429 (rate limited). Tripping circuit breaker for %ss.", ttl)
                    await set_cached("manga:anilist_circuit_open", True, ttl=ttl)
                elif resp.status_code in (500, 502, 503, 504):
                    logger.warning("AniList API returned %d. Tripping circuit breaker for 60s.", resp.status_code)
                    await set_cached("manga:anilist_circuit_open", True, ttl=60)
                elif resp.status_code in (400, 401, 403, 404):
                    logger.debug("AniList API returned %d (client error). Falling back to DB without tripping circuit breaker.", resp.status_code)
                else:
                    logger.debug("AniList API returned unexpected status %d. Falling back to DB.", resp.status_code)
        except Exception as e:
            logger.warning("AniList trending fetch failed (%s). Tripping circuit breaker for 60s and using fast DB fallback.", e, exc_info=True)
            await set_cached("manga:anilist_circuit_open", True, ttl=60)

    # If AniList request failed or returned empty results, query local database
    if not trending_results:
        from_db_fallback = True
        where_clauses: List[Any] = [
            Manga.cover_image_url.isnot(None),
            (Manga.start_year >= 2020) | (Manga.status == "RELEASING")
        ]

        if fmt and fmt != "all":
            from ..services.retrieval import build_format_sql_condition
            fmt_cond = build_format_sql_condition([fmt])
            if fmt_cond:
                where_clauses.append(sa_text(fmt_cond))

        if genre_clean:
            low = genre_clean.lower()
            if low in ['yaoi', 'bl', "boys' love"]:
                where_clauses.append(sa_text("(genres @> ARRAY['Boys'' Love'] OR tags::text ILIKE '%Boys'' Love%' OR tags::text ILIKE '%Yaoi%')"))
            elif low in ['yuri', 'gl', "girls' love"]:
                where_clauses.append(sa_text("(genres @> ARRAY['Girls'' Love'] OR tags::text ILIKE '%Girls'' Love%' OR tags::text ILIKE '%Yuri%')"))
            elif low in ['shoujo ai']:
                where_clauses.append(sa_text("(tags::text ILIKE '%Shoujo Ai%' OR tags::text ILIKE '%Girls'' Love%' OR tags::text ILIKE '%Yuri%')"))
            elif low in ['shounen ai']:
                where_clauses.append(sa_text("(tags::text ILIKE '%Shounen Ai%' OR tags::text ILIKE '%Boys'' Love%' OR tags::text ILIKE '%Yaoi%')"))
            else:
                safe_genre = genre_clean.replace("'", "''")
                where_clauses.append(sa_text(f"(genres @> ARRAY['{safe_genre}'] OR tags::text ILIKE '%{safe_genre}%')"))

        offset = (page - 1) * limit
        stmt = (
            select(Manga)
            .options(defer(Manga.embedding))
            .where(*where_clauses)
            .order_by(
                (func.coalesce(Manga.popularity, 0) * func.coalesce(Manga.average_score, 0)).desc(),
                Manga.average_score.desc().nullslast()
            )
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        mangas: List[Any] = list(result.scalars().all())

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
        if trending_results:
            logger.info("AniList trending using DB fallback (%d results)", len(trending_results))
        else:
            logger.debug("AniList trending DB fallback returned empty results")

    # Live AniList cached for 4 hours; fast DB fallback cached for 15 mins to retry AniList soon
    cache_ttl = 900 if from_db_fallback else 14400
    await set_cached(cache_key, [r.model_dump() for r in trending_results], ttl=cache_ttl)
    return trending_results

@router.get("/manga/{manga_id}", response_model=MangaDetail)
async def get_manga(manga_id: int, response: Response, db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=300"
    cache_key = f"manga:detail:{manga_id}"
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    stmt = select(Manga).options(defer(Manga.embedding)).where(Manga.id == manga_id)
    result = await db.execute(stmt)
    manga = result.scalar_one_or_none()
    
    if not manga:
        raise HTTPException(status_code=404, detail="Manga not found")
        
    detail = MangaDetail.model_validate(manga)
    await set_cached(cache_key, detail.model_dump(), ttl=3600)
    return detail

@router.get("/manga/{manga_id}/similar", response_model=List[RecommendationResult])
async def get_similar_manga(manga_id: int, response: Response, limit: int = 6, allow_nsfw: bool = False, db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=300"
    cache_key = f"manga:similar:{manga_id}:{limit}:{allow_nsfw}"
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    stmt = select(Manga).where(Manga.id == manga_id)
    result = await db.execute(stmt)
    manga = result.scalar_one_or_none()
    
    if not manga or manga.embedding is None:
        raise HTTPException(status_code=404, detail="Manga or embedding not found")
        
    candidates = []
    
    if getattr(manga, 'similar_mangas', None):
        similar_ids = [item["id"] for item in manga.similar_mangas][:limit + 10]
        stmt_sim = select(Manga).options(defer(Manga.embedding)).where(Manga.id.in_(similar_ids))
        res_sim = await db.execute(stmt_sim)
        sim_mangas_map: Dict[Any, Any] = {m.id: m for m in res_sim.scalars().all()}
        
        for item in manga.similar_mangas:
            sm_id = item["id"]
            sm = sim_mangas_map.get(sm_id)
            if sm and sm.id != manga_id:
                if not allow_nsfw and sm.genres and any(g in ['Hentai', 'Erotica'] for g in sm.genres):
                    continue
                candidates.append({
                    "manga": sm,
                    "similarity_score": item.get("score", 0.0)
                })
                if len(candidates) >= limit:
                    break

    if not candidates and manga.embedding is not None:
        candidates = await retrieve_similar_manga(
            session=db,
            query_embedding=manga.embedding,
            filters=RecommendFilters(nsfw=allow_nsfw),
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
