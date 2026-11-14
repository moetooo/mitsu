from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from ..db import get_db
from ..models import MangaDetail, RecommendationResult
from ..services import catalog, featured, trending
from ..services.cache import get_cached, set_cached
from ..services.catalog import MangaNotFound, NoSimilarityData

router = APIRouter()


@router.get("/manga/featured", response_model=List[RecommendationResult])
async def get_featured_manga(response: Response, limit: int = 6, db: AsyncSession = Depends(get_db)):
    """A curated, slot-stable rail over the catalogue.

    The four pools, the safety predicate and the seeded pick live in
    `services/featured.py` (ARCH-07); this handler only handles HTTP.
    """
    response.headers["Cache-Control"] = "public, max-age=900, stale-while-revalidate=60"
    rows = await featured.get_featured(db, limit=limit)
    return [RecommendationResult(**row) for row in rows]


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

    manga = await catalog.get_manga(db, manga_id)
    if manga is None:
        raise HTTPException(status_code=404, detail="Manga not found")

    detail = MangaDetail.model_validate(manga)
    await set_cached(cache_key, detail.model_dump(), ttl=3600)
    return detail


@router.get("/manga/{manga_id}/similar", response_model=List[RecommendationResult])
async def get_similar_manga(
    manga_id: int,
    response: Response,
    limit: int = 6,
    allow_nsfw: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Neighbours of one title, from stored edges or a live ANN query.

    Which source wins, and why, lives in `catalog.similar_candidates`: the
    stored `similar_mangas` edges are preferred while fresh (or when there is no
    vector to recompute from), and the live query covers the rest.
    """
    response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=300"
    cache_key = f"manga:similar:{manga_id}:{limit}:{allow_nsfw}"
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    try:
        candidates = await catalog.similar_candidates(
            db, manga_id, limit=limit, allow_nsfw=allow_nsfw
        )
    except MangaNotFound:
        raise HTTPException(status_code=404, detail="Manga not found")
    except NoSimilarityData:
        raise HTTPException(status_code=404, detail="No similarity data for this manga")

    results = [
        RecommendationResult(
            id=c["manga"].id,
            anilist_id=c["manga"].anilist_id,
            title=(
                c["manga"].title_english
                or c["manga"].title_romaji
                or c["manga"].title_native
                or "Unknown"
            ),
            cover_image_url=c["manga"].cover_image_url,
            synopsis=c["manga"].synopsis,
            genres=c["manga"].genres,
            similarity_score=c["similarity_score"],
            is_nsfw=c["manga"].is_nsfw,
            llm_reasoning=None,  # No LLM for this fast endpoint
        )
        for c in candidates
    ]

    await set_cached(cache_key, [r.model_dump() for r in results], ttl=3600)
    return results
