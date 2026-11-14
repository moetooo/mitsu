from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text as sa_text
from sqlalchemy.orm import defer
from typing import List, Optional, Any, Dict
import random
import logging
from datetime import datetime, timezone

from ..db import get_db
from ..db_models import Manga
from ..models import MangaDetail, RecommendationResult, RecommendFilters
from ..services import trending
from ..services.retrieval import retrieve_similar_manga, similar_edges_are_fresh
from ..services.cache import get_cached, set_cached
from ..services.safety import row_is_nsfw, safety_filter

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
        .where(Manga.cover_image_url.isnot(None), sa_text(safety_filter()))
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
            (Manga.popularity < 500) | (Manga.popularity.is_(None)),
            sa_text(safety_filter()),
        )
        .order_by(Manga.average_score.desc().nullslast())
        .limit(25)
    )
    res_underrated = list((await db.execute(stmt_underrated)).scalars().all())

    # Pool 3: Critically Acclaimed / High Score (average_score >= 84)
    stmt_acclaimed = (
        select(Manga)
        .options(defer(Manga.embedding))
        .where(
            Manga.cover_image_url.isnot(None),
            Manga.average_score >= 84,
            sa_text(safety_filter()),
        )
        .order_by(Manga.average_score.desc().nullslast())
        .limit(25)
    )
    res_acclaimed = list((await db.execute(stmt_acclaimed)).scalars().all())

    # Fallback pool if DB is small
    stmt_all = (
        select(Manga)
        .options(defer(Manga.embedding))
        .where(Manga.cover_image_url.isnot(None), sa_text(safety_filter()))
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
            # A curated "featured" row has no query and therefore no similarity.
            # This was a hardcoded 0.95, shown as a "95% match".
            similarity_score=None,
            llm_reasoning=None,
            is_nsfw=m.is_nsfw,
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
    """Trending, ranked over the catalogue itself (ARCH-08).

    This used to call AniList live on the request path with no provider budget.
    That is gone rather than budgeted: a provider row has no local primary key,
    so it has to be dropped, which made any provider "top-up" unable to add a
    row the catalogue did not already hold. See `services/trending.py`.
    """
    response.headers["Cache-Control"] = "public, max-age=900, stale-while-revalidate=120"
    rows = await trending.get_trending(
        db,
        page=page,
        limit=limit,
        fmt=format_type,
        genre=genre,
        top10_only=top10_only,
    )
    return [RecommendationResult(**row) for row in rows]


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
    
    if not manga:
        raise HTTPException(status_code=404, detail="Manga not found")

    # Precomputed neighbours are only *preferred* while they are fresh. Before
    # this check the column was write-once: a re-embedded row kept the neighbours
    # computed from its old vector, and the endpoint preferred that stale answer
    # over a live ANN query forever.
    #
    # Stale edges are still *served* when there is no vector to recompute from --
    # an old answer beats a 404 -- but the fresh case wins whenever both exist.
    has_edges = bool(getattr(manga, "similar_mangas", None))
    edges_fresh = similar_edges_are_fresh(manga)
    if manga.embedding is None and not has_edges:
        # Either signal is enough: the precomputed `similar_mangas` edges are a
        # stored answer that does not need the vector. Requiring an embedding
        # turned a usable row into a 404.
        raise HTTPException(status_code=404, detail="No similarity data for this manga")

    use_precomputed_edges = edges_fresh or manga.embedding is None
    candidates = []

    if use_precomputed_edges:
        # Resolve the whole edge list. Pre-slicing it to limit + 10 decided before
        # the NSFW filter how many candidates could be considered, so a later
        # clean title could never fill the page.
        similar_ids = [item["id"] for item in manga.similar_mangas]
        stmt_sim = select(Manga).options(defer(Manga.embedding)).where(Manga.id.in_(similar_ids))
        res_sim = await db.execute(stmt_sim)
        sim_mangas_map: Dict[Any, Any] = {m.id: m for m in res_sim.scalars().all()}
        
        for item in manga.similar_mangas:
            sm_id = item["id"]
            sm = sim_mangas_map.get(sm_id)
            if sm and sm.id != manga_id:
                if not allow_nsfw and row_is_nsfw(sm):
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
            is_nsfw=m.is_nsfw,
            llm_reasoning=None  # No LLM for this fast endpoint
        ))
        
        if len(results) >= limit:
            break
            
    await set_cached(cache_key, [r.model_dump() for r in results], ttl=3600)
    return results
