from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from brotli_asgi import BrotliMiddleware
from .routers import recommend, manga, search, admin
from .middleware.rate_limit import RateLimitMiddleware
from .services.embedding import generate_embedding
from .services.cache import redis_client
from .db import engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Pre-warm the embedding model to eliminate first-query cold starts
    try:
        await generate_embedding("warmup")
    except Exception as e:
        pass

    yield

    # Shutdown: Gracefully close database engine and Redis connection pools
    try:
        await engine.dispose()
    except Exception:
        pass
    try:
        await redis_client.aclose()
    except Exception:
        pass

app = FastAPI(title="Mitsu API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware, requests_per_minute=60, window_seconds=60)

# Feature 105: Brotli compression for API response payloads (~15-20% smaller than GZip)
# Falls back to GZip for clients that don't support Brotli
app.add_middleware(BrotliMiddleware, minimum_size=500, gzip_fallback=True)


app.include_router(recommend.router, tags=["recommend"])
app.include_router(manga.router, tags=["manga"])
app.include_router(search.router, tags=["search"])
app.include_router(admin.router, tags=["admin"])

@app.get("/health")
async def health():
    return {"status": "ok"}
