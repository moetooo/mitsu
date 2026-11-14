from fastapi import APIRouter, Depends, Query, Response
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
async def search_manga(
    q: str,
    response: Response,
    limit: int = Query(catalog.SEARCH_RESULT_LIMIT, ge=1, le=catalog.SEARCH_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Title jump box.

    The statement, the LIKE escaping and the safety predicate live in
    `catalog.search_titles` (ARCH-07, API-08). This handler owns the cache key and
    the spelling fallback: **search first, correct only when nothing matched**
    (SVC-05), so a query that works is answered exactly as typed.
    """
    clean_q = sanitize_search_query(q)
    if not clean_q:
        return []

    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=60"

    # The page is part of the identity of the answer: without it, page 2 would be
    # served page 1's rows from the cache.
    cache_key = f"search:{clean_q}:{limit}:{offset}"
    # 1. Check Redis cache first to bypass DB and autocorrect for frequent/keystroke queries
    cached_data = await get_cached(cache_key)
    if cached_data is not None:
        return cached_data

    corrected_q = clean_q
    mangas = await catalog.search_titles(db, clean_q, limit=limit, offset=offset)

    # Autocorrect is a **fallback**, not a preamble (SVC-05). A query that finds
    # something is answered exactly as typed: the old order rewrote valid words
    # (a character name, a romaji term) before the search ever ran, so the user
    # silently searched for something they did not type.
    if not mangas:
        candidate = await autocorrect_query(clean_q, db)
        if candidate != clean_q:
            retried = await catalog.search_titles(db, candidate, limit=limit, offset=offset)
            if retried:
                mangas = retried
                corrected_q = candidate

    response_data = [MangaDetail.model_validate(manga).model_dump() for manga in mangas]

    # Cache response for 5 minutes (300 seconds), under the query as typed and
    # under the corrected form, so both keystroke orders hit.
    await set_cached(cache_key, response_data, ttl=300)
    if corrected_q != clean_q:
        await set_cached(f"search:{corrected_q}:{limit}:{offset}", response_data, ttl=300)

    return response_data
