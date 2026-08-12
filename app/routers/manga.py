from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from ..db import get_db
from ..db_models import Manga
from ..models import MangaDetail, RecommendationResult
from ..services.retrieval import retrieve_similar_manga
from ..services.cache import get_cached, set_cached

import random
from datetime import datetime

router = APIRouter()

@router.get("/manga/featured", response_model=List[RecommendationResult])
async def get_featured_manga(limit: int = 6, db: AsyncSession = Depends(get_db)):
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    cache_key = f"manga:featured:{date_str}:{limit}"
    
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    # Retrieve top 60 popular candidates with valid covers from DB
    stmt = select(Manga).where(Manga.cover_image_url.isnot(None)).order_by(Manga.popularity.desc().nullslast()).limit(60)
    result = await db.execute(stmt)
    mangas_pool = list(result.scalars().all())
    
    if not mangas_pool:
        return []
        
    # Seed by current UTC date so featured titles are random from DB,
    # but remain stable across page refreshes throughout the day!
    rng = random.Random(date_str)
    selected_mangas = rng.sample(mangas_pool, min(len(mangas_pool), limit))
    
    response = [
        RecommendationResult(
            id=m.id,
            anilist_id=m.anilist_id,
            mal_id=m.mal_id,
            title=m.title_english or m.title_romaji or m.title_native or "Unknown",
            cover_image_url=m.cover_image_url,
            banner_image=m.banner_image,
            synopsis=m.synopsis,
            genres=m.genres,
            tags=m.tags,
            status=m.status,
            start_year=m.start_year,
            chapters=m.chapters,
            volumes=m.volumes,
            average_score=m.average_score,
            similarity_score=0.95,
            llm_reasoning=None
        ) for m in selected_mangas
    ]
    
    await set_cached(cache_key, [r.model_dump() for r in response], ttl=86400)
    return response

@router.get("/manga/{manga_id}", response_model=MangaDetail)
async def get_manga(manga_id: int, db: AsyncSession = Depends(get_db)):
    cache_key = f"manga:detail:{manga_id}"
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    stmt = select(Manga).where(Manga.id == manga_id)
    result = await db.execute(stmt)
    manga = result.scalar_one_or_none()
    
    if not manga:
        raise HTTPException(status_code=404, detail="Manga not found")
        
    detail = MangaDetail.model_validate(manga)
    await set_cached(cache_key, detail.model_dump(), ttl=3600)
    return detail

@router.get("/manga/{manga_id}/similar", response_model=List[RecommendationResult])
async def get_similar_manga(manga_id: int, limit: int = 6, db: AsyncSession = Depends(get_db)):
    cache_key = f"manga:similar:{manga_id}:{limit}"
    cached_data = await get_cached(cache_key)
    if cached_data:
        return cached_data

    stmt = select(Manga).where(Manga.id == manga_id)
    result = await db.execute(stmt)
    manga = result.scalar_one_or_none()
    
    if not manga or manga.embedding is None:
        raise HTTPException(status_code=404, detail="Manga or embedding not found")
        
    candidates = await retrieve_similar_manga(
        session=db,
        query_embedding=manga.embedding,
        filters=None,
        limit=limit + 1
    )
    
    # Filter out the source manga itself and format as RecommendationResult
    results = []
    for c in candidates:
        m = c["manga"]
        if m.id == manga_id:
            continue
            
        results.append(RecommendationResult(
            id=m.id,
            anilist_id=m.anilist_id,
            title=m.title_english or m.title_romaji or m.title_native or "Unknown",
            cover_image_url=m.cover_image_url,
            synopsis=m.synopsis,
            genres=m.genres,
            similarity_score=c["similarity_score"],
            llm_reasoning=None  # No LLM for this fast endpoint
        ))
        
        if len(results) >= limit:
            break
            
    await set_cached(cache_key, [r.model_dump() for r in results], ttl=3600)
    return results
