from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import recommend, manga, search, admin
from .middleware.rate_limit import RateLimitMiddleware

app = FastAPI(title="Mitsu API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware, requests_per_minute=60, window_seconds=60)


app.include_router(recommend.router, tags=["recommend"])
app.include_router(manga.router, tags=["manga"])
app.include_router(search.router, tags=["search"])
app.include_router(admin.router, tags=["admin"])

@app.get("/health")
async def health():
    return {"status": "ok"}
