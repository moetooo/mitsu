import time
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import RecommendRequest, RecommendResponse, RecommendationResult, RouletteRequest
from ..db_models import Manga
from ..db import get_db
from ..services.embedding import generate_embedding
from ..services.retrieval import retrieve_similar_manga, retrieve_roulette_manga, find_matched_title
from ..services.llm import generate_reasoning
from ..services.cache import get_cached, set_cached, generate_cache_key
from ..services.search_autocorrect import autocorrect_query
from ..utils.sanitizer import sanitize_search_query, sanitize_recommend_filters

router = APIRouter()

@router.post("/roulette", response_model=RecommendationResult)
async def roulette(request: RouletteRequest, db: AsyncSession = Depends(get_db)):
    request.filters = sanitize_recommend_filters(request.filters)
    results = await retrieve_roulette_manga(
        db, 
        filters=request.filters, 
        seen_ids=request.seen_ids, 
        pool_limit=1,
        session_id=request.session_id
    )
    if not results:
        results = await retrieve_roulette_manga(db, filters=None, seen_ids=None, pool_limit=1)
    
    item = results[0] if results else {}
    return RecommendationResult(
        id=item.get("id", 0),
        anilist_id=item.get("anilist_id"),
        mal_id=item.get("mal_id"),
        title=item.get("title", "Unknown Title"),
        cover_image_url=item.get("cover_image_url"),
        banner_image=item.get("banner_image"),
        synopsis=item.get("synopsis"),
        genres=item.get("genres"),
        tags=item.get("tags"),
        status=item.get("status"),
        start_year=item.get("start_year"),
        chapters=item.get("chapters"),
        volumes=item.get("volumes"),
        average_score=item.get("average_score"),
        similarity_score=item.get("similarity_score", 0.88),
        llm_reasoning="Discovery Roulette candidate.",
        format_type=item.get("format_type")
    )

@router.post("/roulette/batch", response_model=List[RecommendationResult])
async def roulette_batch(request: RouletteRequest, db: AsyncSession = Depends(get_db)):
    request.filters = sanitize_recommend_filters(request.filters)
    count = request.count if request.count > 0 else 5
    results = await retrieve_roulette_manga(
        db, 
        filters=request.filters, 
        seen_ids=request.seen_ids, 
        pool_limit=count,
        session_id=request.session_id
    )
    out = []
    for item in results:
        out.append(RecommendationResult(
            id=item.get("id", 0),
            anilist_id=item.get("anilist_id"),
            mal_id=item.get("mal_id"),
            title=item.get("title", "Unknown Title"),
            cover_image_url=item.get("cover_image_url"),
            banner_image=item.get("banner_image"),
            synopsis=item.get("synopsis"),
            genres=item.get("genres"),
            tags=item.get("tags"),
            status=item.get("status"),
            start_year=item.get("start_year"),
            chapters=item.get("chapters"),
            volumes=item.get("volumes"),
            average_score=item.get("average_score"),
            similarity_score=item.get("similarity_score", 0.88),
            llm_reasoning="Discovery Roulette candidate.",
            format_type=item.get("format_type")
        ))
    return out

@router.post("/recommend", response_model=RecommendResponse)
async def recommend(request: RecommendRequest, db: AsyncSession = Depends(get_db)):
    start_time = time.time()
    
    # Sanitize query and filter payload
    request.query = sanitize_search_query(request.query)
    request.filters = sanitize_recommend_filters(request.filters)
    request.query = await autocorrect_query(request.query, db)
    
    # 1. Check Cache
    cache_key = generate_cache_key("recommend", request.model_dump())
    cached_response = await get_cached(cache_key)
    if cached_response:
        return cached_response
        
    # 2. Title matching with typo tolerance or semantic retrieval
    matched_title = await find_matched_title(db, request.query) if request.query else None
    
    if matched_title:
        mid, matched_name, target_emb, _ = matched_title
        corrected_query = matched_name
        query_embedding_ms = 0.0
        
        t0 = time.time()
        top_candidates = []
        if request.page == 1:
            res = await db.execute(select(Manga).where(Manga.id == mid))
            target_manga = res.scalar_one_or_none()
            if target_manga:
                top_candidates.append({
                    "manga": target_manga,
                    "similarity_score": 0.96,
                    "hybrid_score": 0.96,
                    "format_type": getattr(target_manga, "format_type", None)
                })
        
        needed_limit = request.limit - len(top_candidates) if request.page == 1 else request.limit
        target_offset = 0 if request.page == 1 else ((request.page - 1) * request.limit - 1)
        
        if needed_limit > 0:
            similar_candidates = await retrieve_similar_manga(
                session=db,
                query_embedding=target_emb,
                filters=request.filters,
                limit=needed_limit + 5,
                offset=target_offset
            )
            for c in similar_candidates:
                if c["manga"].id != mid:
                    top_candidates.append(c)
                if len(top_candidates) >= request.limit:
                    break
        retrieval_ms = (time.time() - t0) * 1000
    else:
        # Standard semantic / thematic search
        t0 = time.time()
        query_embedding = await generate_embedding(request.query)
        query_embedding_ms = (time.time() - t0) * 1000
        
        offset = (request.page - 1) * request.limit
        t0 = time.time()
        top_candidates = await retrieve_similar_manga(
            session=db,
            query_embedding=query_embedding,
            filters=request.filters,
            limit=request.limit,
            offset=offset,
            query_text=request.query
        )
        retrieval_ms = (time.time() - t0) * 1000
        corrected_query = request.query

    # If no matching candidates (e.g. gibberish or zero-relevance query), skip LLM and return empty
    if not top_candidates:
        response = RecommendResponse(
            results=[],
            corrected_query=corrected_query,
            query_embedding_ms=query_embedding_ms,
            retrieval_ms=retrieval_ms,
            llm_ms=0.0,
            total_duration_ms=(time.time() - start_time) * 1000,
            has_more=False
        )
        await set_cached(cache_key, response.model_dump(), ttl=1800)
        return response

    # 3. LLM Reasoning
    t0 = time.time()
    reasoning_map = await generate_reasoning(corrected_query, top_candidates)
    llm_ms = (time.time() - t0) * 1000
    
    # 4. Format Response
    results = []
    for c in top_candidates:
        m = c["manga"]
        results.append(RecommendationResult(
            id=m.id,
            anilist_id=m.anilist_id,
            title=m.title_english or m.title_romaji or m.title_native or "Unknown Title",
            cover_image_url=m.cover_image_url,
            synopsis=m.synopsis,
            genres=m.genres,
            tags=m.tags,
            status=m.status,
            start_year=m.start_year,
            chapters=m.chapters,
            volumes=m.volumes,
            average_score=m.average_score,
            similarity_score=c["similarity_score"],
            llm_reasoning=reasoning_map.get(m.id),
            format_type=getattr(m, "format_type", None) or c.get("format_type")
        ))
        
    response = RecommendResponse(
        results=results,
        corrected_query=corrected_query,
        query_embedding_ms=query_embedding_ms,
        retrieval_ms=retrieval_ms,
        llm_ms=llm_ms
    )
    
    # 6. Cache and Return
    await set_cached(cache_key, response.model_dump())
    return response
