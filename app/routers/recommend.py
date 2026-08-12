import time
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import RecommendRequest, RecommendResponse, RecommendationResult
from ..db import get_db
from ..services.embedding import generate_embedding
from ..services.retrieval import retrieve_similar_manga
from ..services.llm import generate_reasoning
from ..services.cache import get_cached, set_cached, generate_cache_key

router = APIRouter()

@router.post("/recommend", response_model=RecommendResponse)
async def recommend(request: RecommendRequest, db: AsyncSession = Depends(get_db)):
    start_time = time.time()
    
    # 1. Check Cache
    cache_key = generate_cache_key("recommend", request.model_dump())
    cached_response = await get_cached(cache_key)
    if cached_response:
        return cached_response
        
    # 2. Embed Query
    t0 = time.time()
    query_embedding = await generate_embedding(request.query)
    query_embedding_ms = (time.time() - t0) * 1000
    
    # 3. Retrieve
    offset = (request.page - 1) * request.limit
    t0 = time.time()
    top_candidates = await retrieve_similar_manga(db, query_embedding, request.filters, limit=request.limit, offset=offset)
    retrieval_ms = (time.time() - t0) * 1000
    
    # 4. LLM Reasoning
    t0 = time.time()
    reasoning_map = await generate_reasoning(request.query, top_candidates)
    llm_ms = (time.time() - t0) * 1000
    
    # 5. Format Response
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
            llm_reasoning=reasoning_map.get(m.id)
        ))
        
    response = RecommendResponse(
        results=results,
        query_embedding_ms=query_embedding_ms,
        retrieval_ms=retrieval_ms,
        llm_ms=llm_ms
    )
    
    # 6. Cache and Return
    await set_cached(cache_key, response.model_dump())
    return response
