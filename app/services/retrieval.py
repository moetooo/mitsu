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

ROULETTE_POOL_TARGET = 50
ROULETTE_REFILL_THRESHOLD = 15

HANGUL_RE = re.compile(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]')
KANA_RE = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
HANZI_RE = re.compile(r'[\u4e00-\u9fff]')

def generate_filter_hash(filters: Optional[RecommendFilters]) -> str:
    """Generates a stable MD5 fingerprint hash for a filter set"""
    if not filters:
        return "default"
    filter_dict = filters.model_dump(exclude_none=True) if hasattr(filters, 'model_dump') else filters.dict(exclude_none=True)
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
                "OR site_url ILIKE '%manhwa%'"
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
                "OR tags @> '[{\"name\": \"Manhua\"}]' "
                "OR tags @> '[{\"name\": \"Chinese\"}]' "
                "OR tags @> '[{\"name\": \"Ancient China\"}]' "
                "OR genres @> ARRAY['Manhua'] "
                "OR site_url ILIKE '%manhua%' "
                "OR (title_native ~ '[\\u4e00-\\u9fff]' AND NOT (title_native ~ '[\\u3040-\\u309f\\u30a0-\\u30ff]') AND (tags @> '[{\"name\": \"Long Strip\"}]' OR tags @> '[{\"name\": \"Full Color\"}]'))"
                ")"
            )
    if not fmt_conditions:
        return None
    return f"({' OR '.join(fmt_conditions)})"

def infer_format_type(
    title_native: Optional[str] = None,
    tags: Any = None,
    genres: Optional[List[str]] = None,
    site_url: Optional[str] = None
) -> str:
    """Infers whether a title is MANHWA, MANHUA, or MANGA from metadata."""
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
    query: str
) -> Optional[Tuple[int, str, List[float], float]]:
    """
    Identifies if a search query targets a specific manga title (including typos/misspellings)
    using exact matching, prefix matching, and trigram/word similarity via pg_trgm GIN indexes.
    Returns (manga_id, matched_title, embedding_list, match_score) or None.
    """
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
    query_text: Optional[str] = None
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
    
    if filters:
        if filters.status:
            st_list = ", ".join(f"'{s.replace('\'', '\'\'')}'" for s in filters.status)
            where_clauses.append(f"status IN ({st_list})")
        if filters.min_year:
            where_clauses.append(f"start_year >= {int(filters.min_year)}")
        if filters.max_year:
            where_clauses.append(f"start_year <= {int(filters.max_year)}")
        if filters.min_score:
            where_clauses.append(f"average_score >= {int(filters.min_score)}")
        if filters.min_chapters:
            where_clauses.append(f"chapters >= {int(filters.min_chapters)}")
        if filters.max_chapters:
            where_clauses.append(f"chapters <= {int(filters.max_chapters)}")
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

    where_str = " AND ".join(where_clauses)

    has_query_text = bool(query_text and query_text.strip())
    if has_query_text:
        clean_q = query_text.strip().lower()
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
        score_calc = """
            (
              0.55 * sim +
              0.30 * title_boost +
              0.08 * (COALESCE(average_score, 50) / 100.0) +
              0.07 * (LOG(GREATEST(COALESCE(popularity, 1), 1)) / 6.0)
            ) as hybrid_score
        """
    else:
        title_boost_select = "0.0 as title_boost,"
        score_calc = """
            (
              0.70 * sim +
              0.18 * (COALESCE(average_score, 50) / 100.0) +
              0.12 * (LOG(GREATEST(COALESCE(popularity, 1), 1)) / 6.0)
            ) as hybrid_score
        """

    relevance_conditions = []
    if has_query_text:
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
        m.status = r.status
        m.start_year = r.start_year
        m.chapters = r.chapters
        m.volumes = r.volumes
        m.average_score = r.average_score
        m.popularity = r.popularity
        m.cover_image_url = r.cover_image_url
        m.banner_image = r.banner_image
        m.site_url = r.site_url
        m.format_type = infer_format_type(r.title_native, r.tags, r.genres, r.site_url)

        score_val = float(r.hybrid_score)
        # Boost perceived match percentage for exact/prefix title matches
        if hasattr(r, 'title_boost'):
            if r.title_boost >= 1.0:
                score_val = max(score_val, 0.96)
            elif r.title_boost >= 0.6:
                score_val = max(score_val, 0.88)

        candidates.append({
            "manga": m,
            "similarity_score": score_val,
            "format_type": m.format_type
        })

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

    if filters:
        if filters.status:
            st_list = ", ".join(f"'{s.replace('\'', '\'\'')}'" for s in filters.status)
            where_clauses.append(f"status IN ({st_list})")
        if filters.min_year:
            where_clauses.append(f"start_year >= {int(filters.min_year)}")
        if filters.max_year:
            where_clauses.append(f"start_year <= {int(filters.max_year)}")
        if filters.min_score:
            where_clauses.append(f"average_score >= {int(filters.min_score)}")
        if filters.min_chapters:
            where_clauses.append(f"chapters >= {int(filters.min_chapters)}")
        if filters.max_chapters:
            where_clauses.append(f"chapters <= {int(filters.max_chapters)}")
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

    where_str = " AND ".join(where_clauses)
    rand_offset = random.randint(0, 40)
    rand_seed = f"seed_{random.randint(1, 999999999)}_{time.time()}"

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

    result = await session.execute(sql, {
        "limit": sample_limit, 
        "offset": rand_offset,
        "seed": rand_seed
    })
    return result.all()


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
