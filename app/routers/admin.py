from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from ..db import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/ingestion-status")
async def get_ingestion_status(db: AsyncSession = Depends(get_db)):
    query = text("""
        SELECT source,
               count(*) FILTER (WHERE enriched) AS done,
               count(*) FILTER (WHERE NOT enriched AND enrich_attempts < 5) AS pending,
               count(*) FILTER (WHERE NOT enriched AND enrich_attempts >= 5) AS stuck,
               count(*) AS total
        FROM discovery_queue
        GROUP BY source;
    """)
    
    result = await db.execute(query)
    rows = result.mappings().all()
    
    # Also fetch total manga count in database
    manga_count_res = await db.execute(text("SELECT count(*) FROM manga;"))
    total_manga = manga_count_res.scalar()
    
    anilist_count_res = await db.execute(text("SELECT count(*) FROM manga WHERE anilist_id IS NOT NULL;"))
    total_anilist = anilist_count_res.scalar()
    
    return {
        "total_manga_in_db": total_manga,
        "anilist_manga_count": total_anilist,
        "discovery_queue_status": [dict(r) for r in rows]
    }
