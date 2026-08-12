import httpx
from typing import Dict, Any
from .rate_limiter import fetch_with_retry, jikan_bucket

JIKAN_API_URL = "https://api.jikan.moe/v4"

async def fetch_list_page(page: int = 1, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
    url = f"{JIKAN_API_URL}/manga"
    params = {"page": page, "order_by": "popularity", "sort": "asc"}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    
    async with httpx.AsyncClient() as client:
        def raw_get():
            return client.get(url, params=params, timeout=15.0)
        
        return await fetch_with_retry(jikan_bucket, raw_get)

async def fetch_detail(mal_id: int) -> Dict[str, Any]:
    url = f"{JIKAN_API_URL}/manga/{mal_id}/full"
    
    async with httpx.AsyncClient() as client:
        def raw_get():
            return client.get(url, timeout=15.0)
        
        data = await fetch_with_retry(jikan_bucket, raw_get)
        return data.get("data", {})
