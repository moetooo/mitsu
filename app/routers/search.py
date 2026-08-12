from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import List
from ..db import get_db
from ..db_models import Manga
from ..models import MangaDetail

router = APIRouter()

@router.get("/search", response_model=List[MangaDetail])
async def search_manga(q: str, db: AsyncSession = Depends(get_db)):
    if not q:
        return []
        
    search_term = f"%{q}%"
    stmt = select(Manga).where(
        or_(
            Manga.title_english.ilike(search_term),
            Manga.title_romaji.ilike(search_term)
        )
    ).limit(10)
    
    result = await db.execute(stmt)
    return result.scalars().all()
