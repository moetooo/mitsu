from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import recommend, manga, search, admin

app = FastAPI(title="Mitsu API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recommend.router, tags=["recommend"])
app.include_router(manga.router, tags=["manga"])
app.include_router(search.router, tags=["search"])
app.include_router(admin.router, tags=["admin"])

@app.get("/health")
async def health():
    return {"status": "ok"}
