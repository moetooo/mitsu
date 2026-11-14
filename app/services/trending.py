"""The trending page, served from the catalogue (ARCH-08).

This endpoint used to call AniList live, inside a 2.5s request timeout, with no
provider budget, and fall back to a database query only when that failed. Two
things were wrong with that, and the second one is why the live path is gone
rather than budgeted:

1. A third-party call sat on the user's request path, so a slow or rate-limited
   provider became a slow or failing page. AniList is currently degraded to 30
   requests/minute and this project's own cap is 30 requests/*day*.
2. A live row has no local primary key. `RecommendationResult.id` is optional
   precisely for that case, but a card whose id is `None` cannot be opened and
   cannot be handed to `/manga/{id}/similar`. **A provider row that cannot be
   resolved to a local `manga.id` has to be dropped**, which means any "top-up"
   from a provider can only ever contribute rows the catalogue already holds --
   a no-op that costs a network round trip and a dependency.

So trending is a ranking over `manga` and nothing else. Every row is openable by
construction, `is_nsfw` comes from `services/safety.py` like everywhere else, and
no provider's acceptable-use policy governs a page load.

There is deliberately no scheduler: the query measures **63 ms warm** against the
95,626-row catalogue, and answers are cached, so a cold cache on an unusual
filter combination costs one indexed query. A scheduled precompute would have
existed only to keep the external call off the request path.

The genre and format predicates come from `retrieval.build_genre_sql_condition`
and `format.build_format_sql_condition` rather than being re-written here. The
router used to carry its own inline `tags::text ILIKE '%Yaoi%'` variants, which
disagreed with the retrieval filter on the same request (ARCH-07).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..db_models import Manga
from .cache import get_cached, set_cached
from .format import build_format_sql_condition
from .retrieval import build_genre_sql_condition
from .safety import safety_filter

logger = logging.getLogger("mitsu.services.trending")

#: Trending moves on the order of days, not minutes, and the query is cheap.
CACHE_TTL_SECONDS = 900

#: `top10_only` is the dashboard's "top 10" widget.
TOP10_LIMIT = 10


def _normalise(fmt: Optional[str], genre: Optional[str]) -> tuple[str, Optional[str]]:
    """`all`/blank mean "no filter", and the cache key must not see the difference."""
    clean_fmt = (fmt or "all").strip().lower() or "all"
    clean_genre = genre.strip() if genre and genre.strip() else None
    if clean_genre and clean_genre.lower() == "all":
        clean_genre = None
    return clean_fmt, clean_genre


def cache_key(fmt: Optional[str], genre: Optional[str], page: int, limit: int) -> str:
    clean_fmt, clean_genre = _normalise(fmt, genre)
    return f"manga:trending:{clean_fmt}:{clean_genre or 'all'}:{page}:{limit}"


def build_query(fmt: Optional[str], genre: Optional[str]) -> tuple[Any, Dict[str, Any], bool]:
    """The catalogue ranking, as a statement plus its bind parameters.

    Returns ``(stmt, params, used_filters)``. `used_filters` is False when the
    request asked for filters this catalogue cannot express, so the caller can
    tell "nothing matches" apart from "nothing to match on".
    """
    clean_fmt, clean_genre = _normalise(fmt, genre)

    where_clauses: List[Any] = [
        Manga.cover_image_url.isnot(None),
        sa_text(safety_filter()),
        # Prefer recent and ongoing titles. The catalogue is 99.8% post-2000, so
        # this mostly guards against a stale pre-2020 classic outranking a
        # currently-publishing series on a product of popularity and score.
        (Manga.start_year >= 2020)
        | ((Manga.status == "RELEASING") & Manga.start_year.isnot(None)),
    ]
    params: Dict[str, Any] = {}
    used_filters = True

    if clean_fmt != "all":
        fmt_cond = build_format_sql_condition([clean_fmt])
        if fmt_cond:
            where_clauses.append(sa_text(fmt_cond))
        else:
            used_filters = False

    if clean_genre:
        genre_cond = build_genre_sql_condition([clean_genre], params)
        if genre_cond:
            where_clauses.append(sa_text(genre_cond))

    stmt = (
        select(Manga)
        .options(defer(Manga.embedding))
        .where(*where_clauses)
        .order_by(
            (func.coalesce(Manga.popularity, 0) * func.coalesce(Manga.average_score, 0)).desc(),
            Manga.average_score.desc().nullslast(),
            Manga.popularity.desc().nullslast(),
        )
    )
    return stmt, params, used_filters


async def trending_page(
    session: AsyncSession,
    *,
    page: int = 1,
    limit: int = 12,
    fmt: Optional[str] = None,
    genre: Optional[str] = None,
) -> List[Manga]:
    """One page of the catalogue ranking. No cache, no network."""
    stmt, params, _used = build_query(fmt, genre)
    offset = max(0, (page - 1) * limit)
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt, params) if params else await session.execute(stmt)
    return list(result.scalars().all())


async def get_trending(
    session: AsyncSession,
    *,
    page: int = 1,
    limit: int = 12,
    fmt: Optional[str] = None,
    genre: Optional[str] = None,
    top10_only: bool = False,
) -> List[Dict[str, Any]]:
    """Cached trending page, as plain dicts ready for `RecommendationResult`."""
    if top10_only:
        limit, page = TOP10_LIMIT, 1

    key = cache_key(fmt, genre, page, limit)
    cached = await get_cached(key)
    if cached is not None:
        return cached

    rows = await trending_page(session, page=page, limit=limit, fmt=fmt, genre=genre)
    payload = [_row_payload(row) for row in rows]
    await set_cached(key, payload, ttl=CACHE_TTL_SECONDS)
    logger.info("Trending served from the catalogue (%d rows, fmt=%s, genre=%s)", len(payload), fmt, genre)
    return payload


def _row_payload(m: Manga) -> Dict[str, Any]:
    """The subset of a row the endpoint returns, resolved to its local PK."""
    return {
        "id": m.id,
        "anilist_id": m.anilist_id,
        "mal_id": m.mal_id,
        "title": m.title_english or m.title_romaji or m.title_native or "Unknown Title",
        "cover_image_url": m.cover_image_url,
        "banner_image": m.banner_image,
        "synopsis": m.synopsis,
        "genres": m.genres,
        "tags": m.tags,
        "status": m.status,
        "start_year": m.start_year,
        "chapters": m.chapters,
        "volumes": m.volumes,
        "average_score": m.average_score,
        # A catalogue ranking has no query vector, so there is no similarity to
        # report. This was a hardcoded 0.95 displayed as "95% match" (API-12).
        "similarity_score": None,
        "llm_reasoning": None,
        "is_nsfw": m.is_nsfw,
    }
