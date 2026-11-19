from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from ..db import get_db
from ..models import (
    CoverReportAck,
    CoverReportRequest,
    MangaDetail,
    RecommendationResult,
    SimilarPage,
)
from ..services import catalog, cover_health, cover_reports, featured, trending
from ..services.cache import BROWSER_CACHE_SECONDS, get_cached, set_cached
from ..services.catalog import MangaNotFound, NoSimilarityData

router = APIRouter()


@router.get("/manga/featured", response_model=List[RecommendationResult])
async def get_featured_manga(response: Response, limit: int = 6, db: AsyncSession = Depends(get_db)):
    """A curated, slot-stable rail over the catalogue.

    The four pools, the safety predicate and the seeded pick live in
    `services/featured.py` (ARCH-07); this handler only handles HTTP.
    """
    response.headers["Cache-Control"] = f"public, max-age={BROWSER_CACHE_SECONDS}"
    rows = await featured.get_featured(db, limit=limit)
    return [RecommendationResult(**row) for row in rows]


@router.get(
    "/manga/trending",
    response_model=List[RecommendationResult],
    # The trending payload omits fields no surface renders (`mal_id`, `volumes`,
    # `similarity_score`, `llm_reasoning`). Without this flag the response model
    # would put every one of them back as a null, which is how they were shipped
    # before.
    response_model_exclude_unset=True,
)
async def get_trending_manga(
    response: Response,
    limit: int = Query(12, ge=1, le=trending.MAX_PAGE_LIMIT),
    page: int = Query(1, ge=1),
    format_type: Optional[str] = None,
    genre: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Trending, ranked over the catalogue itself (ARCH-08).

    This used to call AniList live on the request path with no provider budget.
    That is gone rather than budgeted: a provider row has no local primary key,
    so it has to be dropped, which made any provider "top-up" unable to add a
    row the catalogue did not already hold. See `services/trending.py`.

    `limit` and `page` are bounded here rather than in the service, so an
    out-of-range request never reaches the database or the cache.

    The shared copy of this page is the Redis entry in `services/trending.py`
    (900 s, one per filter combination). The header is only a transport hint, so
    it does not hand out a second, un-revokable fifteen-minute copy.
    """
    response.headers["Cache-Control"] = f"public, max-age={BROWSER_CACHE_SECONDS}"
    rows = await trending.get_trending(
        db,
        page=page,
        limit=limit,
        fmt=format_type,
        genre=genre,
    )
    return [RecommendationResult(**row) for row in rows]


@router.get("/manga/{manga_id}", response_model=MangaDetail)
async def get_manga(manga_id: int, response: Response, db: AsyncSession = Depends(get_db)):
    # Redis owns the shared copy (3600 s, wiped by every catalogue write); the
    # browser gets a minute, because its copy cannot be revoked.
    response.headers["Cache-Control"] = f"public, max-age={BROWSER_CACHE_SECONDS}"
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


def _similar_results(candidates):
    """The one projection shared by `/similar` and its paged twin."""
    return [
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
            cover_candidates=c["manga"].cover_candidates,
            synopsis=c["manga"].synopsis,
            genres=c["manga"].genres,
            tags=c["manga"].tags,
            inferred_tags=c["manga"].inferred_tags,
            # The rail and `/similar/{id}` render the same MangaCard as the
            # result grids, so they need the same facts. Without these the
            # identical card appeared with no year, status or rating.
            status=c["manga"].status,
            start_year=c["manga"].start_year,
            chapters=c["manga"].chapters,
            volumes=c["manga"].volumes,
            average_score=c["manga"].average_score,
            popularity=c["manga"].popularity,
            format_type=c["manga"].format_type,
            similarity_score=c["similarity_score"],
            is_nsfw=c["manga"].is_nsfw,
            llm_reasoning=None,  # No LLM for this fast endpoint
        )
        for c in candidates
    ]


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
    response.headers["Cache-Control"] = f"public, max-age={BROWSER_CACHE_SECONDS}"
    cache_key = f"manga:similar:v2:{manga_id}:{limit}:{allow_nsfw}"
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

    results = _similar_results(candidates)

    await set_cached(cache_key, [r.model_dump() for r in results], ttl=3600)
    return results


@router.get("/manga/{manga_id}/similar/pages", response_model=SimilarPage)
async def get_similar_pages(
    manga_id: int,
    response: Response,
    limit: int = Query(12, ge=1, le=50),
    page: int = Query(1, ge=1, le=20),
    allow_nsfw: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """The full "You Might Also Like" page, one grid page at a time.

    `/similar` answers the modal rail with a fixed small list and no page
    question. This endpoint asks for `limit + 1` rows so `has_more` is known
    without paying for an extra empty request, and bounds both numbers before
    anything reaches the database or the cache.
    """
    response.headers["Cache-Control"] = f"public, max-age={BROWSER_CACHE_SECONDS}"
    cache_key = f"manga:similar:v2:pages:{manga_id}:{limit}:{page}:{allow_nsfw}"
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    try:
        candidates = await catalog.similar_candidates(
            db, manga_id, limit=limit + 1, offset=(page - 1) * limit, allow_nsfw=allow_nsfw
        )
    except MangaNotFound:
        raise HTTPException(status_code=404, detail="Manga not found")
    except NoSimilarityData:
        raise HTTPException(status_code=404, detail="No similarity data for this manga")

    has_more = len(candidates) > limit
    payload = SimilarPage(results=_similar_results(candidates[:limit]), has_more=has_more)
    await set_cached(cache_key, payload.model_dump(), ttl=3600)
    return payload


@router.post(
    "/covers/{manga_id}/broken",
    response_model=CoverReportAck,
    status_code=202,
    tags=["covers"],
)
async def report_broken_cover(
    manga_id: int,
    payload: Optional[CoverReportRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """Report a cover that will not render for a reader.

    The client only says "this one is broken"; whether it *is* broken is decided by
    the verifier, twice, on separate runs. This handler therefore never touches
    `cover_status` - a report is a nudge, not a verdict. Responses are 202 even for
    a duplicate, because the caller's intent was already satisfied.
    """
    reason = (payload or CoverReportRequest()).reason
    try:
        result = await cover_reports.record_broken_report(db, manga_id, reason=reason)
    except cover_reports.CoverNotFound:
        raise HTTPException(status_code=404, detail="Manga not found")
    return CoverReportAck(manga_id=manga_id, **result)


@router.get("/health/covers", tags=["covers"])
async def get_cover_health(db: AsyncSession = Depends(get_db)):
    """Whether the catalogue's covers render, survive one provider, and are current.

    Counters only - no URLs, no titles - so this can be watched by anything that can
    read JSON. The verdict and its reasons are computed in
    `services/cover_health.assess` so the thresholds live in one testable place.
    """
    return await cover_health.cover_health(db)
