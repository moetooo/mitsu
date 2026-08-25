import os
from app.config import settings
from sentence_transformers import SentenceTransformer
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Pass HuggingFace authentication token if set in environment
token = settings.HF_TOKEN or os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
model_kwargs = {"token": token} if token else {}

try:
    model = SentenceTransformer("all-MiniLM-L6-v2", **model_kwargs)
except Exception:
    # Fallback to standard initialization if kwarg is unsupported
    model = SentenceTransformer("all-MiniLM-L6-v2")

executor = ThreadPoolExecutor(max_workers=8)

def generate_embedding_sync(text: str):
    return model.encode(text).tolist()

async def generate_embedding(text: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, generate_embedding_sync, text)
