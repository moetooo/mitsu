from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from ..db_models import Manga
from ..models import RecommendFilters

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
    
    # NSFW Filtering
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
        # Create a proxy/dummy Manga object or dict matching expectations
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

