import random
import hashlib
import json
import asyncio
import time
import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any, Set, Tuple
from ..db_models import Manga
from ..models import RecommendFilters
from ..services import cache
from ..config import settings
from ..enrichment.vocabulary import CANONICAL_VOCABULARY

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

def build_genre_sql_condition(genres_list: List[str], exclude: bool = False) -> Optional[str]:
    """Builds an exhaustive SQL condition across PostgreSQL text array genres and JSONB tags"""
    if not genres_list:
        return None
    conditions = []
    for g in genres_list:
        escaped = g.replace("'", "''")
        low = g.lower()
        if low in ['yaoi', 'bl', "boys' love"]:
            conditions.append("(genres @> ARRAY['Boys'' Love'] OR tags @> '[{\"name\": \"Boys'' Love\"}]' OR tags @> '[{\"name\": \"Yaoi\"}]')")
        elif low in ['yuri', 'gl', "girls' love"]:
            conditions.append("(genres @> ARRAY['Girls'' Love'] OR tags @> '[{\"name\": \"Girls'' Love\"}]' OR tags @> '[{\"name\": \"Yuri\"}]')")
        elif low in ['shoujo ai', 'shoujo-ai']:
            conditions.append("(tags @> '[{\"name\": \"Shoujo Ai\"}]' OR tags @> '[{\"name\": \"Girls'' Love\"}]' OR tags @> '[{\"name\": \"Yuri\"}]')")
        elif low in ['shounen ai', 'shounen-ai']:
            conditions.append("(tags @> '[{\"name\": \"Shounen Ai\"}]' OR tags @> '[{\"name\": \"Boys'' Love\"}]' OR tags @> '[{\"name\": \"Yaoi\"}]')")
        elif low in ['shounen', 'shoujo', 'seinen', 'josei']:
            conditions.append(f"tags @> '[{{\"name\": \"{escaped}\"}}]'")
        elif low in ['harem', 'reverse harem', 'love triangle']:
            conditions.append(f"tags @> '[{{\"name\": \"{escaped}\"}}]'")
        else:
            conditions.append(f"(genres @> ARRAY['{escaped}'] OR tags @> '[{{\"name\": \"{escaped}\"}}]')")

    if not conditions:
        return None
    combined = " OR ".join(conditions)
    if exclude:
        return f"NOT ({combined})"
    return f"({combined})"

def build_format_sql_condition(raw_fmts: List[str]) -> Optional[str]:
    """Builds an accurate SQL condition distinguishing Japanese Manga from Korean Manhwa and Chinese Manhua."""
    if not raw_fmts:
        return None
    fmt_conditions = []
    for f in raw_fmts:
        ft = f.lower().strip()
        if ft == 'manhwa':
            fmt_conditions.append(
                "("
                "("
                "title_native ~ '[\\uac00-\\ud7af\\u1100-\\u11ff\\u3130-\\u318f]' "
                "OR tags @> '[{\"name\": \"Manhwa\"}]' "
                "OR tags @> '[{\"name\": \"Webtoon\"}]' "
                "OR tags @> '[{\"name\": \"Korean\"}]' "
                "OR genres @> ARRAY['Manhwa'] "
                "OR site_url ILIKE '%manhwa%' "
                "OR (inferred_tags IS NOT NULL AND inferred_tags @> '[{\"slug\": \"manhwa\"}]')"
                ") "
                "AND NOT ("
                "tags @> '[{\"name\": \"Manhua\"}]' "
                "OR tags @> '[{\"name\": \"Chinese\"}]' "
                "OR tags @> '[{\"name\": \"Ancient China\"}]' "
                "OR genres @> ARRAY['Manhua'] "
                "OR site_url ILIKE '%manhua%'"
                ")"
                ")"
            )
        elif ft == 'manhua':
            fmt_conditions.append(
                "("
                "("
                "tags @> '[{\"name\": \"Manhua\"}]' "
                "OR tags @> '[{\"name\": \"Chinese\"}]' "
                "OR tags @> '[{\"name\": \"Ancient China\"}]' "
                "OR genres @> ARRAY['Manhua'] "
                "OR site_url ILIKE '%manhua%' "
                "OR (inferred_tags IS NOT NULL AND inferred_tags @> '[{\"slug\": \"manhua\"}]') "
                "OR (title_native ~ '[\\u4e00-\\u9fff]' AND NOT (title_native ~ '[\\u3040-\\u309f\\u30a0-\\u30ff]' OR title_native ~ '[\\uac00-\\ud7af\\u1100-\\u11ff\\u3130-\\u318f]') AND (tags @> '[{\"name\": \"Long Strip\"}]' OR tags @> '[{\"name\": \"Full Color\"}]'))"
                ") "
                "AND NOT ("
                "title_native ~ '[\\uac00-\\ud7af\\u1100-\\u11ff\\u3130-\\u318f]' "
                "OR tags @> '[{\"name\": \"Manhwa\"}]' "
                "OR tags @> '[{\"name\": \"Korean\"}]' "
                "OR genres @> ARRAY['Manhwa'] "
                "OR site_url ILIKE '%manhwa%'"
                ")"
                ")"
            )
        elif ft == 'manga':
            fmt_conditions.append(
                "NOT ("
                "title_native ~ '[\\uac00-\\ud7af\\u1100-\\u11ff\\u3130-\\u318f]' "
                "OR tags @> '[{\"name\": \"Manhwa\"}]' "
                "OR tags @> '[{\"name\": \"Webtoon\"}]' "
                "OR tags @> '[{\"name\": \"Korean\"}]' "
                "OR genres @> ARRAY['Manhwa'] "
                "OR site_url ILIKE '%manhwa%' "
                "OR (inferred_tags IS NOT NULL AND inferred_tags @> '[{\"slug\": \"manhwa\"}]') "
                "OR tags @> '[{\"name\": \"Manhua\"}]' "
                "OR tags @> '[{\"name\": \"Chinese\"}]' "
                "OR tags @> '[{\"name\": \"Ancient China\"}]' "
                "OR genres @> ARRAY['Manhua'] "
                "OR site_url ILIKE '%manhua%' "
                "OR (inferred_tags IS NOT NULL AND inferred_tags @> '[{\"slug\": \"manhua\"}]') "
                "OR (title_native ~ '[\\u4e00-\\u9fff]' AND NOT (title_native ~ '[\\u3040-\\u309f\\u30a0-\\u30ff]') AND (tags @> '[{\"name\": \"Long Strip\"}]' OR tags @> '[{\"name\": \"Full Color\"}]'))"
                ")"
            )
    if not fmt_conditions:
        return None
    return f"({' OR '.join(fmt_conditions)})"

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
        cond = build_genre_sql_condition(filters.genres, exclude=False)
        if cond:
            where_clauses.append(cond)

    if filters.exclude_genres:
        cond = build_genre_sql_condition(filters.exclude_genres, exclude=True)
        if cond:
            where_clauses.append(cond)

    if filters.format_type:
        raw_fmts = filters.format_type if isinstance(filters.format_type, list) else [filters.format_type]
        fmt_cond = build_format_sql_condition(raw_fmts)
        if fmt_cond:
            where_clauses.append(fmt_cond)


def infer_format_type(
    title_native: Optional[str] = None,
    tags: Any = None,
    genres: Optional[List[str]] = None,
    site_url: Optional[str] = None,
    inferred_tags: Any = None
) -> str:
    """Infers whether a title is MANHWA, MANHUA, or MANGA from metadata."""
    if inferred_tags and isinstance(inferred_tags, list):
        inferred_slugs = {t.get("slug") for t in inferred_tags if isinstance(t, dict)}
        if "manhwa" in inferred_slugs:
            return "MANHWA"
        if "manhua" in inferred_slugs:
            return "MANHUA"
        if "manga" in inferred_slugs:
            return "MANGA"

    tags_str = str(tags) if tags else ""
    genres_list = genres or []
    site_str = (site_url or "").lower()
    has_kana = bool(title_native and KANA_RE.search(title_native))
    has_hangul = bool(title_native and HANGUL_RE.search(title_native))
    has_hanzi = bool(title_native and HANZI_RE.search(title_native))

    # Korean Manhwa check (Explicit Korean markers)
    if (
        has_hangul or
        "Manhwa" in genres_list or
        "Manhwa" in tags_str or
        "Webtoon" in tags_str or
        "Korean" in tags_str or
        "manhwa" in site_str
    ):
        return "MANHWA"

    # Chinese Manhua check (Explicit Chinese markers or Hanzi-only webtoons)
    if (
        "Manhua" in genres_list or
        "Manhua" in tags_str or
        "Chinese" in tags_str or
        "Ancient China" in tags_str or
        "manhua" in site_str or
        (has_hanzi and not has_kana and not has_hangul and ("Long Strip" in tags_str or "Full Color" in tags_str))
    ):
        return "MANHUA"

    return "MANGA"

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
        WHERE (LOWER(title_english) = :q OR LOWER(title_romaji) = :q)
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
    await session.execute(text("SET pg_trgm.word_similarity_threshold = 0.40;"))
    await session.execute(text("SET pg_trgm.similarity_threshold = 0.30;"))
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
        LIMIT 1;
    """), {'q': clean_q})
    row = res.fetchone()
    if row:
        mid, t_en, t_ro, emb, pop, sim, w_sim, score = row
        if score >= 0.48 or sim >= 0.40 or w_sim >= 0.65:
            try:
                return mid, t_en or t_ro, emb, float(score)
            except Exception:
                pass

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
    tag_boost: Optional[float] = None
):
    if isinstance(query_embedding, str):
        emb_str = query_embedding
    else:
        emb_list = list(query_embedding) if hasattr(query_embedding, '__iter__') else query_embedding
        emb_str = "[" + ",".join(map(str, emb_list)) + "]"
    
    where_clauses = ["embedding IS NOT NULL"]
    params: Dict[str, Any] = {"emb": emb_str, "limit": limit, "offset": offset}
    
    if isinstance(filters, dict):
        filters = RecommendFilters(**filters)

    allow_nsfw = filters.nsfw if filters and filters.nsfw is not None else False
    if not allow_nsfw:
        where_clauses.append("(genres IS NULL OR NOT (genres && ARRAY['Hentai', 'Erotica']))")
    
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
              WHEN LOWER(COALESCE(title_english, '')) LIKE :contain_q OR LOWER(COALESCE(title_romaji, '')) LIKE :contain_q THEN 0.3
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

    sql = text(f"""
        WITH ranked AS (
          SELECT 
            id, 
            anilist_id,
            mal_id,
            mangadex_id,
            title_romaji, 
            title_english, 
            title_native,
            synopsis, 
            genres, 
            tags, 
            inferred_tags,
            status,
            start_year, 
            chapters,
            volumes,
            average_score, 
            popularity, 
            cover_image_url, 
            banner_image,
            site_url,
            (1 - (embedding <=> CAST(:emb AS vector))) as sim,
            {title_boost_select}
            {tag_select_sql}
            ROW_NUMBER() OVER (
              PARTITION BY LOWER(COALESCE(title_english, title_romaji, id::text)) 
              ORDER BY (1 - (embedding <=> CAST(:emb AS vector))) DESC, popularity DESC NULLS LAST
            ) as rn
          FROM manga
          WHERE {where_str}
        ),
        scored AS (
          SELECT *,
            {score_calc}
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
        m.format_type = infer_format_type(r.title_native, r.tags, r.genres, r.site_url, r.inferred_tags)

        score_val = float(r.hybrid_score)
        # Boost perceived match percentage for exact/prefix title matches
        if hasattr(r, 'title_boost'):
            if r.title_boost >= 1.0:
                score_val = max(score_val, 0.96)
            elif r.title_boost >= 0.6:
                score_val = max(score_val, 0.88)

        cand_dict = {
            "manga": m,
            "similarity_score": score_val,
            "format_type": m.format_type
        }
        if hasattr(r, 'tag_alignment'):
            cand_dict["tag_alignment"] = round(float(r.tag_alignment), 4)

        candidates.append(cand_dict)

    return candidates

# =========================================================
# PRODUCTION DIVERSITY & NON-ORDER-BY-RANDOM SAMPLING
# =========================================================

def apply_diversity_filtering(rows: List[Any], exclude_ids: Set[int], max_target: int = 50) -> List[Dict[str, Any]]:
    """Applies lightweight rule-based diversity (genres, format, score bands, hidden gems)"""
    if not rows:
        return []

    # 1. Deduplicate seen IDs & Franchise series titles
    seen_titles: Set[str] = set()
    filtered_rows = []

    for r in rows:
        if r.id in exclude_ids:
            continue
        stem = (r.title_english or r.title_romaji or str(r.id)).lower().strip()[:15]
        if stem in seen_titles:
            continue
        seen_titles.add(stem)
        filtered_rows.append(r)

    if not filtered_rows:
        filtered_rows = rows  # Fallback to full set if over-filtered

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
        sim_score = round((r.average_score or 85) / 100.0, 2)
        fmt = infer_format_type(r.title_native, r.tags, r.genres, r.site_url)
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
            "similarity_score": sim_score,
            "llm_reasoning": "Discovery Roulette candidate.",
            "format_type": fmt
        })

    return out


async def sample_candidates_from_db(
    session: AsyncSession,
    filters: Optional[RecommendFilters] = None,
    sample_limit: int = 150
) -> List[Any]:
    """Efficient SQL sampling using MOD hash & pseudo-random offsets without ORDER BY RANDOM()"""
    where_clauses = ["cover_image_url IS NOT NULL"]

    allow_nsfw = filters.nsfw if filters and filters.nsfw is not None else False
    if not allow_nsfw:
        where_clauses.append("(genres IS NULL OR NOT (genres && ARRAY['Hentai', 'Erotica']))")

    rand_offset = random.randint(0, 40)
    rand_seed = f"seed_{random.randint(1, 999999999)}_{time.time()}"
    params: Dict[str, Any] = {
        "limit": sample_limit, 
        "offset": rand_offset,
        "seed": rand_seed
    }

    apply_filter_criteria(filters, where_clauses, params)

    where_str = " AND ".join(where_clauses)

    # Safe, uniform pseudo-random distribution via core PostgreSQL hashtext (0 overflow risk)
    sql = text(f"""
        SELECT 
          id, anilist_id, mal_id, mangadex_id, title_romaji, title_english, title_native,
          synopsis, genres, tags, status, start_year, chapters, volumes,
          average_score, popularity, cover_image_url, banner_image, site_url
        FROM manga
        WHERE {where_str}
        ORDER BY hashtext(id::text || :seed) DESC
        LIMIT :limit OFFSET :offset;
    """)

    result = await session.execute(sql, params)
    return list(result.all())


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

    # 4. Attempt popping from Redis candidate pool
    results = []
    if pool_size > 0:
        popped_items = await cache.pop_roulette_pool(filter_hash, count=max(pool_limit, 4))
        # Exclude seen items
        unseen_items = [item for item in popped_items if item["id"] not in combined_seen]
        if unseen_items:
            random.shuffle(unseen_items)
            results = unseen_items[:pool_limit]

    # 5. Fallback: If Redis empty or popped items were seen, query DB cleanly with dynamic seeds
    if not results:
        db_rows = await sample_candidates_from_db(session, filters=filters, sample_limit=80)
        results = apply_diversity_filtering(db_rows, exclude_ids=combined_seen, max_target=pool_limit)
        if not results and db_rows:
            # Absolute fallback if all candidates were seen
            results = apply_diversity_filtering(db_rows, exclude_ids=set(), max_target=pool_limit)
        if results:
            random.shuffle(results)

    # 6. Update server-authoritative seen set in Redis
    if results and session_id:
        served_ids = [r["id"] for r in results]
        await cache.add_session_seen(session_id, served_ids)

    return results
