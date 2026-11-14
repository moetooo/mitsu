from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, text
from sqlalchemy.orm import defer
from typing import List
from ..db import get_db
from ..db_models import Manga
from ..models import MangaDetail

from ..utils.sanitizer import sanitize_search_query
from ..services.search_autocorrect import autocorrect_query
from ..services.cache import get_cached, set_cached
from ..services.safety import safety_filter

router = APIRouter()


def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters so a query of `%` is not a wildcard."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/search", response_model=List[MangaDetail])
async def search_manga(q: str, response: Response, db: AsyncSession = Depends(get_db)):
    clean_q = sanitize_search_query(q)
    if not clean_q:
        return []

    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=60"

    # 1. Check Redis cache first to bypass DB and autocorrect for frequent/keystroke queries
    cache_key = f"search:{clean_q}"
    cached_data = await get_cached(cache_key)
    if cached_data is not None:
        return cached_data

    # 2. Autocorrect query if needed
    autocorrected_q = await autocorrect_query(clean_q, db)
    if autocorrected_q != clean_q:
        auto_cache_key = f"search:{autocorrected_q}"
        cached_auto = await get_cached(auto_cache_key)
        if cached_auto is not None:
            await set_cached(cache_key, cached_auto, ttl=300)
            return cached_auto
        search_target = autocorrected_q
    else:
        search_target = clean_q
        
    search_term = f"%{_escape_like(search_target)}%"
    stmt = (
        select(Manga)
        .options(defer(Manga.embedding))
        .where(
            or_(
                Manga.title_english.ilike(search_term, escape="\\"),
                Manga.title_romaji.ilike(search_term, escape="\\"),
                Manga.title_native.ilike(search_term, escape="\\"),
                func.array_to_string(Manga.alternative_titles, ' ').ilike(search_term, escape="\\"),
            ),
            # /search is a public endpoint, so it uses the shared safety
            # predicate instead of trusting each caller to pass nsfw=False.
            text(safety_filter()),
        )
        .order_by(Manga.popularity.desc().nullslast())
        .limit(10)
    )
    
    result = await db.execute(stmt)
    mangas = result.scalars().all()
    response_data = [MangaDetail.model_validate(m).model_dump() for m in mangas]

    # Cache response for 5 minutes (300 seconds)
    await set_cached(cache_key, response_data, ttl=300)
    if autocorrected_q != clean_q:
        await set_cached(f"search:{autocorrected_q}", response_data, ttl=300)

    return response_data

