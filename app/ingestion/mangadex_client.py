import httpx
from typing import Dict, Any
from .rate_limiter import fetch_with_retry, mangadex_bucket

MANGADEX_API_URL = "https://api.mangadex.org"

async def fetch_list_page(offset: int = 0, limit: int = 100, year: int = None) -> Dict[str, Any]:
    url = f"{MANGADEX_API_URL}/manga"
    params = {
        "limit": limit,
        "offset": offset,
        "order[followedCount]": "desc",
        "includes[]": ["cover_art"]
    }
    if year:
        params["year"] = year
    
    async with httpx.AsyncClient() as client:
        def raw_get():
            return client.get(url, params=params, timeout=15.0)
        
        return await fetch_with_retry(mangadex_bucket, raw_get)

async def fetch_detail(mangadex_id: str) -> Dict[str, Any]:
    url = f"{MANGADEX_API_URL}/manga/{mangadex_id}"
    params = {"includes[]": ["cover_art", "author", "artist"]}
    
    async with httpx.AsyncClient() as client:
        def raw_get():
            return client.get(url, params=params, timeout=15.0)
        
        data = await fetch_with_retry(mangadex_bucket, raw_get)
        return data.get("data", {})
