from pydantic import BaseModel, ConfigDict, Field
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
    # Bounded on purpose: `page=0` used to build a negative OFFSET and fail as a
    # 500 instead of a 422, and an unbounded limit let a caller ask the retriever
    # for the whole catalog.
    limit: int = Field(default=12, ge=1, le=50)
    page: int = Field(default=1, ge=1, le=100)

class RouletteRequest(BaseModel):
    query: Optional[str] = None
    filters: Optional[RecommendFilters] = None
    seen_ids: Optional[List[int]] = None
    session_id: Optional[str] = None
    count: int = Field(default=1, ge=1, le=20)
    limit: int = Field(default=40, ge=1, le=100)

class RecommendationResult(BaseModel):
    # Local database PK. None only for a live provider row (for example a
    # trending title the catalog has not ingested yet); callers must check for
    # it before using the id in a local-only endpoint such as /manga/{id}/similar.
    id: Optional[int] = None
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
    category_badge: Optional[str] = None
    format_type: Optional[str] = None
    alternative_titles: Optional[List[str]] = None
    inferred_tags: Optional[List[Dict[str, Any]]] = None
    is_nsfw: Optional[bool] = None

class TitleSuggestion(BaseModel):
    """A close title offered *beside* thematic results, never instead of them.

    Thematic searches used to be silently replaced by a fuzzy title hit, so
    "monster hunting" returned *Monster Hunter* and nothing else. This carries
    the same hit as an affordance the user can choose: the results answer the
    phrase they typed, and this answers "or did you mean this title?".
    """
    id: int
    title: str
    cover_image_url: Optional[str] = None
    format_type: Optional[str] = None
    start_year: Optional[int] = None
    # The trigram match_score behind the suggestion, so the client can rank or
    # suppress it rather than trusting every hit equally.
    match_score: Optional[float] = None

class RecommendResponse(BaseModel):
    results: List[RecommendationResult]
    corrected_query: Optional[str] = None
    query_embedding_ms: Optional[float] = None
    retrieval_ms: Optional[float] = None
    llm_ms: Optional[float] = None
    # Declared so the values the router already computes reach the client
    # instead of being silently dropped by response_model validation.
    total_duration_ms: Optional[float] = None
    has_more: bool = False
    # Present only when a confident close title exists for a query that was
    # answered thematically. An exact-title query returns results *about* the
    # title instead and does not need this.
    title_suggestion: Optional[TitleSuggestion] = None

class MangaDetail(BaseModel):
    id: int
    anilist_id: Optional[int] = None
    mal_id: Optional[int] = None
    title_romaji: Optional[str] = None
    title_english: Optional[str] = None
    title_native: Optional[str] = None
    synopsis: Optional[str] = None
    genres: Optional[List[str]] = None
    tags: Optional[List[Dict[str, Any]]] = None
    alternative_titles: Optional[List[str]] = None
    inferred_tags: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    start_year: Optional[int] = None
    chapters: Optional[int] = None
    volumes: Optional[int] = None
    average_score: Optional[int] = None
    popularity: Optional[int] = None
    cover_image_url: Optional[str] = None
    banner_image: Optional[str] = None
    site_url: Optional[str] = None
    is_nsfw: Optional[bool] = None

    # Pydantic v2: class-based `Config` is deprecated and warns on import (QA-20;
    # the blanket warning filter used to hide it).
    model_config = ConfigDict(from_attributes=True)

