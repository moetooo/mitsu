import random
import hashlib
import json
import asyncio
import time
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any, Set, Tuple
from ..db_models import Manga
from ..models import RecommendFilters
from ..services import cache
from ..config import settings
from ..enrichment.vocabulary import CANONICAL_VOCABULARY
from .safety import safety_filter
from .format import (
    build_format_sql_condition as _build_format_sql_condition,
    infer_format_type as _infer_format_type,
)

DEFAULT_CATEGORY_WEIGHTS: Dict[str, float] = {
    "relationship": 1.00,
    "trope": 1.00,
    "theme": 0.90,
    "setting": 0.80,
    "genre": 0.60,
    "demographic": 0.30,
    "format": 0.15,
}

def compute_category_aware_tag_alignment(
    query_tags: Optional[List[Dict[str, Any]]],
    candidate_tags: Optional[List[Dict[str, Any]]],
    category_weights: Optional[Dict[str, float]] = None
) -> float:
    """
    Computes normalized category-aware tag alignment between query tags and candidate tags.
    Formula:
        tag_alignment = weighted_shared_tags / weighted_query_tags
    Clamped to [0.0, 1.0].
    """
    if not query_tags or not candidate_tags:
        return 0.0

    weights = category_weights or DEFAULT_CATEGORY_WEIGHTS

    cand_slugs = {
        t.get("slug") for t in candidate_tags
        if isinstance(t, dict) and t.get("slug")
    }

    weighted_shared = 0.0
    weighted_query = 0.0

    seen_query_slugs = set()
    for t in query_tags:
        if not isinstance(t, dict):
            continue
        slug = t.get("slug")
        if not slug or slug in seen_query_slugs:
            continue
        seen_query_slugs.add(slug)

        cat = t.get("category")
        if not cat:
            tag_def = CANONICAL_VOCABULARY.get(slug)
            cat = tag_def.category.value if tag_def else "unknown"

        w = weights.get(cat, 0.50)
        weighted_query += w
        if slug in cand_slugs:
            weighted_shared += w

    if weighted_query <= 0.0:
        return 0.0

    alignment = weighted_shared / weighted_query
    return max(0.0, min(1.0, alignment))


def build_tag_alignment_sql(
    query_tags: Optional[List[Dict[str, Any]]],
    category_weights: Optional[Dict[str, float]] = None,
    tag_boost: Optional[float] = None
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Constructs SQL expressions and parameters for category-aware tag alignment.
    Returns:
        tag_select_clause: String to include in SELECT of ranked CTE
        tag_boost_score_expr: String to add to hybrid_score in scored CTE
        params: Dict of parameter bindings
    """
    weights = category_weights or DEFAULT_CATEGORY_WEIGHTS
    boost = tag_boost if tag_boost is not None else settings.INFERRED_TAG_BOOST

    if not query_tags:
        return "0.0 as tag_alignment,", "", {}

    params: Dict[str, Any] = {"tag_boost": float(boost)}
    weighted_query = 0.0
    case_terms = []

    seen_slugs = set()
    for idx, t in enumerate(query_tags):
        if not isinstance(t, dict):
            continue
        slug = t.get("slug")
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        cat = t.get("category")
        if not cat:
            tag_def = CANONICAL_VOCABULARY.get(slug)
            cat = tag_def.category.value if tag_def else "unknown"

        w = float(weights.get(cat, 0.50))
        weighted_query += w

        param_key = f"q_tag_{idx}"
        params[param_key] = json.dumps([{"slug": slug}])
        case_terms.append(
            f"(CASE WHEN inferred_tags IS NOT NULL AND inferred_tags @> CAST(:{param_key} AS jsonb) THEN {w} ELSE 0.0 END)"
        )

    if weighted_query <= 0.0 or not case_terms:
        return "0.0 as tag_alignment,", "", {}

    sum_terms = " + ".join(case_terms)
    tag_select = f"LEAST(1.0, GREATEST(0.0, ({sum_terms}) / {weighted_query})) as tag_alignment,"
    tag_score_add = " + (:tag_boost * tag_alignment)"

    return tag_select, tag_score_add, params

ROULETTE_POOL_TARGET = 50
ROULETTE_REFILL_THRESHOLD = 15

HANGUL_RE = re.compile(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]')
KANA_RE = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
HANZI_RE = re.compile(r'[\u4e00-\u9fff]')

def generate_filter_hash(filters: Optional[RecommendFilters]) -> str:
    """Generates a stable MD5 fingerprint hash for a filter set"""
    if not filters:
        return "default"
    filter_dict = filters.model_dump(exclude_none=True)
    filter_str = json.dumps(filter_dict, sort_keys=True)
    return hashlib.md5(filter_str.encode()).hexdigest()[:12]

def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


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


def is_confident_title_match(query: str, title: Optional[str], sim: float, word_sim: float) -> Tuple[bool, str]:
    """Should a fuzzy trigram hit be treated as "the user typed this title"?

    Returns (accepted, reason_if_rejected) so callers and tests can say why.

    The old rule was `match_score >= 0.48 or sim >= 0.40 or word_sim >= 0.65`.
    The `word_sim >= 0.65` arm is the problem: `word_similarity` is 1.000
    whenever one query word occurs in the title, so "cooking", "survival" and
    "detective" all resolved to a single title. Measured: 10 of 12 thematic
    queries took the title branch.

    A verbatim word fragment is therefore rejected. A misspelling cannot appear
    verbatim in a title -- over 8 measured misspellings the highest
    word_similarity is 0.933 -- so this veto costs no typo tolerance. It is also
    the only rule here that does not need re-tuning as the catalogue grows.
    """
    if not query or not title:
        return False, "no-title"

    q = query.strip().lower()
    t = title.strip().lower()
    if not q or not t:
        return False, "no-title"

    # The user typed the title exactly; the exact-match query already caught that
    # case, so reaching here with identical text means a different row collided.
    if q == t:
        return True, ""

    if word_sim >= settings.TITLE_MATCH_MAX_WORD_SIM:
        return False, "verbatim-fragment"

    if sim < settings.TITLE_MATCH_MIN_SIM:
        return False, "similarity"

    coverage = len(q) / len(t)
    if not (settings.TITLE_MATCH_MIN_COVERAGE <= coverage <= settings.TITLE_MATCH_MAX_COVERAGE):
        return False, "coverage"

    return True, ""


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


def _tag_json_condition(tag_name: str, key: str, params: Optional[Dict[str, Any]]) -> str:
    """JSONB containment on tags; bound as a parameter when params is given."""
    if params is None:
        return "tags @> '[{\"name\": \"" + _sql_literal(tag_name) + "\"}]'"
    params[key] = json.dumps([{"name": tag_name}])
    return "tags @> CAST(:" + key + " AS jsonb)"


def _array_contains_condition(value: str, key: str, params: Optional[Dict[str, Any]]) -> str:
    """genres @> ARRAY[...] containment; bound as a parameter when params is given."""
    if params is None:
        return "genres @> ARRAY['" + _sql_literal(value) + "']"
    params[key] = [value]
    return "genres @> CAST(:" + key + " AS text[])"


def build_genre_sql_condition(
    genres_list: Optional[List[str]],
    exclude: bool = False,
    params: Optional[Dict[str, Any]] = None,
    key_prefix: str = "genre",
) -> Optional[str]:
    """Builds an exhaustive SQL condition across PostgreSQL text array genres and JSONB tags.

    When params is supplied, every user-provided genre is emitted as a bind
    parameter so the statement text stays constant across requests and can be
    planned and cached by PostgreSQL. Without params the legacy inline form is
    produced (used by unit tests).
    """
    if not genres_list:
        return None

    conditions: List[str] = []
    for idx, genre in enumerate(genres_list):
        if not isinstance(genre, str) or not genre.strip():
            continue
        low = genre.lower().strip()
        # Include and exclude lists need distinct bind names, otherwise the
        # exclusion overwrites the inclusion and the two conditions cancel out.
        key = key_prefix + "_" + str(idx)

        if low in ("yaoi", "bl", "boys' love"):
            conditions.append("(" + " OR ".join([
                _array_contains_condition("Boys' Love", key + "_arr", params),
                _tag_json_condition("Boys' Love", key + "_t1", params),
                _tag_json_condition("Yaoi", key + "_t2", params),
            ]) + ")")
        elif low in ("yuri", "gl", "girls' love"):
            conditions.append("(" + " OR ".join([
                _array_contains_condition("Girls' Love", key + "_arr", params),
                _tag_json_condition("Girls' Love", key + "_t1", params),
                _tag_json_condition("Yuri", key + "_t2", params),
            ]) + ")")
        elif low in ("shoujo ai", "shoujo-ai"):
            conditions.append("(" + " OR ".join([
                _tag_json_condition("Shoujo Ai", key + "_t1", params),
                _tag_json_condition("Girls' Love", key + "_t2", params),
                _tag_json_condition("Yuri", key + "_t3", params),
            ]) + ")")
        elif low in ("shounen ai", "shounen-ai"):
            conditions.append("(" + " OR ".join([
                _tag_json_condition("Shounen Ai", key + "_t1", params),
                _tag_json_condition("Boys' Love", key + "_t2", params),
                _tag_json_condition("Yaoi", key + "_t3", params),
            ]) + ")")
        elif low in ("shounen", "shoujo", "seinen", "josei", "harem", "reverse harem", "love triangle"):
            conditions.append(_tag_json_condition(genre, key + "_tag", params))
        else:
            conditions.append("(" + " OR ".join([
                _array_contains_condition(genre, key + "_arr", params),
                _tag_json_condition(genre, key + "_tag", params),
            ]) + ")")

    if not conditions:
        return None
    combined = " OR ".join(conditions)
    if exclude:
        return "NOT (" + combined + ")"
    return "(" + combined + ")"

def build_format_sql_condition(raw_fmts: List[str]) -> Optional[str]:
    """Format filter over the stored `manga.format_type` column (ARCH-05).

    Re-exported so existing callers keep working; the definition lives in
    `app/services/format.py` next to the classifier that fills the column.
    """
    return _build_format_sql_condition(raw_fmts)


def apply_filter_criteria(
    filters: Optional[RecommendFilters],
    where_clauses: List[str],
    params: Dict[str, Any]
) -> None:
    """Applies structured RecommendFilters criteria into parameterized WHERE clauses and bind params."""
    if not filters:
        return

    if filters.status:
        status_placeholders = []
        for idx, st_val in enumerate(filters.status):
            p_key = f"st_{idx}"
            params[p_key] = st_val
            status_placeholders.append(f":{p_key}")
        where_clauses.append(f"status IN ({', '.join(status_placeholders)})")

    if filters.min_year is not None:
        params["min_year"] = filters.min_year
        where_clauses.append("start_year >= :min_year")

    if filters.max_year is not None:
        params["max_year"] = filters.max_year
        where_clauses.append("start_year <= :max_year")

    if filters.min_score is not None:
        params["min_score"] = filters.min_score
        where_clauses.append("average_score >= :min_score")

    if filters.min_chapters is not None:
        params["min_chapters"] = filters.min_chapters
        where_clauses.append("chapters >= :min_chapters")

    if filters.max_chapters is not None:
        params["max_chapters"] = filters.max_chapters
        where_clauses.append("chapters <= :max_chapters")

    if filters.genres:
        cond = build_genre_sql_condition(
            filters.genres, exclude=False, params=params, key_prefix="genre"
        )
        if cond:
            where_clauses.append(cond)

    if filters.exclude_genres:
        cond = build_genre_sql_condition(
            filters.exclude_genres, exclude=True, params=params, key_prefix="exclude_genre"
        )
        if cond:
            where_clauses.append(cond)

    if filters.format_type:
        raw_fmts = filters.format_type if isinstance(filters.format_type, list) else [filters.format_type]
        fmt_cond = build_format_sql_condition(raw_fmts)
        if fmt_cond:
            where_clauses.append(fmt_cond)


def infer_format_type(*args, **kwargs) -> str:
    """Re-export of `app.services.format.infer_format_type` (ARCH-05)."""
    return _infer_format_type(*args, **kwargs)


async def find_matched_title(
    session: AsyncSession,
    query: Optional[str] = None
) -> Optional[Tuple[int, str, List[float], float]]:
    """
    Identifies if a search query targets a specific manga title (including typos/misspellings)
    using exact matching, prefix matching, and trigram/word similarity via pg_trgm GIN indexes.
    Returns (manga_id, matched_title, embedding_list, match_score) or None.
    """
    if not query or not query.strip():
        return None
    clean_q = query.strip().lower()
    if len(clean_q) < 3:
        return None

    # 1. Exact title match (case-insensitive)
    res = await session.execute(text("""
        SELECT id, title_english, title_romaji, embedding::real[], popularity
        FROM manga
        WHERE (
            LOWER(title_english) = :q 
            OR LOWER(title_romaji) = :q
            OR LOWER(COALESCE(title_native, '')) = :q
            OR EXISTS (
                SELECT 1
                FROM unnest(COALESCE(alternative_titles, '{}')) AS alt(t)
                WHERE LOWER(t) = :q
            )
        )
          AND embedding IS NOT NULL
        ORDER BY popularity DESC NULLS LAST
        LIMIT 1;
    """), {'q': clean_q})
    exact = res.fetchone()
    if exact:
        try:
            return exact[0], exact[1] or exact[2], exact[3], 1.0
        except Exception:
            pass

    # 2. Fast Trigram / word similarity match using GIN indexes
    # One round-trip and transaction-local, so pooled connections never inherit these.
    await session.execute(text(
        "SELECT set_config('pg_trgm.word_similarity_threshold', '0.40', true), "
        "set_config('pg_trgm.similarity_threshold', '0.30', true);"
    ))
    res = await session.execute(text("""
        SELECT id, title_english, title_romaji, embedding::real[], popularity,
               GREATEST(similarity(:q, LOWER(COALESCE(title_english, ''))), similarity(:q, LOWER(COALESCE(title_romaji, '')))) as sim,
               GREATEST(word_similarity(:q, LOWER(COALESCE(title_english, ''))), word_similarity(:q, LOWER(COALESCE(title_romaji, '')))) as w_sim,
               (
                   0.55 * GREATEST(similarity(:q, LOWER(COALESCE(title_english, ''))), similarity(:q, LOWER(COALESCE(title_romaji, ''))))
                   + 0.25 * GREATEST(word_similarity(:q, LOWER(COALESCE(title_english, ''))), word_similarity(:q, LOWER(COALESCE(title_romaji, ''))))
                   + 0.20 * (LOG(GREATEST(COALESCE(popularity, 1), 1)) / 6.0)
               ) as match_score
        FROM manga
        WHERE (:q <% title_english OR :q <% title_romaji OR title_english % :q OR title_romaji % :q)
          AND embedding IS NOT NULL
        ORDER BY match_score DESC
        LIMIT 5;
    """), {'q': clean_q})

    # A few candidates rather than one: the best-scoring hit may be a verbatim
    # word fragment (a theme, not a title) while the second is the real title.
    for mid, t_en, t_ro, emb, pop, sim, w_sim, score in res.fetchall():
        name = t_en or t_ro
        accepted, _reason = is_confident_title_match(clean_q, name, float(sim), float(w_sim))
        if accepted:
            return mid, name, emb, float(score)

    return None

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
        relevance_conditions.append("(title_boost > 0 OR sim >= 0.44)")
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

    pool_columns = """
            id, anilist_id, mal_id, mangadex_id,
            title_romaji, title_english, title_native,
            synopsis, genres, tags, inferred_tags, status, start_year,
            chapters, volumes, average_score, popularity,
            cover_image_url, banner_image, site_url, alternative_titles
    """

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
            ) as rn
          FROM candidates
        ),
        scored AS (
          SELECT *,
            {score_calc}
          FROM ranked
          WHERE rn = 1
        )"""

    sql = text(f"""
        WITH {cte_sql}
        SELECT *
        FROM scored
        {where_filter_sql}
        ORDER BY hybrid_score DESC, id ASC
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
            ) as rn
          FROM manga
          WHERE {where_str}
        ),
        scored AS (
          SELECT *, {score_calc}
          FROM ranked
          WHERE rn = 1
        )
        SELECT *
        FROM scored
        {where_filter_sql}
        ORDER BY hybrid_score DESC, id ASC
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
        score_val = float(r.hybrid_score)

        cand_dict = {
            "manga": m,
            "similarity_score": score_val,
            "title_boost": float(getattr(r, "title_boost", 0.0) or 0.0),
            "format_type": m.format_type
        }
        if hasattr(r, 'tag_alignment'):
            cand_dict["tag_alignment"] = round(float(r.tag_alignment), 4)

        candidates.append(cand_dict)

    return candidates

# =========================================================
# PRODUCTION DIVERSITY & NON-ORDER-BY-RANDOM SAMPLING
# =========================================================

# Trailing markers that distinguish a volume/season entry from the series itself.
_VOLUME_MARKER = re.compile(
    r"\s*[\u2013\u2014-]?\s*(?:vol(?:ume)?\.?|book|part|season|season\s+\d+|"
    r"chapter|ch\.|#)\s*\d+\s*$",
    re.IGNORECASE,
)


def franchise_key(title: Optional[str], row_id: Any = None) -> str:
    """A normalized key used to keep one series from filling a whole page.

    This replaces `title.lower()[:15]`. The blind 15-character cut merged
    genuinely different series -- "Berserk" with "Berserk of Gluttony" -- and in
    this catalogue 81 different Gundam titles share one 15-character prefix, as
    do 79 villainess titles.

    The key is deliberately conservative: the whole normalized title, with a
    trailing volume/season/chapter marker removed. Two differently-named entries
    are therefore never merged, which is the failure mode that loses titles from
    a page. Merging a sequel into its parent is a nice-to-have and needs a real
    series identifier, not a title heuristic.
    """
    if not title or not str(title).strip():
        return f"id:{row_id}"

    text_value = str(title).strip().lower()
    # Unify the separators that catalogues use interchangeably.
    text_value = re.sub(r"[_/\\|~]", ":", text_value)
    text_value = re.sub(r"\s+", " ", text_value)
    # Drop a trailing volume/season marker, then any now-trailing punctuation.
    text_value = _VOLUME_MARKER.sub("", text_value)
    text_value = text_value.strip(" -\u2013\u2014:.,")
    return text_value or f"id:{row_id}"


def apply_diversity_filtering(rows: List[Any], exclude_ids: Set[int], max_target: int = 50) -> List[Dict[str, Any]]:
    """Applies lightweight rule-based diversity (genres, format, score bands, hidden gems)

    `exclude_ids` is honoured absolutely. It used to be undone: when every row was
    excluded the function restored the full unfiltered list, so marking a title as
    already-seen had no effect at exactly the moment it mattered. Relaxing the
    seen set is a product decision and belongs to the caller, which already does
    it explicitly for Discovery Roulette.
    """
    if not rows:
        return []

    # 1. Drop already-seen rows, then collapse repeats of the same series.
    seen_titles: Set[str] = set()
    filtered_rows = []

    for r in rows:
        if r.id in exclude_ids:
            continue
        stem = franchise_key(r.title_english or r.title_romaji or r.title_native, r.id)
        if stem in seen_titles:
            continue
        seen_titles.add(stem)
        filtered_rows.append(r)

    if not filtered_rows:
        # Nothing survived: either every candidate was already seen, or the page is
        # a single series. Returning the unfiltered rows here is what made
        # `exclude_ids` a no-op; the caller decides whether to relax it.
        return []

    # 2. Separate into High Confidence vs. Hidden Gems
    high_confidence = []
    hidden_gems = []

    for r in filtered_rows:
        score = r.average_score or 75
        pop = r.popularity or 10000
        # Hidden gem: solid score >= 75 but lower popularity / higher pop rank number
        if score >= 75 and pop > 8000:
            hidden_gems.append(r)
        else:
            high_confidence.append(r)

    random.shuffle(high_confidence)
    random.shuffle(hidden_gems)

    # 3. Target ratio: 80% High Confidence, 20% Hidden Gems
    target_gems_count = int(max_target * 0.20)
    selected_gems = hidden_gems[:target_gems_count]
    selected_conf = high_confidence[: max_target - len(selected_gems)]
    candidate_pool = selected_conf + selected_gems

    # 4. Enforce Genre Spread (Max 30% per genre)
    genre_counts: Dict[str, int] = {}
    diverse_selection = []
    max_per_genre = max(3, int(max_target * 0.30))

    for r in candidate_pool:
        primary_genre = r.genres[0] if (r.genres and len(r.genres) > 0) else "General"
        curr_count = genre_counts.get(primary_genre, 0)

        if curr_count < max_per_genre or len(diverse_selection) < 10:
            genre_counts[primary_genre] = curr_count + 1
            diverse_selection.append(r)

        if len(diverse_selection) >= max_target:
            break

    # If still below target, fill remaining with skipped rows
    if len(diverse_selection) < max_target:
        for r in candidate_pool:
            if r not in diverse_selection:
                diverse_selection.append(r)
            if len(diverse_selection) >= max_target:
                break

    random.shuffle(diverse_selection)

    # Format result dicts
    out = []
    for r in diverse_selection:
        title = r.title_english or r.title_romaji or r.title_native or "Unknown Title"
        fmt = getattr(r, "format_type", None) or infer_format_type(
            r.title_native, r.tags, r.genres, r.site_url
        )
        # No similarity is computed for roulette, so no similarity_score is
        # reported. The previous value was `average_score / 100` with a default
        # of 85 -- a community score presented as a match percentage, so an
        # unrated title claimed an 85% "match". `average_score` is already its
        # own field below.
        out.append({
            "id": r.id,
            "anilist_id": r.anilist_id,
            "mal_id": r.mal_id,
            "title": title,
            "cover_image_url": r.cover_image_url,
            "banner_image": r.banner_image,
            "synopsis": r.synopsis,
            "genres": r.genres,
            "tags": r.tags,
            "status": r.status,
            "start_year": r.start_year,
            "chapters": r.chapters,
            "volumes": r.volumes,
            "average_score": r.average_score,
            "similarity_score": None,
            "llm_reasoning": "Discovery Roulette candidate.",
            "format_type": fmt
        })

    return out


async def sample_candidates_from_db(
    session: AsyncSession,
    filters: Optional[RecommendFilters] = None,
    sample_limit: int = 150
) -> List[Any]:
    """Sample candidates from across the whole catalogue, cheaply.

    Ids follow ingestion order, so one contiguous block of them is one ingest
    batch, and therefore one source. Measured: 76% of a draw carried a MangaDex
    id against a 14% catalogue baseline, and every draw came from a single ingest
    day. The year spread did not change -- this catalogue is 99.8% 2000+ -- so
    source, not era, is what the block was skewing.

    This takes one short range from each of several evenly spaced slices of the
    id space instead. Each range is an index range scan, so the work is set by
    `ROULETTE_SAMPLE_BLOCKS` and the per-block width -- not by the table size.
    `ORDER BY random()` was the obvious alternative and was rejected: its cost
    grows with the catalogue and it would silently become the slowest query here
    as the table grows.
    """
    where_clauses = ["cover_image_url IS NOT NULL"]

    allow_nsfw = filters.nsfw if filters and filters.nsfw is not None else False
    nsfw_predicate = safety_filter(allow_nsfw)
    if nsfw_predicate:
        where_clauses.append(nsfw_predicate)

    rand_seed = f"seed_{random.randint(1, 999999999)}_{time.time()}"
    params: Dict[str, Any] = {
        "limit": sample_limit,
        "seed": rand_seed,
    }

    apply_filter_criteria(filters, where_clauses, params)

    where_str = " AND ".join(where_clauses)

    columns = """
          id, anilist_id, mal_id, mangadex_id, title_romaji, title_english, title_native,
          synopsis, genres, tags, status, start_year, chapters, volumes,
          average_score, popularity, cover_image_url, banner_image, site_url"""

    bounds = (await session.execute(text(
        "SELECT COALESCE(MIN(id), 0) AS lo, COALESCE(MAX(id), 0) AS hi FROM manga"
    ))).one()
    lo, hi = int(bounds.lo), int(bounds.hi)

    blocks = max(1, settings.ROULETTE_SAMPLE_BLOCKS)
    span = max(1, (sample_limit * max(1, settings.ROULETTE_SAMPLE_OVERSCAN)) // blocks)

    # One random start per slice, so a draw spans the catalogue instead of an era.
    slot = max(1, (hi - lo + 1) // blocks)
    starts = []
    for i in range(blocks):
        slot_lo = lo + i * slot
        start = slot_lo + random.randint(0, max(0, slot - span))
        starts.append(min(start, hi))

    params["starts"] = starts
    params["span"] = span

    # ORDER BY hashtext() sorts only the sampled ranges (blocks * span rows), so it
    # picks a random subset of them without sorting the table.
    sql = text(f"""
        WITH starts AS (SELECT unnest(CAST(:starts AS bigint[])) AS s)
        SELECT {columns}
        FROM manga, starts
        WHERE manga.id >= starts.s
          AND manga.id < starts.s + :span
          AND {where_str}
        ORDER BY hashtext(manga.id::text || :seed) DESC
        LIMIT :limit;
    """)

    result = await session.execute(sql, params)
    rows = list(result.all())

    if len(rows) < max(1, sample_limit // 4):
        # Selective filters can miss every sampled range. Only now pay for the
        # whole-table hash ordering, which is what the old path always did.
        fb = text(f"""
            SELECT {columns}
            FROM manga
            WHERE {where_str}
            ORDER BY hashtext(id::text || :seed) DESC
            LIMIT :limit;
        """)
        result = await session.execute(fb, params)
        rows = list(result.all())

    random.shuffle(rows)
    return rows



async def refill_roulette_pool(filters: Optional[RecommendFilters], session_id: Optional[str] = None):
    """Background pool refiller: fetches DB candidates, applies diversity, and pushes to Redis"""
    filter_hash = generate_filter_hash(filters)

    # Concurrency Lock: Prevent multiple background workers from refilling simultaneously
    locked = await cache.acquire_refill_lock(filter_hash, ttl=10)
    if not locked:
        return

    try:
        seen_set = set()
        if session_id:
            seen_set = await cache.get_session_seen(session_id)

        from ..db import AsyncSessionLocal
        async with AsyncSessionLocal() as bg_session:
            db_rows = await sample_candidates_from_db(bg_session, filters=filters, sample_limit=150)
            diverse_items = apply_diversity_filtering(db_rows, exclude_ids=seen_set, max_target=ROULETTE_POOL_TARGET)

            if diverse_items:
                random.shuffle(diverse_items)
                await cache.push_roulette_pool(filter_hash, diverse_items, ttl=1800)
    except Exception as e:
        pass
    finally:
        await cache.release_refill_lock(filter_hash)


async def retrieve_roulette_manga(
    session: AsyncSession,
    filters: Optional[RecommendFilters] = None,
    seen_ids: Optional[List[int]] = None,
    pool_limit: int = 1,
    session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Production roulette retriever serving instant results from Redis pool or fast DB fallback"""
    filter_hash = generate_filter_hash(filters)

    # 1. Combine client seen_ids and server session seen set
    server_seen = await cache.get_session_seen(session_id) if session_id else set()
    combined_seen = set(seen_ids or []).union(server_seen)

    # 2. Check current Redis candidate pool size
    pool_size = await cache.get_roulette_pool_size(filter_hash)

    # 3. Asynchronously trigger background pool refill if below threshold and active session
    if pool_size < ROULETTE_REFILL_THRESHOLD and session_id:
        asyncio.create_task(refill_roulette_pool(filters, session_id))

    # 4. Attempt popping from Redis candidate pool.
    #
    # This popped exactly `max(pool_limit, 4)` items. If all of them happened to
    # be in the session's seen set, the loop gave up and went to the database --
    # discarding a pool that might still hold dozens of unseen rows. The pool is
    # drained by LPOP, so those unseen rows were simply thrown away.
    # It now pops in bounded rounds until it has enough unseen rows, the pool is
    # empty, or the budget is spent.
    results = []
    if pool_size > 0:
        wanted = max(pool_limit, 4)
        budget = max(wanted * 4, ROULETTE_POOL_TARGET)
        unseen_items: List[dict] = []
        popped_total = 0
        while len(unseen_items) < pool_limit and popped_total < budget:
            round_size = min(wanted, budget - popped_total)
            popped_items = await cache.pop_roulette_pool(filter_hash, count=round_size)
            if not popped_items:
                break
            popped_total += len(popped_items)
            unseen_items.extend(
                item for item in popped_items if item["id"] not in combined_seen
            )
        if unseen_items:
            random.shuffle(unseen_items)
            results = unseen_items[:pool_limit]

    # 5. Fallback: If Redis empty or popped items were seen, query DB cleanly with dynamic seeds
    if not results:
        db_rows = await sample_candidates_from_db(session, filters=filters, sample_limit=80)
        results = apply_diversity_filtering(db_rows, exclude_ids=combined_seen, max_target=pool_limit)
        if not results:
            # Every row in this draw was already seen. Draw again before relaxing:
            # the sample is 80 rows out of ~95k, so a second draw almost always
            # contains unseen ones, whereas re-filtering the same 80 rows with an
            # empty exclusion set can only re-serve something already shown.
            retry_rows = await sample_candidates_from_db(session, filters=filters, sample_limit=80)
            results = apply_diversity_filtering(retry_rows, exclude_ids=combined_seen, max_target=pool_limit)
        if not results and db_rows:
            # Absolute fallback: the catalogue really is exhausted for this
            # session, so repeat rather than return nothing.
            results = apply_diversity_filtering(db_rows, exclude_ids=set(), max_target=pool_limit)
        if results:
            random.shuffle(results)

    # 6. Update server-authoritative seen set in Redis
    if results and session_id:
        served_ids = [r["id"] for r in results]
        await cache.add_session_seen(session_id, served_ids)

    return results
