"""Similarity retrieval: the ANN-first hybrid search (ARCH-10).

What is left of a 1,159-line god module that also held filters, tag alignment,
title resolution, diversity and roulette sampling. Those moved to

    query_filters.py   SQL predicates and bind parameters
    tag_alignment.py   category-weighted tag scoring
    title_match.py     exact vs close title resolution
    diversity.py       franchise key and page diversity
    roulette.py        sampling, Redis pool, roulette draw

What stays is the one thing that has to see the whole ranking at once: the
candidate pool, the score arithmetic, and the hydration of the rows it returns.
`apply_ann_settings` and `compute_pool_limit` live here because the ranking is
their only caller and the pgvector GUCs mean nothing outside it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db_models import Manga
from ..models import RecommendFilters
from .format import infer_format_type
from .query_filters import apply_filter_criteria
# The ordering grammar and the seed floor live in `retrieval_ordering` so this
# module stays under the service line ceiling. Re-exported because callers
# (router, catalog, tests) import them from here.
from .retrieval_ordering import (
    SEED_MIN_SIMILARITY,
    SORT_IDS,
    browse_order_clause as _browse_order_clause,
    normalize_sort,
    text_order_clause as _text_order_clause,
)
from .safety import safety_filter
from .tag_alignment import build_tag_alignment_sql


async def apply_ann_settings(session: AsyncSession, ef_search: Optional[int] = None) -> None:
    """Apply the pgvector ANN settings for the current transaction.

    These must be set here rather than on the connection pool because pgvector is
    loaded lazily: until the `vector` type is used in a session the GUCs do not
    exist, so a startup parameter or a connect-time SET raises
    `unrecognized configuration parameter "hnsw.ef_search"`.

    `set_config(..., true)` is transaction-local, so a pooled connection is never
    left carrying one caller's setting -- the same reason
    `find_matched_title` sets the pg_trgm thresholds this way.

    `hnsw.iterative_scan = 'relaxed_order'` is what makes an ANN scan able to
    return more than `ef_search` rows. Measured against a 95k-row catalog:
    `ORDER BY embedding <=> q LIMIT 100` returned 39 rows with the default
    `ef_search = 40`, and 100 once relaxed_order was on.
    """
    ef = int(ef_search if ef_search is not None else settings.HNSW_EF_SEARCH)
    iterative = (settings.HNSW_ITERATIVE_SCAN or "off").strip().lower()
    if iterative not in ("off", "relaxed_order", "strict_order"):
        iterative = "off"
    await session.execute(
        text(
            "SELECT set_config('hnsw.ef_search', :ef, true), "
            "set_config('hnsw.iterative_scan', :iterative, true)"
        ),
        {"ef": str(ef), "iterative": iterative},
    )


def compute_pool_limit(offset: int, limit: int) -> int:
    """ANN candidate budget for one page.

    The pool has to cover the requested page *before* the CTE's title
    de-duplication and relevance filter run, so it scales with `offset + limit`
    and multiplies by a headroom factor.

    The previous formula clamped the result to `HNSW_EF_SEARCH` (200), which made
    the offset term inert -- every page asked for exactly 200 candidates, so
    anything past the first few pages was silently unreachable. The ceiling is
    now a separate setting, and completeness is delivered by
    `hnsw.iterative_scan` rather than by keeping the pool small.
    """
    needed = max(0, int(offset)) + max(1, int(limit))
    pool = max(settings.HNSW_EF_SEARCH, needed * max(1, settings.HNSW_POOL_HEADROOM))
    return min(pool, max(settings.HNSW_EF_SEARCH, settings.HNSW_MAX_POOL_LIMIT))


def similar_edges_are_fresh(manga: Any, max_age_days: Optional[int] = None) -> bool:
    """Is this row's precomputed `similar_mangas` list still usable?

    The edges are produced only by the precomputation job, which used to skip any
    row that already had them, so a re-embedded title kept neighbours calculated
    from its old vector forever. `similarities_computed_at` existed but nothing
    read it.

    A row is usable only when it has edges *and* a timestamp inside the window.
    A row with edges but no timestamp is treated as stale, because its age is
    unknown rather than zero. Rows the ingestion pipeline invalidated have both
    fields cleared, so they also read as not-fresh and fall back to a live ANN
    query.
    """
    edges = getattr(manga, "similar_mangas", None)
    if not edges:
        return False

    written_at = getattr(manga, "similarities_computed_at", None)
    if written_at is None:
        return False

    days = settings.SIMILAR_EDGES_MAX_AGE_DAYS if max_age_days is None else max_age_days
    if days <= 0:
        return True

    now = datetime.now(timezone.utc)
    if written_at.tzinfo is None:
        written_at = written_at.replace(tzinfo=timezone.utc)
    return (now - written_at) <= timedelta(days=days)


# Columns every candidate query returns. Kept at module scope so the
# embedding-free browse query and the ANN query hydrate through one function.
CANDIDATE_COLUMNS = """
            id, anilist_id, mal_id, mangadex_id,
            title_romaji, title_english, title_native,
            synopsis, genres, tags, inferred_tags, status, start_year,
            chapters, volumes, average_score, popularity,
            cover_image_url, banner_image, site_url, alternative_titles
    """

def _hydrate_candidates(rows) -> List[Dict[str, Any]]:
    """Turn result rows into the `{"manga", "similarity_score", ...}` shape.

    Shared by the ANN query and the embedding-free browse query. A browse row
    has no `hybrid_score`, so the displayed match stays None instead of a
    fabricated number.
    """
    candidates = []
    for r in rows:
        m = Manga()
        m.id = r.id
        m.anilist_id = r.anilist_id
        m.mal_id = r.mal_id
        m.mangadex_id = r.mangadex_id
        m.title_romaji = r.title_romaji
        m.title_english = r.title_english
        m.title_native = r.title_native
        m.synopsis = r.synopsis
        m.genres = r.genres
        m.tags = r.tags
        m.inferred_tags = r.inferred_tags
        m.status = r.status
        m.start_year = r.start_year
        m.chapters = r.chapters
        m.volumes = r.volumes
        m.average_score = r.average_score
        m.popularity = r.popularity
        m.cover_image_url = r.cover_image_url
        m.banner_image = r.banner_image
        m.site_url = r.site_url
        m.format_type = getattr(r, "format_type", None) or infer_format_type(
            r.title_native, r.tags, r.genres, r.site_url, r.inferred_tags
        )

        # The displayed score is the score the ranking actually used.
        #
        # It used to be floored: `max(score, 0.96)` for an exact title and
        # `max(score, 0.88)` for a prefix, applied after the query ran. That
        # turned a real 0.42 similarity into a rendered "96%", and it made
        # three genuinely different matches (Berserk: The Prototype, Berserk:
        # The Flame Dragon Knight, Berserk of Gluttony) all render as exactly
        # "88%" -- the floor value, not a measured one.
        #
        # The title preference is not lost by removing this: `title_boost`
        # already enters `hybrid_score` as a 0.30-weighted term in the SQL, so
        # exact and prefix hits still rank first. Only the dishonest number is
        # gone.
        hybrid = getattr(r, "hybrid_score", None)

        cand_dict = {
            "manga": m,
            "similarity_score": float(hybrid) if hybrid is not None else None,
            "title_boost": float(getattr(r, "title_boost", 0.0) or 0.0),
            "format_type": m.format_type
        }
        if hasattr(r, 'tag_alignment'):
            cand_dict["tag_alignment"] = round(float(r.tag_alignment), 4)

        candidates.append(cand_dict)

    return candidates


async def retrieve_similar_manga(
    session: AsyncSession,
    query_embedding: Any,
    filters: Optional[RecommendFilters] = None,
    limit: int = 20,
    offset: int = 0,
    query_text: Optional[str] = None,
    query_inferred_tags: Optional[List[Dict[str, Any]]] = None,
    enable_inferred_tags: Optional[bool] = None,
    category_weights: Optional[Dict[str, float]] = None,
    tag_boost: Optional[float] = None,
    exclude_id: Optional[int] = None,
    sort: str = "default",
    min_similarity: Optional[float] = None,
):
    if isinstance(query_embedding, str):
        emb_str = query_embedding
    else:
        emb_list = list(query_embedding) if hasattr(query_embedding, '__iter__') else query_embedding
        emb_str = "[" + ",".join(map(str, emb_list)) + "]"
    
    where_clauses = ["embedding IS NOT NULL"]
    params: Dict[str, Any] = {"emb": emb_str, "limit": limit, "offset": offset}

    # Excluding the seed row in SQL keeps page offsets exact: filtering it out
    # in Python after retrieval consumed an extra candidate, so the next page
    # started one row too early and repeated a title.
    if exclude_id is not None:
        params["exclude_id"] = exclude_id
        where_clauses.append("id <> :exclude_id")

    if isinstance(filters, dict):
        filters = RecommendFilters(**filters)

    allow_nsfw = filters.nsfw if filters and filters.nsfw is not None else False
    nsfw_predicate = safety_filter(allow_nsfw)
    if nsfw_predicate:
        where_clauses.append(nsfw_predicate)

    apply_filter_criteria(filters, where_clauses, params)

    where_str = " AND ".join(where_clauses)

    # Inferred tags category-aware ranking configuration
    should_rank_tags = enable_inferred_tags if enable_inferred_tags is not None else settings.ENABLE_INFERRED_TAG_RANKING
    if should_rank_tags and query_inferred_tags:
        tag_select_sql, tag_boost_sql, tag_params = build_tag_alignment_sql(
            query_inferred_tags, category_weights, tag_boost
        )
        params.update(tag_params)
    else:
        tag_select_sql = "0.0 as tag_alignment,"
        tag_boost_sql = ""

    clean_q = query_text.strip().lower() if (query_text and query_text.strip()) else None
    if clean_q:
        params["clean_q"] = clean_q
        params["prefix_q"] = f"{clean_q}%"
        params["contain_q"] = f"%{clean_q}%"
        title_boost_select = """
            CASE 
              WHEN LOWER(COALESCE(title_english, '')) = :clean_q OR LOWER(COALESCE(title_romaji, '')) = :clean_q OR LOWER(COALESCE(title_native, '')) = :clean_q THEN 1.0
              WHEN LOWER(COALESCE(title_english, '')) LIKE :prefix_q OR LOWER(COALESCE(title_romaji, '')) LIKE :prefix_q THEN 0.6
              WHEN LOWER(COALESCE(title_english, '')) LIKE :contain_q OR LOWER(COALESCE(title_romaji, '')) LIKE :contain_q OR LOWER(COALESCE(array_to_string(alternative_titles, ' '), '')) LIKE :contain_q THEN 0.3
              ELSE 0.0
            END as title_boost,
        """
        score_calc = f"""
            (
              0.55 * sim +
              0.30 * title_boost +
              0.08 * (COALESCE(average_score, 50) / 100.0) +
              0.07 * (LOG(GREATEST(COALESCE(popularity, 1), 1)) / 6.0)
              {tag_boost_sql}
            ) as hybrid_score
        """
    else:
        title_boost_select = "0.0 as title_boost,"
        score_calc = f"""
            (
              0.70 * sim +
              0.18 * (COALESCE(average_score, 50) / 100.0) +
              0.12 * (LOG(GREATEST(COALESCE(popularity, 1), 1)) / 6.0)
              {tag_boost_sql}
            ) as hybrid_score
        """

    relevance_conditions = []
    if clean_q:
        # A title-word match is admitted even when `sim` is low -- that is the
        # whole point of the word rule. An extra absolute floor ANDed here would
        # cancel it ("Berserk of Gluttony" at 0.327 next to "Berserk").
        relevance_conditions.append(f"(title_boost > 0 OR sim >= {SEED_MIN_SIMILARITY})")
    elif min_similarity is not None:
        # A seed (title) search with no query text has no title rule to lean on,
        # so the caller passes an absolute floor. Applied to `sim`, not
        # `hybrid_score`: popularity and score must not buy a row into a
        # neighbourhood it is not semantically in.
        params["min_similarity"] = float(min_similarity)
        relevance_conditions.append("sim >= :min_similarity")
    if filters and filters.min_match_pct and filters.min_match_pct > 0:
        params["min_pct"] = float(filters.min_match_pct)
        relevance_conditions.append("hybrid_score >= :min_pct")

    where_filter_sql = ""
    if relevance_conditions:
        where_filter_sql = "WHERE " + " AND ".join(relevance_conditions)

    # ------------------------------------------------------------------
    # ANN-first retrieval.
    # ORDER BY distance + LIMIT is what lets the planner use
    # idx_manga_embedding_hnsw. Ranking and dedup then run on a bounded
    # candidate pool instead of scanning the whole partitioned table.
    # ------------------------------------------------------------------
    pool_limit = compute_pool_limit(offset, limit)
    params["pool_limit"] = pool_limit

    # pgvector runs at its default ef_search (40) and with iterative_scan off
    # unless this is set, which caps an ordered ANN scan at ef_search candidates:
    # `LIMIT 100` returned 39 rows. apply_ann_settings is transaction-local, so it
    # has to precede the query on the same session.
    await apply_ann_settings(session)

    pool_columns = CANDIDATE_COLUMNS

    cte_sql = f"""vector_pool AS (
          SELECT {pool_columns},
                 (1 - (embedding <=> CAST(:emb AS vector))) AS sim
          FROM manga
          WHERE {where_str}
          ORDER BY embedding <=> CAST(:emb AS vector)
          LIMIT :pool_limit
        )"""

    if clean_q:
        params["title_limit"] = max(50, limit * 5)
        cte_sql += f""",
        title_pool AS (
          SELECT {pool_columns},
                 (1 - (embedding <=> CAST(:emb AS vector))) AS sim
          FROM manga
          WHERE {where_str}
            AND (
              LOWER(COALESCE(title_english, '')) LIKE :contain_q
              OR LOWER(COALESCE(title_romaji, '')) LIKE :contain_q
              OR LOWER(COALESCE(title_native, '')) LIKE :contain_q
            )
          ORDER BY (1 - (embedding <=> CAST(:emb AS vector))) DESC
          LIMIT :title_limit
        )"""

    union_clause = "\n          UNION\n          SELECT * FROM title_pool" if clean_q else ""
    tag_select_final = tag_select_sql.rstrip().rstrip(",")

    cte_sql += f""",
        candidates AS (
          SELECT * FROM vector_pool{union_clause}
        ),
        ranked AS (
          SELECT *,
            {title_boost_select}
            {tag_select_final},
            ROW_NUMBER() OVER (
              PARTITION BY LOWER(COALESCE(title_english, title_romaji, id::text))
              ORDER BY sim DESC, popularity DESC NULLS LAST
            ) as rn,
            ROW_NUMBER() OVER (
              PARTITION BY COALESCE(anilist_id, mal_id, id)
              ORDER BY sim DESC, popularity DESC NULLS LAST
            ) as rn_work
          FROM candidates
        ),
        scored AS (
          SELECT *,
            {score_calc}
          FROM ranked
          WHERE rn = 1 AND rn_work = 1
        )"""

    sql = text(f"""
        WITH {cte_sql}
        SELECT *
        FROM scored
        {where_filter_sql}
        ORDER BY {_text_order_clause(sort)}
        LIMIT :limit OFFSET :offset;
    """)

    legacy_sql = text(f"""
        WITH ranked AS (
          SELECT {pool_columns},
            (1 - (embedding <=> CAST(:emb AS vector))) as sim,
            {title_boost_select}
            {tag_select_final},
            ROW_NUMBER() OVER (
              PARTITION BY LOWER(COALESCE(title_english, title_romaji, id::text))
              ORDER BY (1 - (embedding <=> CAST(:emb AS vector))) DESC, popularity DESC NULLS LAST
            ) as rn,
            ROW_NUMBER() OVER (
              PARTITION BY COALESCE(anilist_id, mal_id, id)
              ORDER BY (1 - (embedding <=> CAST(:emb AS vector))) DESC, popularity DESC NULLS LAST
            ) as rn_work
          FROM manga
          WHERE {where_str}
        ),
        scored AS (
          SELECT *, {score_calc}
          FROM ranked
          WHERE rn = 1 AND rn_work = 1
        )
        SELECT *
        FROM scored
        {where_filter_sql}
        ORDER BY {_text_order_clause(sort)}
        LIMIT :limit OFFSET :offset;
    """)

    result = await session.execute(sql, params)
    rows = result.all()

    # Selective SQL filters can still shrink the pool below the requested page,
    # because the HNSW index cannot apply them and they are checked per candidate.
    # This retry drops the explicit ORDER BY ... LIMIT pool and lets the planner
    # choose; note that with the HNSW index available the planner may still use
    # it, so this is a second plan rather than a guaranteed exact scan. A truly
    # exact scan costs ~5.6 s for 300 rows on a 95k-row catalog and is not
    # something to put on a request path.
    if filters is not None and len(rows) < max(1, limit) and settings.DB_ENABLE_HNSW_FALLBACK:
        try:
            result = await session.execute(legacy_sql, params)
            rows = result.all()
        except Exception:
            pass

    return _hydrate_candidates(rows)


async def retrieve_catalog_page(
    session: AsyncSession,
    filters: Optional[RecommendFilters] = None,
    sort: str = "default",
    limit: int = 20,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """One page of the catalogue when there is no query vector.

    Filter-only discovery: genres/status/score/year are the whole request, so
    there is nothing to embed and no ANN ordering. The predicates come from the
    same `apply_filter_criteria` / `safety_filter` pair the text path uses, so a
    filter cannot mean one thing here and another in search.

    `limit + 1` is the caller's job: `has_more` needs one extra row and this
    function returns exactly the page it was asked for.
    """
    if isinstance(filters, dict):
        filters = RecommendFilters(**filters)

    where_clauses: List[str] = []
    params: Dict[str, Any] = {"limit": limit, "offset": offset}

    allow_nsfw = filters.nsfw if filters and filters.nsfw is not None else False
    nsfw_predicate = safety_filter(allow_nsfw)
    if nsfw_predicate:
        where_clauses.append(nsfw_predicate)

    apply_filter_criteria(filters, where_clauses, params)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = text(f"""
        SELECT {CANDIDATE_COLUMNS}
        FROM manga
        {where_sql}
        ORDER BY {_browse_order_clause(sort)}
        LIMIT :limit OFFSET :offset;
    """)

    result = await session.execute(sql, params)
    return _hydrate_candidates(result.all())
