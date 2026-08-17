from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union

class RecommendFilters(BaseModel):
    status: Optional[List[str]] = None
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    min_score: Optional[int] = None
    min_chapters: Optional[int] = None
    max_chapters: Optional[int] = None
    min_match_pct: Optional[float] = None
    genres: Optional[List[str]] = None
    exclude_genres: Optional[List[str]] = None
    format_type: Optional[Union[str, List[str]]] = None
    nsfw: Optional[bool] = False


class RecommendRequest(BaseModel):
    query: str
    filters: Optional[RecommendFilters] = None
    limit: int = 12
    page: int = 1

class RouletteRequest(BaseModel):
    query: Optional[str] = None
    filters: Optional[RecommendFilters] = None
    seen_ids: Optional[List[int]] = None
    session_id: Optional[str] = None
    count: int = 1
    limit: int = 40

class RecommendationResult(BaseModel):
    id: int
    anilist_id: Optional[int] = None
    mal_id: Optional[int] = None
    title: str
    cover_image_url: Optional[str] = None
    banner_image: Optional[str] = None
    synopsis: Optional[str] = None
    genres: Optional[List[str]] = None
    tags: Optional[List[Any]] = None
    status: Optional[str] = None
    start_year: Optional[int] = None
    chapters: Optional[int] = None
    volumes: Optional[int] = None
    average_score: Optional[int] = None
    similarity_score: Optional[float] = None
    llm_reasoning: Optional[str] = None

class RecommendResponse(BaseModel):
    results: List[RecommendationResult]
    query_embedding_ms: Optional[float] = None
    retrieval_ms: Optional[float] = None
    llm_ms: Optional[float] = None

class MangaDetail(BaseModel):
    id: int
    anilist_id: int
    mal_id: Optional[int] = None
    title_romaji: Optional[str] = None
    title_english: Optional[str] = None
    title_native: Optional[str] = None
    synopsis: Optional[str] = None
    genres: Optional[List[str]] = None
    tags: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    start_year: Optional[int] = None
    chapters: Optional[int] = None
    volumes: Optional[int] = None
    average_score: Optional[int] = None
    popularity: Optional[int] = None
    cover_image_url: Optional[str] = None
    banner_image: Optional[str] = None
    site_url: Optional[str] = None

    class Config:
        from_attributes = True
