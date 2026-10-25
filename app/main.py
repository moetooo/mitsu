import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from brotli_asgi import BrotliMiddleware
from sqlalchemy import text
from .routers import recommend, manga, search, admin
from .middleware.rate_limit import RateLimitMiddleware
from .services.embedding import generate_embedding
from .services.cache import redis_client
from .db import engine, AsyncSessionLocal

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
async def health(response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    db_ok = False
    redis_ok = False
    details = {}
    
    # 1. Database Check (safe isolated session)
    t0 = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_latency = round((time.perf_counter() - t0) * 1000, 2)
        db_ok = True
        details["database"] = {"status": "connected", "latency_ms": db_latency}
    except Exception as e:
        details["database"] = {"status": "unhealthy", "error": str(e)}

    # 2. Redis Check
    t0 = time.perf_counter()
    try:
        await redis_client.ping()
        redis_latency = round((time.perf_counter() - t0) * 1000, 2)
        redis_ok = True
        details["redis"] = {"status": "connected", "latency_ms": redis_latency}
    except Exception as e:
        details["redis"] = {"status": "unhealthy", "error": str(e)}

    is_healthy = db_ok and redis_ok
    status = "healthy" if is_healthy else ("degraded" if (db_ok or redis_ok) else "unhealthy")
    
    response.status_code = 200 if is_healthy else 503
    return {
        "status": status,
        "services": details
    }
