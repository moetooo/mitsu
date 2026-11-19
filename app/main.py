import asyncio
import time
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from brotli_asgi import BrotliMiddleware
from sqlalchemy import text
from .routers import recommend, manga, search, admin, vocabulary
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.request_log import RequestLogMiddleware
from .core import covers as _cover_cfg
from .services.cover_canary import canary_loop
from .services.embedding import generate_embedding, shutdown_embedding
from .services.cache import redis_client
from .db import engine, AsyncSessionLocal
from .core.logging import configure_logging
from .core.schema import verify_schema
from .config import settings

# One configuration for the API, the CLI and the maintenance scripts
# (`app/core/logging.py`), driven by LOG_LEVEL / LOG_FORMAT. It replaces the
# `basicConfig` that let every transport library log at INFO.
configure_logging()
logger = logging.getLogger("mitsu")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Name the models once at boot: the previous failure mode was a hardcoded id
    # that 404'd quietly, so the first place to look is here.
    logger.info(
        "LLM reasoning: model=%s timeout=%ss enabled=%s (enrichment model=%s)",
        settings.LLM_REASONING_MODEL,
        settings.LLM_REASONING_TIMEOUT_S,
        "yes" if settings.LLM_REASONING_ENABLED else "no",
        settings.LLM_MODEL,
    )
    # Startup: Pre-warm the embedding model to eliminate first-query cold starts
    try:
        await generate_embedding("warmup")
        logger.info("FastEmbed model pre-warmed successfully.")
    except Exception as e:
        logger.warning("FastEmbed model pre-warming warning: %s", e)

    # Read-only readiness check. Schema changes belong to Alembic (`alembic
    # upgrade head`); nothing here writes DDL at startup any more (ARCH-03).
    try:
        await verify_schema()
        logger.info("Schema is at the revision this build expects.")
    except Exception as e:
        logger.warning("Schema check: %s", e)

    # Cover policy is configuration now, so it is checked once, loudly, at startup.
    # A bad value degrades to the built-in default instead of taking the app down:
    # a typo in a hostname must not be able to serve a site with no covers.
    try:
        from .core.covers import validate_cover_config

        for problem in validate_cover_config():
            logger.error("Cover config: %s", problem)
        logger.info(
            "Cover policy: allowed=%s blocked=%s order=%s max=%d",
            ",".join(_cover_cfg.allowed_hosts()),
            ",".join(_cover_cfg.blocked_hosts()) or "(none)",
            ",".join(_cover_cfg.source_order()),
            _cover_cfg.max_candidates(),
        )
    except Exception as e:
        logger.warning("Cover config check skipped: %s", e)

    # Weekly MangaDex cover canary: one request a week, in this process, guarded by
    # a Redis lock so only one worker probes. No external scheduler is involved, and
    # nothing on the request path waits for it.
    canary_stop: asyncio.Event | None = None
    canary_task: asyncio.Task | None = None
    if settings.COVER_CANARY_ENABLED:
        canary_stop = asyncio.Event()
        canary_task = asyncio.create_task(canary_loop(canary_stop), name="cover-canary")
        logger.info("Cover canary started (MangaDex CDN probe, weekly).")

    yield

    if canary_task is not None and canary_stop is not None:
        canary_stop.set()
        canary_task.cancel()
        try:
            await canary_task
        except (asyncio.CancelledError, Exception):  # noqa: B014 - shutdown must not raise
            pass

    # Shutdown: Gracefully close database engine and Redis connection pools
    try:
        await engine.dispose()
        logger.info("Database connection engine disposed.")
    except Exception as e:
        logger.warning("Error disposing database engine: %s", e)
    try:
        await redis_client.aclose()
        logger.info("Redis connection pool closed.")
    except Exception as e:
        logger.warning("Error closing Redis client: %s", e)
    try:
        # SVC-07: release the fastembed weights and their worker threads.
        # The release itself is logged by `services.embedding`, which owns the
        # resource; logging it here too printed the same line twice.
        shutdown_embedding()
    except Exception as e:
        logger.warning("Error releasing embedding resources: %s", e)

app = FastAPI(title="Mitsu API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware, requests_per_minute=60, window_seconds=60)

# One INFO line per request plus the id stamped on every log record it emits.
app.add_middleware(RequestLogMiddleware)

# Feature 105: Brotli compression for API response payloads (~15-20% smaller than GZip)
# Falls back to GZip for clients that don't support Brotli
app.add_middleware(BrotliMiddleware, minimum_size=500, gzip_fallback=True)


app.include_router(recommend.router, tags=["recommend"])
app.include_router(manga.router, tags=["manga"])
app.include_router(search.router, tags=["search"])
app.include_router(admin.router, tags=["admin"])
app.include_router(vocabulary.router, tags=["vocabulary"])

# The dashboard is a separate Vite entry built into app/static/dashboard.
# Assets are relative to /admin/dashboard, so a proxy prefix such as /api works.
_DASHBOARD_ASSETS = Path(__file__).resolve().parent / "static" / "dashboard" / "assets"
if _DASHBOARD_ASSETS.is_dir():
    app.mount(
        "/admin/assets",
        StaticFiles(directory=str(_DASHBOARD_ASSETS)),
        name="dashboard-assets",
    )

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
