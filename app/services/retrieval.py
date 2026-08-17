import random
import hashlib
import json
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any, Set
from ..db_models import Manga
from ..models import RecommendFilters
from ..services import cache

ROULETTE_POOL_TARGET = 50
ROULETTE_REFILL_THRESHOLD = 15

def generate_filter_hash(filters: Optional[RecommendFilters]) -> str:
    """Generates a stable MD5 fingerprint hash for a filter set"""
    if not filters:
        return "default"
    filter_dict = filters.dict(exclude_none=True)
    filter_str = json.dumps(filter_dict, sort_keys=True)
    return hashlib.md5(filter_str.encode()).hexdigest()[:12]

async def retrieve_similar_manga(
    session: AsyncSession,
    query_embedding: List[float],
    filters: Optional[RecommendFilters] = None,
    limit: int = 20,
    offset: int = 0
):
    emb_list = list(query_embedding) if hasattr(query_embedding, '__iter__') else query_embedding
    emb_str = "[" + ",".join(map(str, emb_list)) + "]"
    
    where_clauses = ["embedding IS NOT NULL"]
    params: Dict[str, Any] = {"emb": emb_str, "limit": limit, "offset": offset}
    
    allow_nsfw = filters.nsfw if filters and filters.nsfw is not None else False
    if not allow_nsfw:
        where_clauses.append("(genres IS NULL OR NOT (genres && ARRAY['Hentai', 'Erotica']))")
    
    if filters:
        if filters.status:
            st_list = ", ".join(f"'{s}'" for s in filters.status)
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
            genres_arr = "ARRAY[" + ",".join(f"'{g}'" for g in filters.genres) + "]"
            where_clauses.append(f"genres && {genres_arr}")
        if filters.exclude_genres:
            ex_genres_arr = "ARRAY[" + ",".join(f"'{g}'" for g in filters.exclude_genres) + "]"
            where_clauses.append(f"NOT (genres && {ex_genres_arr})")
        if filters.format_type:
            raw_fmts = filters.format_type if isinstance(filters.format_type, list) else [filters.format_type]
            fmt_conditions = []
            for f in raw_fmts:
                ft = f.lower()
                if ft == 'manhwa':
                    fmt_conditions.append("(tags::text ILIKE '%Long Strip%' OR tags::text ILIKE '%Manhwa%' OR tags::text ILIKE '%Korean%' OR genres @> ARRAY['Manhwa'] OR site_url ILIKE '%manhwa%')")
                elif ft == 'manhua':
                    fmt_conditions.append("(tags::text ILIKE '%Manhua%' OR tags::text ILIKE '%Chinese%' OR tags::text ILIKE '%Ancient China%' OR genres @> ARRAY['Manhua'] OR site_url ILIKE '%manhua%')")
                elif ft == 'manga':
                    fmt_conditions.append("NOT (tags::text ILIKE '%Long Strip%' OR tags::text ILIKE '%Manhwa%' OR tags::text ILIKE '%Manhua%' OR tags::text ILIKE '%Chinese%' OR site_url ILIKE '%manhwa%' OR site_url ILIKE '%manhua%')")
            if fmt_conditions:
                where_clauses.append(f"({' OR '.join(fmt_conditions)})")

    where_str = " AND ".join(where_clauses)

    min_pct_filter = ""
    if filters and filters.min_match_pct and filters.min_match_pct > 0:
        params["min_pct"] = float(filters.min_match_pct)
        min_pct_filter = "WHERE hybrid_score >= :min_pct"

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
            ROW_NUMBER() OVER (
              PARTITION BY LOWER(COALESCE(title_english, title_romaji, id::text)) 
              ORDER BY (1 - (embedding <=> CAST(:emb AS vector))) DESC, popularity DESC NULLS LAST
            ) as rn
          FROM manga
          WHERE {where_str}
        ),
        scored AS (
          SELECT *,
            (
              0.70 * sim +
              0.18 * (COALESCE(average_score, 50) / 100.0) +
              0.12 * (LOG(GREATEST(COALESCE(popularity, 1), 1)) / 6.0)
            ) as hybrid_score
          FROM ranked
          WHERE rn = 1
        )
        SELECT *
        FROM scored
        {min_pct_filter}
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

        candidates.append({
            "manga": m,
            "similarity_score": float(r.hybrid_score)
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
            "llm_reasoning": "Discovery Roulette candidate."
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
            st_list = ", ".join(f"'{s}'" for s in filters.status)
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
            genres_arr = "ARRAY[" + ",".join(f"'{g}'" for g in filters.genres) + "]"
            where_clauses.append(f"genres && {genres_arr}")
        if filters.exclude_genres:
            ex_genres_arr = "ARRAY[" + ",".join(f"'{g}'" for g in filters.exclude_genres) + "]"
            where_clauses.append(f"NOT (genres && {ex_genres_arr})")
        if filters.format_type:
            raw_fmts = filters.format_type if isinstance(filters.format_type, list) else [filters.format_type]
            fmt_conditions = []
            for f in raw_fmts:
                ft = f.lower()
                if ft == 'manhwa':
                    fmt_conditions.append("(tags::text ILIKE '%Long Strip%' OR tags::text ILIKE '%Manhwa%' OR tags::text ILIKE '%Korean%' OR genres @> ARRAY['Manhwa'] OR site_url ILIKE '%manhwa%')")
                elif ft == 'manhua':
                    fmt_conditions.append("(tags::text ILIKE '%Manhua%' OR tags::text ILIKE '%Chinese%' OR tags::text ILIKE '%Ancient China%' OR genres @> ARRAY['Manhua'] OR site_url ILIKE '%manhua%')")
                elif ft == 'manga':
                    fmt_conditions.append("NOT (tags::text ILIKE '%Long Strip%' OR tags::text ILIKE '%Manhwa%' OR tags::text ILIKE '%Manhua%' OR tags::text ILIKE '%Chinese%' OR site_url ILIKE '%manhwa%' OR site_url ILIKE '%manhua%')")
            if fmt_conditions:
                where_clauses.append(f"({' OR '.join(fmt_conditions)})")

    where_str = " AND ".join(where_clauses)
    rand_offset = random.randint(0, 40)

    # NO ORDER BY RANDOM()! Uses fast pseudo-random knuth hash modulo order & offset
    sql = text(f"""
        SELECT 
          id, anilist_id, mal_id, mangadex_id, title_romaji, title_english, title_native,
          synopsis, genres, tags, status, start_year, chapters, volumes,
          average_score, popularity, cover_image_url, banner_image, site_url
        FROM manga
        WHERE {where_str}
        ORDER BY MOD(id * 2654435761, 4294967296) DESC
        LIMIT :limit OFFSET :offset;
    """)

    result = await session.execute(sql, {"limit": sample_limit, "offset": rand_offset})
    return result.all()


async def refill_roulette_pool(session: AsyncSession, filters: Optional[RecommendFilters], session_id: Optional[str] = None):
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

        db_rows = await sample_candidates_from_db(session, filters=filters, sample_limit=150)
        diverse_items = apply_diversity_filtering(db_rows, exclude_ids=seen_set, max_target=ROULETTE_POOL_TARGET)

        if diverse_items:
            await cache.push_roulette_pool(filter_hash, diverse_items, ttl=3600)
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

    # 3. Asynchronously trigger background pool refill if below threshold
    if pool_size < ROULETTE_REFILL_THRESHOLD:
        asyncio.create_task(refill_roulette_pool(session, filters, session_id))

    # 4. Attempt popping from Redis candidate pool
    results = []
    if pool_size > 0:
        popped_items = await cache.pop_roulette_pool(filter_hash, count=pool_limit)
        # Exclude seen items
        for item in popped_items:
            if item["id"] not in combined_seen:
                results.append(item)

    # 5. Fallback: If Redis empty or popped items were seen, query DB cleanly without ORDER BY RANDOM()
    if not results:
        db_rows = await sample_candidates_from_db(session, filters=filters, sample_limit=60)
        results = apply_diversity_filtering(db_rows, exclude_ids=combined_seen, max_target=pool_limit)
        if not results and db_rows:
            # Absolute fallback if all candidates were seen
            results = apply_diversity_filtering(db_rows, exclude_ids=set(), max_target=pool_limit)

    # 6. Update server-authoritative seen set in Redis
    if results and session_id:
        served_ids = [r["id"] for r in results]
        await cache.add_session_seen(session_id, served_ids)

    return results
