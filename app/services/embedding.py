from sentence_transformers import SentenceTransformer
import asyncio
from concurrent.futures import ThreadPoolExecutor

model = SentenceTransformer("all-MiniLM-L6-v2")
executor = ThreadPoolExecutor(max_workers=8)

def generate_embedding_sync(text: str):
    return model.encode(text).tolist()

async def generate_embedding(text: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, generate_embedding_sync, text)
