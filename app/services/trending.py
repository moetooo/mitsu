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

The genre and format predicates come from `query_filters.build_genre_sql_condition`
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
from .query_filters import build_genre_sql_condition
from .safety import safety_filter
from .covers import public_cover

logger = logging.getLogger("mitsu.services.trending")

#: Trending moves on the order of days, not minutes, and the query is cheap.
CACHE_TTL_SECONDS = 900

#: The page is 12 cards, and 48 is the largest slice this endpoint will build and
#: cache. Unbounded, `?limit=5000` built a 5000-row page and stored it in Redis
#: under its own key (the cache key includes the limit), and `?page=99999` paid
#: for a deep OFFSET. The bound is enforced by the handler (`Query(ge=, le=)`), so
#: an out-of-range request is a 422 instead of work.
MAX_PAGE_LIMIT = 48


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


def build_query(fmt: Optional[str], genre: Optional[str]) -> tuple[Any, Dict[str, Any]]:
    """The catalogue ranking, as a statement plus its bind parameters.

    Returns ``(stmt, params)``. A format this catalogue cannot express simply
    contributes no predicate (see `format.build_format_sql_condition`). The
    `used_filters` flag that reported that case used to be the third return
    value here; no caller read it, so it is gone rather than kept.
    """
    clean_fmt, clean_genre = _normalise(fmt, genre)

    where_clauses: List[Any] = [
        Manga.cover_image_url.isnot(None),
        sa_text(safety_filter()),
        # No recency **filter** (API-19). This used to require `start_year >= 2020`
        # (or RELEASING), which is a ranking intent expressed as a WHERE clause,
        # and it does not do that job: it hides 7 of the all-time top 10 by
        # popularity x score -- Chainsaw Man, Solo Leveling, Jujutsu Kaisen,
        # Attack on Titan, Tokyo Ghoul, Demon Slayer, Oyasumi Punpun -- and keeps
        # only 36.6% of the catalogue (34,977 rows), so a filtered query can also
        # answer "nothing" for a genre that simply has no recent hits. If freshness
        # should matter to the ranking, it belongs in the ORDER BY as a weight,
        # where it can reorder rows instead of deleting them.
    ]
    params: Dict[str, Any] = {}

    if clean_fmt != "all":
        fmt_cond = build_format_sql_condition([clean_fmt])
        if fmt_cond:
            where_clauses.append(sa_text(fmt_cond))

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
    return stmt, params


async def trending_page(
    session: AsyncSession,
    *,
    page: int = 1,
    limit: int = 12,
    fmt: Optional[str] = None,
    genre: Optional[str] = None,
) -> List[Manga]:
    """One page of the catalogue ranking. No cache, no network."""
    stmt, params = build_query(fmt, genre)
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
) -> List[Dict[str, Any]]:
    """Cached trending page, as plain dicts ready for `RecommendationResult`."""
    key = cache_key(fmt, genre, page, limit)
    cached = await get_cached(key)
    if cached is not None:
        return cached

    rows = await trending_page(session, page=page, limit=limit, fmt=fmt, genre=genre)
    payload = [_row_payload(row) for row in rows]
    await set_cached(key, payload, ttl=CACHE_TTL_SECONDS)
    logger.info("Trending served from the catalogue (%d rows, fmt=%s, genre=%s)", len(payload), fmt, genre)
    return payload


def _tag_names(tags: Any) -> List[str]:
    """Tag *names* only.

    The stored tag objects are `{"name": ..., "rank": ...}`; `rank` is read by
    no surface (the card's safety scan and the modal's chip list both read
    `name`). Measured on the twelve top rows: the objects cost 16.5 KB of a
    30.7 KB page, the names alone 6.3 KB.
    """
    names: List[str] = []
    for tag in tags or []:
        name = tag.get("name") if isinstance(tag, dict) else tag
        if name:
            names.append(name)
    return names


def _row_payload(m: Manga) -> Dict[str, Any]:
    """The subset of a row the endpoint returns, resolved to its local PK.

    `mal_id`, `volumes`, `similarity_score` and `llm_reasoning` are absent on
    purpose. Nothing rendered them: the detail modal renders the trending row
    it was handed rather than refetching, and the last two were hardcoded `None`
    here because a catalogue ranking has no query vector and no LLM reasoning
    (API-12 removed the fake "95% match"). The handler serialises with
    `response_model_exclude_unset=True`, so an absent key stays absent on the
    wire instead of coming back as a null.
    """
    cover_url, cover_list = public_cover(m.cover_image_url, m.cover_candidates)
    return {
        "id": m.id,
        "anilist_id": m.anilist_id,
        "title": m.title_english or m.title_romaji or m.title_native or "Unknown Title",
        "cover_image_url": cover_url,
        "cover_candidates": cover_list,
        "banner_image": m.banner_image,
        "synopsis": m.synopsis,
        "genres": m.genres,
        "tags": _tag_names(m.tags),
        "status": m.status,
        "start_year": m.start_year,
        "chapters": m.chapters,
        "average_score": m.average_score,
        # The detail modal names the record by its format ("Manhwa Details"), so a
        # trending row that dropped this field made every manhwa open as a manga.
        "format_type": m.format_type,
        "is_nsfw": m.is_nsfw,
    }
