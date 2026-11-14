from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from ..db import get_db
from ..models import MangaDetail
from ..services import catalog
from ..utils.sanitizer import sanitize_search_query
from ..services.search_autocorrect import autocorrect_query
from ..services.cache import get_cached, set_cached

router = APIRouter()


@router.get("/search", response_model=List[MangaDetail])
async def search_manga(q: str, response: Response, db: AsyncSession = Depends(get_db)):
    """Title jump box.

    The statement, the LIKE escaping and the safety predicate live in
    `catalog.search_titles` (ARCH-07). Stage 7 owns this endpoint's ranking and
    pagination; this handler keeps the cache and the autocorrect hop.
    """
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

    mangas = await catalog.search_titles(db, search_target)
    response_data = [MangaDetail.model_validate(manga).model_dump() for manga in mangas]

    # Cache response for 5 minutes (300 seconds), under the query as typed and
    # under the corrected form, so both keystroke orders hit.
    await set_cached(cache_key, response_data, ttl=300)
    if autocorrected_q != clean_q:
        await set_cached(f"search:{autocorrected_q}", response_data, ttl=300)

    return response_data
