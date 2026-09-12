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
        # Get all mangas with embeddings using yield_per to stream results and prevent OOM
        stmt = select(Manga).where(Manga.embedding.isnot(None)).execution_options(yield_per=100)
        result = await session.stream(stmt)
        
        # We can't easily get the total count when streaming without a separate COUNT query, 
        # so we'll just track the progress index.
        print("Precomputing similarities in chunks (streaming)...")
        
        i = 0
        async for manga in result.scalars():
            i += 1
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
            
            if i % 100 == 0:
                await session.commit()
                print(f"Processed {i} mangas.")
                
        await session.commit()
        print("Done precomputing similarities.")

if __name__ == "__main__":
    asyncio.run(precompute_similarities())
