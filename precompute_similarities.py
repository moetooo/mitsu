import asyncio
import os
import sys

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.db_models import Manga
from app.services.retrieval import retrieve_similar_manga, similar_edges_are_fresh

from datetime import datetime, timezone

async def precompute_similarities():
    async with AsyncSessionLocal() as session:
        # Get all mangas with embeddings using yield_per to stream results and prevent OOM
        stmt = select(Manga).where(Manga.embedding.isnot(None)).execution_options(yield_per=100)
        result = await session.stream(stmt)
        
        # We can't easily get the total count when streaming without a separate COUNT query, 
        # so we'll just track the progress index.
        print("Precomputing similarities in chunks (streaming)...")
        
        i = 0
        computed = 0
        skipped = 0
        async for manga in result.scalars():
            i += 1
            # Recompute when the stored edges are missing or past
            # SIMILAR_EDGES_MAX_AGE_DAYS. This used to be `is not None`, so the
            # job was write-once: a re-embedded row kept neighbours computed
            # from its old vector forever and the reader had no way to tell.
            if similar_edges_are_fresh(manga):
                skipped += 1
                continue

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
            # Stamped so the reader can decide whether the edges are still
            # usable; without it every stored edge read as stale.
            manga.similarities_computed_at = datetime.now(timezone.utc)
            session.add(manga)
            computed += 1
            
            if i % 100 == 0:
                await session.commit()
                print(f"Processed {i} mangas ({computed} computed, {skipped} fresh).")
                
        await session.commit()
        print(f"Done precomputing similarities: {computed} computed, {skipped} already fresh.")

if __name__ == "__main__":
    asyncio.run(precompute_similarities())
