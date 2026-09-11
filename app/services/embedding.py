import os
from app.config import settings
from fastembed import TextEmbedding
import asyncio
from concurrent.futures import ThreadPoolExecutor

try:
    model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
except Exception:
    # Fallback to default small model if needed
    model = TextEmbedding("BAAI/bge-small-en-v1.5")

executor = ThreadPoolExecutor(max_workers=8)

def generate_embedding_sync(text: str):
    embeddings = list(model.embed([text]))
    return embeddings[0].tolist()

async def generate_embedding(text: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, generate_embedding_sync, text)
