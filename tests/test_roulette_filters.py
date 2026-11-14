import pytest
import re

# Every test here reads the shared catalog, so it needs a seeded database.
pytestmark = pytest.mark.requires_catalog

from app.db import AsyncSessionLocal
from app.models import RecommendFilters
from app.services.retrieval import retrieve_roulette_manga

HANGUL_RE = re.compile(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]')

# -------------------------------------------------------------
# 1. Format Filters (Manga vs Manhwa vs Manhua)
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_roulette_manga_only():
    """When format_type=['manga'], all returned candidates must be 100% Japanese Manga with zero Manhwa/Manhua."""
    async with AsyncSessionLocal() as db:
        filters = RecommendFilters(format_type=["manga"])
        results = await retrieve_roulette_manga(db, filters=filters, pool_limit=10)
        assert len(results) > 0, "Should return candidates for manga filter"

        for item in results:
            fmt = item.get("format_type")
            title = item.get("title")
            genres = [g.lower() for g in (item.get("genres") or [])]
            tags_str = str(item.get("tags") or "").lower()

            assert fmt == "MANGA", f"Item '{title}' expected format MANGA, got {fmt}"
            assert "manhwa" not in genres, f"'{title}' should not have manhwa genre"
            assert "manhua" not in genres, f"'{title}' should not have manhua genre"
            assert "webtoon" not in tags_str, f"'{title}' should not have webtoon tag"
            assert "korean" not in tags_str, f"'{title}' should not have korean tag"

@pytest.mark.asyncio
async def test_roulette_manhwa_only():
    """When format_type=['manhwa'], all returned candidates must be Korean Manhwa."""
    async with AsyncSessionLocal() as db:
        filters = RecommendFilters(format_type=["manhwa"])
        results = await retrieve_roulette_manga(db, filters=filters, pool_limit=10)
        assert len(results) > 0, "Should return candidates for manhwa filter"

        for item in results:
            fmt = item.get("format_type")
            title = item.get("title")
            assert fmt == "MANHWA", f"Item '{title}' expected format MANHWA, got {fmt}"

@pytest.mark.asyncio
async def test_roulette_manhua_only():
    """When format_type=['manhua'], all returned candidates must be Chinese Manhua."""
    async with AsyncSessionLocal() as db:
        filters = RecommendFilters(format_type=["manhua"])
        results = await retrieve_roulette_manga(db, filters=filters, pool_limit=8)
        assert len(results) > 0, "Should return candidates for manhua filter"

        for item in results:
            fmt = item.get("format_type")
            title = item.get("title")
            assert fmt == "MANHUA", f"Item '{title}' expected format MANHUA, got {fmt}"

# -------------------------------------------------------------
# 2. Genre Inclusion & Exclusion
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_roulette_genre_inclusion():
    """When genres=['Romance'], every candidate must contain Romance."""
    async with AsyncSessionLocal() as db:
        filters = RecommendFilters(genres=["Romance"])
        results = await retrieve_roulette_manga(db, filters=filters, pool_limit=10)
        assert len(results) > 0

        for item in results:
            genres_lower = [g.lower() for g in (item.get("genres") or [])]
            tags_str = str(item.get("tags") or "").lower()
            has_romance = ("romance" in genres_lower) or ("romance" in tags_str)
            assert has_romance, f"Item '{item.get('title')}' missing Romance"

@pytest.mark.asyncio
async def test_roulette_genre_exclusion():
    """When exclude_genres=['Horror'], no candidate may contain Horror."""
    async with AsyncSessionLocal() as db:
        filters = RecommendFilters(exclude_genres=["Horror"])
        results = await retrieve_roulette_manga(db, filters=filters, pool_limit=15)
        assert len(results) > 0

        for item in results:
            genres_lower = [g.lower() for g in (item.get("genres") or [])]
            tag_names = [t.get("name", "").lower() for t in (item.get("tags") or [])]
            assert "horror" not in genres_lower, f"'{item.get('title')}' should not have Horror genre"
            assert "horror" not in tag_names, f"'{item.get('title')}' should not have Horror tag"

# -------------------------------------------------------------
# 3. Score, Year, Chapters, Status Filters
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_roulette_min_score():
    """When min_score=85, all returned candidates must have average_score >= 85."""
    async with AsyncSessionLocal() as db:
        filters = RecommendFilters(min_score=85)
        results = await retrieve_roulette_manga(db, filters=filters, pool_limit=10)
        assert len(results) > 0

        for item in results:
            score = item.get("average_score")
            assert score is not None
            assert score >= 85, f"'{item.get('title')}' score {score} < 85"

@pytest.mark.asyncio
async def test_roulette_year_range():
    """When min_year=2020 and max_year=2024, all returned candidates must fall in [2020, 2024]."""
    async with AsyncSessionLocal() as db:
        filters = RecommendFilters(min_year=2020, max_year=2024)
        results = await retrieve_roulette_manga(db, filters=filters, pool_limit=10)
        assert len(results) > 0

        for item in results:
            year = item.get("start_year")
            assert year is not None
            assert 2020 <= year <= 2024, f"'{item.get('title')}' start_year {year} outside [2020, 2024]"

@pytest.mark.asyncio
async def test_roulette_status_filter():
    """When status=['FINISHED'], all returned candidates must have status FINISHED."""
    async with AsyncSessionLocal() as db:
        filters = RecommendFilters(status=["FINISHED"])
        results = await retrieve_roulette_manga(db, filters=filters, pool_limit=10)
        assert len(results) > 0

        for item in results:
            assert item.get("status") == "FINISHED"

@pytest.mark.asyncio
async def test_roulette_nsfw_default_safe():
    """By default (nsfw=False), no Hentai or Erotica titles should be returned."""
    async with AsyncSessionLocal() as db:
        filters = RecommendFilters(nsfw=False)
        results = await retrieve_roulette_manga(db, filters=filters, pool_limit=20)
        assert len(results) > 0

        for item in results:
            genres_lower = [g.lower() for g in (item.get("genres") or [])]
            assert "hentai" not in genres_lower
            assert "erotica" not in genres_lower

# -------------------------------------------------------------
# 4. Combined Multi-Filter Test
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_roulette_combined_multi_filters():
    """Multi-filter combination: Manga + Romance + min_score 75 + exclude Horror."""
    async with AsyncSessionLocal() as db:
        filters = RecommendFilters(
            format_type=["manga"],
            genres=["Romance"],
            exclude_genres=["Horror"],
            min_score=75
        )
        results = await retrieve_roulette_manga(db, filters=filters, pool_limit=8)
        assert len(results) > 0

        for item in results:
            fmt = item.get("format_type")
            title = item.get("title")
            genres_lower = [g.lower() for g in (item.get("genres") or [])]
            tags_str = str(item.get("tags") or "").lower()
            score = item.get("average_score")

            assert fmt == "MANGA", f"'{title}' should be MANGA"
            assert ("romance" in genres_lower) or ("romance" in tags_str), f"'{title}' missing Romance"
            assert "horror" not in genres_lower, f"'{title}' has Horror"
            assert score >= 75, f"'{title}' score {score} < 75"
