import asyncio
import os
import sys

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.db_models import Manga
from app.services.retrieval import retrieve_similar_manga

async def precompute_similarities():
    async with AsyncSessionLocal() as session:
        # Get all mangas with embeddings
        stmt = select(Manga).where(Manga.embedding.isnot(None))
        result = await session.execute(stmt)
        mangas = result.scalars().all()
        
        total = len(mangas)
        print(f"Precomputing similarities for {total} mangas...")
        
        for i, manga in enumerate(mangas):
            if manga.similar_mangas is not None:
                continue # Skip if already computed
                
            candidates = await retrieve_similar_manga(
                session, 
                query_embedding=manga.embedding, 
                limit=51
            )
            
            # Extract top 50, excluding self
            similar_list = []
            for c in candidates:
                if c["manga"].id != manga.id:
                    similar_list.append({
                        "id": c["manga"].id,
                        "score": round(c["similarity_score"], 4)
                    })
            
            similar_list = similar_list[:50]
            
            # Update DB
            manga.similar_mangas = similar_list
            session.add(manga)
            
            if (i + 1) % 100 == 0:
                await session.commit()
                print(f"Processed {i + 1}/{total} mangas.")
                
        await session.commit()
        print("Done precomputing similarities.")

if __name__ == "__main__":
    asyncio.run(precompute_similarities())
