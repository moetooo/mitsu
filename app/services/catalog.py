"""Catalogue reads, owned by the service layer (ARCH-07).

The routers used to build their own statements: `/manga/featured` carried four
ORM queries, `/similar` resolved its neighbour ids inline, `/search` wrote its
own `ilike`/`array_to_string`, and the dashboard wrote raw SQL against
`discovery_queue`. Two consequences, both invisible until something had to
change:

* the safety predicate was applied by hand at every site, so each new query path
  was a new chance to leak NSFW rows (which is exactly what happened, and why
  `services/safety.py` exists);
* a change to the catalogue read shape meant editing four routers, and a
  `text()`-based filter could not be reused at all.

Every read that returns catalogue rows now lives here. Services answer domain
questions; they do not know about HTTP, which is why a missing row raises
`MangaNotFound` rather than importing `HTTPException`.

Kept deliberately small: this is the *read* side of the catalogue, not a second
copy of `retrieval.py` (which owns ranking). ARCH-16's full repository layer is
a later, separate decision.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..db_models import Manga, SEARCH_BLOB
from ..models import RecommendFilters
from .retrieval import SEED_MIN_SIMILARITY, retrieve_similar_manga, similar_edges_are_fresh
from .safety import row_is_nsfw, safety_filter
from .covers import public_cover

#: `/search` is a jump-to-title box. Stage 7 added `limit`/`offset` (API-08);
#: the router bounds `limit` to `SEARCH_MAX_LIMIT` so the ceiling is one number.
SEARCH_RESULT_LIMIT = 10
SEARCH_MAX_LIMIT = 50


class MangaNotFound(LookupError):
    """No catalogue row with that id. The router maps this to 404."""


class NoSimilarityData(LookupError):
    """The row has neither an embedding nor stored neighbour edges."""


def escape_like(value: str) -> str:
    """Escape LIKE metacharacters so a query of `%` is not a wildcard."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_pattern(value: str) -> str:
    """`berserk` -> `%berserk%`, with the metacharacters escaped.

    Callers pass the *raw* term on purpose: escaping here means a new caller
    cannot forget it, the same way `key_prefix` derives itself from `exclude`.
    """
    return f"%{escape_like(value)}%"


async def get_manga(
    session: AsyncSession,
    manga_id: int,
    *,
    include_embedding: bool = False,
) -> Optional[Manga]:
    """One row by primary key, or None.

    The embedding column is deferred by default: it is a 384-float vector and
    every caller except `/similar` throws it away, so loading it inflated every
    detail response.
    """
    stmt = select(Manga).where(Manga.id == manga_id)
    if not include_embedding:
        stmt = stmt.options(defer(Manga.embedding))
    return (await session.execute(stmt)).scalar_one_or_none()


async def require_manga(
    session: AsyncSession,
    manga_id: int,
    *,
    include_embedding: bool = False,
) -> Manga:
    """Like `get_manga`, but raises `MangaNotFound` instead of returning None."""
    manga = await get_manga(session, manga_id, include_embedding=include_embedding)
    if manga is None:
        raise MangaNotFound(f"manga {manga_id} does not exist")
    return manga


async def get_mangas_by_ids(session: AsyncSession, manga_ids: Iterable[Any]) -> Dict[Any, Manga]:
    """Resolve a list of ids into `{id: row}` in one query.

    A missing id is simply absent from the map: stored neighbour edges are a
    snapshot, so a neighbour may have been deleted since the edges were written
    and that must not fail the page.
    """
    ids = [manga_id for manga_id in manga_ids if manga_id is not None]
    if not ids:
        return {}
    stmt = select(Manga).options(defer(Manga.embedding)).where(Manga.id.in_(ids))
    return {manga.id: manga for manga in (await session.execute(stmt)).scalars().all()}


async def get_title_card(session: AsyncSession, manga_id: int) -> Optional[Dict[str, Any]]:
    """The few columns a "did you mean" card needs, or None if the row is gone.

    A single-column projection instead of a full row: the suggestion is advisory
    and rendered beside the results, so it must not pay for a synopsis and a
    384-float vector.
    """
    result = await session.execute(
        select(
            Manga.id,
            Manga.title_english,
            Manga.title_romaji,
            Manga.cover_image_url,
            Manga.cover_candidates,
            Manga.format_type,
            Manga.start_year,
        ).where(Manga.id == manga_id)
    )
    row = result.first()
    if row is None:
        return None
    cover_url, cover_list = public_cover(row.cover_image_url, row.cover_candidates)
    return {
        "id": row.id,
        "title": row.title_english or row.title_romaji,
        "cover_image_url": cover_url,
        "cover_candidates": cover_list,
        "format_type": row.format_type,
        "start_year": row.start_year,
    }


def build_search_statement(
    term: str,
    *,
    limit: int = SEARCH_RESULT_LIMIT,
    offset: int = 0,
):
    """The `/search` statement, with no database attached.

    Split out so the shape can be tested without a catalog (`tests/test_search_index.py`),
    the same way `trending.build_query` is.
    """
    return (
        select(Manga)
        .options(defer(Manga.embedding))
        .where(
            SEARCH_BLOB.like(like_pattern(term.lower()), escape="\\"),
            sa_text(safety_filter()),
        )
        .order_by(Manga.popularity.desc().nullslast(), Manga.id)
        .offset(offset)
        .limit(limit)
    )


async def search_titles(
    session: AsyncSession,
    term: str,
    *,
    limit: int = SEARCH_RESULT_LIMIT,
    offset: int = 0,
) -> List[Manga]:
    """Titles whose names or alternative titles contain `term`, one page at a time.

    Three things changed in Stage 7 (API-08):

    * **One indexed predicate.** The old statement ORed four `ILIKE`s, one of
      them over `array_to_string(alternative_titles, ' ')`, which no index can
      serve -- so every keystroke scanned all 95,626 rows (**270-390 ms warm**).
      It now matches `SEARCH_BLOB`, the exact expression behind
      `idx_manga_search_blob_trgm` (**3-14 ms** measured, bitmap index scan).
    * **A page, not ten rows.** `limit`/`offset` are bounded at the router.
    * **A total order.** `popularity DESC` alone is not a total order: rows that
      tie can be returned in either order, so consecutive pages could repeat or
      skip one. `id` breaks the tie, which is what makes `offset` paging stable.

    Public endpoint, so it applies the shared safety predicate rather than
    trusting a caller to pass `nsfw=False`.
    """
    stmt = build_search_statement(term, limit=limit, offset=offset)
    return list((await session.execute(stmt)).scalars().all())


async def similar_candidates(
    session: AsyncSession,
    manga_id: int,
    *,
    limit: int,
    offset: int = 0,
    allow_nsfw: bool = False,
) -> List[Dict[str, Any]]:
    """Neighbours of one title as `{"manga": row, "similarity_score": float}`.

    Two sources, in this order:

    1. the precomputed `similar_mangas` edges, while they are fresh (or when
       there is no vector to recompute from -- an old answer beats a 404);
    2. a live ANN query over the row's own embedding.

    Raises `MangaNotFound` for an unknown id and `NoSimilarityData` when the row
    has neither signal, which the router renders as a 404.
    """
    manga = await require_manga(session, manga_id, include_embedding=True)

    has_edges = bool(getattr(manga, "similar_mangas", None))
    edges_fresh = similar_edges_are_fresh(manga)
    if manga.embedding is None and not has_edges:
        raise NoSimilarityData(f"manga {manga_id} has neither an embedding nor edges")

    use_precomputed_edges = edges_fresh or manga.embedding is None
    candidates: List[Dict[str, Any]] = []
    # The edge list is a fixed, already-ordered answer; paginate it by slicing.
    take = max(0, offset) + max(1, limit)

    if use_precomputed_edges:
        # Resolve the whole edge list, then filter. Pre-slicing it to `limit + 10`
        # decided how many candidates could be considered before the NSFW filter
        # ran, so a later clean title could never fill the page.
        edge_items = list(manga.similar_mangas or [])
        rows = await get_mangas_by_ids(session, (item.get("id") for item in edge_items))
        for item in edge_items:
            neighbour = rows.get(item.get("id"))
            if neighbour is None or neighbour.id == manga_id:
                continue
            if not allow_nsfw and row_is_nsfw(neighbour):
                continue
            candidates.append({"manga": neighbour, "similarity_score": item.get("score", 0.0)})
            if len(candidates) >= take:
                break
        # The edge list has no SQL offset; slice the already-ordered page here.
        candidates = candidates[max(0, offset):take]

    if not candidates and manga.embedding is not None:
        candidates = await retrieve_similar_manga(
            session=session,
            query_embedding=manga.embedding,
            filters=RecommendFilters(nsfw=allow_nsfw),
            limit=max(1, limit),
            offset=max(0, offset),
            # Exclude the seed in SQL so an offset counts candidates, not the
            # seed it would have to drop afterwards (which shortened page 2+).
            exclude_id=manga_id,
            # Same neighbourhood floor as the title-seeded search: a live
            # neighbour list must not contain a row the seed is not near.
            min_similarity=SEED_MIN_SIMILARITY,
        )

    return [c for c in candidates if c["manga"].id != manga_id][:limit]
