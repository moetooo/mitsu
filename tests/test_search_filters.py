import pytest
from app.db import AsyncSessionLocal
from app.models import RecommendFilters
from app.services.embedding import generate_embedding
from app.services.retrieval import retrieve_similar_manga
from app.utils.sanitizer import sanitize_search_query, sanitize_recommend_filters
from app.services.search_autocorrect import autocorrect_query

@pytest.fixture(scope="module")
def sample_embedding():
    import asyncio
    return asyncio.run(generate_embedding("action superpower battle"))

# -------------------------------------------------------------
# 1. Search Query Sanitizer & Autocorrect Tests
# -------------------------------------------------------------
def test_search_query_sanitizer():
    """Sanitizer must strip SQL injection comment markers and statement breakouts."""
    dirty_query = "   Naruto'; DROP TABLE manga; -- comment   "
    clean = sanitize_search_query(dirty_query)
    assert "--" not in clean
    assert ";" not in clean
    assert "DROP" not in clean
    assert "Naruto" in clean

@pytest.mark.asyncio
@pytest.mark.requires_catalog
async def test_search_autocorrect():
    """Autocorrect should resolve known popular title typos like 'bersrk' to 'Berserk'."""
    async with AsyncSessionLocal() as db:
        corrected = await autocorrect_query("bersrk", db)
        assert "berserk" in corrected.lower()

def test_search_autocorrect_alternative_titles_vocabulary():
    """Autocorrect vocabulary token extraction should extract tokens from alternative_titles."""
    from app.services.search_autocorrect import _words, _correction_for_token
    test_alt_titles = ["Shingeki no Kyojin: The Final Season", "Sousou no Frieren", "Slime Tensei"]
    vocab = _words(test_alt_titles)
    assert "shingeki" in vocab
    assert "kyojin" in vocab
    assert "season" in vocab
    assert "frieren" in vocab
    assert "tensei" in vocab

    # Verify correction of a typo against vocabulary derived from alternative titles
    corrected = _correction_for_token("shingki", vocab)
    assert corrected == "shingeki"


# -------------------------------------------------------------
# 2. Search Retrieval with Format Filter Tests
# -------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.requires_catalog
async def test_search_filter_manga_only():
    """Search with format_type=['manga'] must return ONLY authentic Japanese manga."""
    emb = await generate_embedding("action fantasy adventure")
    filters = RecommendFilters(format_type=["manga"])

    async with AsyncSessionLocal() as db:
        results = await retrieve_similar_manga(db, emb, filters=filters, limit=8)
        assert len(results) > 0

        for r in results:
            m = r["manga"]
            fmt = m.format_type
            title = m.title_english or m.title_romaji or "Unknown"
            genres = [g.lower() for g in (m.genres or [])]
            tags_str = str(m.tags or "").lower()

            assert fmt == "MANGA", f"'{title}' should be MANGA, got {fmt}"
            assert "manhwa" not in genres, f"'{title}' has Manhwa genre"
            assert "manhua" not in genres, f"'{title}' has Manhua genre"
            assert "webtoon" not in tags_str, f"'{title}' has Webtoon tag"

@pytest.mark.asyncio
@pytest.mark.requires_catalog
async def test_search_filter_manhwa_only():
    """Search with format_type=['manhwa'] must return ONLY Korean Manhwa."""
    emb = await generate_embedding("dungeon hunter leveling")
    filters = RecommendFilters(format_type=["manhwa"])

    async with AsyncSessionLocal() as db:
        results = await retrieve_similar_manga(db, emb, filters=filters, limit=8)
        assert len(results) > 0

        for r in results:
            m = r["manga"]
            fmt = m.format_type
            title = m.title_english or m.title_romaji or "Unknown"
            assert fmt == "MANHWA", f"'{title}' expected MANHWA, got {fmt}"

@pytest.mark.asyncio
@pytest.mark.requires_catalog
async def test_search_filter_manhua_only():
    """Search with format_type=['manhua'] must return ONLY Chinese Manhua."""
    emb = await generate_embedding("martial arts cultivation ancient")
    filters = RecommendFilters(format_type=["manhua"])

    async with AsyncSessionLocal() as db:
        results = await retrieve_similar_manga(db, emb, filters=filters, limit=8)
        assert len(results) > 0

        for r in results:
            m = r["manga"]
            fmt = m.format_type
            title = m.title_english or m.title_romaji or "Unknown"
            assert fmt == "MANHUA", f"'{title}' expected MANHUA, got {fmt}"

# -------------------------------------------------------------
# 3. Search Retrieval with Genre Inclusion & Exclusion
# -------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.requires_catalog
async def test_search_filter_genre_inclusion():
    """Search with genres=['Romance'] must return titles containing Romance."""
    emb = await generate_embedding("school life feelings")
    filters = RecommendFilters(genres=["Romance"])

    async with AsyncSessionLocal() as db:
        results = await retrieve_similar_manga(db, emb, filters=filters, limit=8)
        assert len(results) > 0

        for r in results:
            m = r["manga"]
            genres_lower = [g.lower() for g in (m.genres or [])]
            tags_str = str(m.tags or "").lower()
            has_romance = ("romance" in genres_lower) or ("romance" in tags_str)
            assert has_romance, f"'{m.title_english or m.title_romaji}' missing Romance"

@pytest.mark.asyncio
@pytest.mark.requires_catalog
async def test_search_filter_genre_exclusion():
    """Search with exclude_genres=['Horror'] must NEVER return Horror titles."""
    emb = await generate_embedding("dark mystery thriller")
    filters = RecommendFilters(exclude_genres=["Horror"])

    async with AsyncSessionLocal() as db:
        results = await retrieve_similar_manga(db, emb, filters=filters, limit=10)
        assert len(results) > 0

        for r in results:
            m = r["manga"]
            genres_lower = [g.lower() for g in (m.genres or [])]
            tags_str = str(m.tags or "").lower()
            assert "horror" not in genres_lower, f"'{m.title_english or m.title_romaji}' has Horror"
            tag_names = [t.get("name", "").lower() for t in (m.tags or [])]
            assert "horror" not in tag_names, f"'{m.title_english or m.title_romaji}' has exact Horror tag"

# -------------------------------------------------------------
# 4. Search Retrieval with Multi-Filter Combination
# -------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.requires_catalog
async def test_search_filter_multi_combination():
    """Search combining Manga + Action + min_score 75 + exclude Horror."""
    emb = await generate_embedding("sword fighting warrior")
    filters = RecommendFilters(
        format_type=["manga"],
        genres=["Action"],
        exclude_genres=["Horror"],
        min_score=75
    )

    async with AsyncSessionLocal() as db:
        results = await retrieve_similar_manga(db, emb, filters=filters, limit=8)
        assert len(results) > 0

        for r in results:
            m = r["manga"]
            fmt = m.format_type
            title = m.title_english or m.title_romaji or "Unknown"
            genres_lower = [g.lower() for g in (m.genres or [])]
            tags_str = str(m.tags or "").lower()

            assert fmt == "MANGA", f"'{title}' should be MANGA"
            tag_names = [t.get("name", "").lower() for t in (m.tags or [])]
            assert ("action" in genres_lower) or ("action" in tag_names), f"'{title}' missing Action"
            assert "horror" not in genres_lower, f"'{title}' has Horror"
            assert "horror" not in tag_names, f"'{title}' has Horror tag"
            assert m.average_score >= 75, f"'{title}' score {m.average_score} < 75"
