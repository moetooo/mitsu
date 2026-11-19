import pytest
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.models import RecommendFilters
from app.services.embedding import generate_embedding
from app.services.query_filters import apply_filter_criteria
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
def test_search_query_sanitizer_keeps_text_that_looks_like_sql():
    """API-18: the sanitizer is normalisation, not SQL detection.

    It used to delete `;`, `--` and the *words* `drop`/`delete`/`truncate`. On the
    live catalogue that altered 73 of the 76 titles carrying those markers and
    turned a query of exactly `Drop` into the empty string. Nothing is spliced
    into SQL any more -- every statement binds -- so the deletion protected
    nothing and only damaged real titles.
    """
    for title in ("Occultic;Nine", "STEINS;GATE DROPS", "Kaguya-sama -- Love is War"):
        assert sanitize_search_query(title) == title

    assert sanitize_search_query("   Drop   ") == "Drop"


def test_search_query_sanitizer_still_caps_length_and_control_characters():
    """What is left must still hold: a bounded query with no control characters."""
    assert sanitize_search_query("x" * 1_000) == "x" * 300
    assert sanitize_search_query("Naruto" + chr(0) + chr(7)) == "Naruto"
    assert sanitize_search_query("   ") == ""
    assert sanitize_search_query(None) == ""

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


def test_zero_chapter_bounds_are_not_a_chapter_range():
    """0 is "no bound", not "chapters BETWEEN 0 AND 0".

    The drawer's untouched state sends both bounds as 0. Bound literally, that
    pair matched almost no row, so a normal search returned one title and every
    sort looked identical.
    """
    where_clauses = []
    params = {}
    apply_filter_criteria(RecommendFilters(min_chapters=0, max_chapters=0), where_clauses, params)

    assert where_clauses == []
    assert params == {}


def test_real_chapter_bounds_are_still_bound():
    where_clauses = []
    params = {}
    apply_filter_criteria(RecommendFilters(min_chapters=5, max_chapters=100), where_clauses, params)

    assert params == {"min_chapters": 5, "max_chapters": 100}
    assert any("chapters >= :min_chapters" in clause for clause in where_clauses)
    assert any("chapters <= :max_chapters" in clause for clause in where_clauses)


def test_filter_list_sanitizer_keeps_tag_punctuation():
    """Tag names must survive normalisation intact.

    `sanitize_string_list` used to strip everything outside alphanumerics,
    spaces, hyphens, plus and hash, which deleted the apostrophe from `Boys' Love` / `Girls' Love`. The SQL
    builder then no longer recognised the tag alias, so `exclude_genres:
    ["Boys' Love"]` excluded nothing at all -- the reported bug. Values are
    bound parameters, so the text can stay as the catalogue spells it.
    """
    filters = RecommendFilters(
        genres=["Boys' Love"],
        exclude_genres=["Girls' Love", "Sci-Fi"],
        status=["FINISHED"],
    )
    cleaned = sanitize_recommend_filters(filters)
    assert cleaned.genres == ["Boys' Love"]
    assert cleaned.exclude_genres == ["Girls' Love", "Sci-Fi"]
    assert cleaned.status == ["FINISHED"]


def test_filter_list_sanitizer_still_drops_control_characters_and_caps_length():
    filters = RecommendFilters(exclude_genres=["Boys' Love" + chr(0) + chr(7), "x" * 80])
    cleaned = sanitize_recommend_filters(filters)
    assert cleaned.exclude_genres[0] == "Boys' Love"
    assert len(cleaned.exclude_genres[1]) == 50


@pytest.mark.asyncio
@pytest.mark.requires_catalog
async def test_exclude_boys_love_removes_every_bl_row():
    """Regression: excluding Boys' Love must remove BL rows from the page.

    Exercises the whole chain the UI uses -- sanitizer, alias resolution, SQL --
    against the catalogue, and accepts the apostrophe-free spelling a client may
    send after normalising the vocabulary label.
    """
    emb = await generate_embedding("school romance confession")
    for spelling in ("Boys' Love", "Boys Love"):
        filters = sanitize_recommend_filters(
            RecommendFilters(exclude_genres=[spelling])
        )
        async with AsyncSessionLocal() as db:
            results = await retrieve_similar_manga(db, emb, filters=filters, limit=10)
            assert len(results) > 0
            for row in results:
                tag_names = [t.get("name") for t in (row["manga"].tags or [])]
                title = row["manga"].title_english or row["manga"].title_romaji
                assert "Boys' Love" not in tag_names, f"{title} is BL but was returned"
                assert "Yaoi" not in tag_names, f"{title} is Yaoi but was returned"


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


@pytest.mark.asyncio
@pytest.mark.requires_catalog
async def test_sql_shaped_query_is_harmless_now_that_it_is_not_rewritten():
    """API-18, end to end: the text survives sanitising and is still only a value.

    The strap line matters: `search_titles` binds the term, so the payload reaches
    PostgreSQL as a parameter and matches nothing. `Occultic;Nine` is a real
    catalogue title the old filter used to corrupt (`OcculticNine`).
    """
    from app.services import catalog

    async with AsyncSessionLocal() as db:
        assert await catalog.search_titles(db, "'; DROP TABLE manga; --", limit=5) == []
        assert await catalog.search_titles(db, "Occultic;Nine", limit=5)
        # The table the payload names is still there, with its rows.
        surviving = await db.scalar(text("SELECT count(*) FROM manga"))
        assert surviving > 0
