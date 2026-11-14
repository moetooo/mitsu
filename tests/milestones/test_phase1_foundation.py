"""
Automated Test Suite for Phase 1 — Canonical Metadata Foundation.

Tests:
1. Canonical Vocabulary integrity, categories, and uniqueness.
2. Synonym and Alias mapping, whitespace/case normalization, unknown preservation.
3. InferredTag data model, provenance validation, confidence, and conflict-free merging.
4. Alternative titles extraction and preservation during normalization & upsert.
5. Database schema verification and migration idempotency.
"""

import pytest
from sqlalchemy import text
from app.db import AsyncSessionLocal
from app.enrichment.vocabulary import (
    CANONICAL_VOCABULARY,
    CanonicalTag,
    TagCategory,
    get_tag_by_slug,
    get_tags_by_category,
    list_all_tags,
    SLUG_PATTERN
)
from app.enrichment.synonyms import (
    resolve_canonical_tag,
    normalize_tag_input,
    ALIAS_MAP
)
from app.enrichment.models import (
    InferredTag,
    merge_inferred_tags,
    ALLOWED_PROVENANCES
)
from app.ingestion.normalize import anilist_to_record, mangadex_to_record
from app.ingestion.upsert import smart_upsert_manga
from app.db_models import Manga

# ─────────────────────────────────────────────────────────────────────────────
# 1. CANONICAL VOCABULARY TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_canonical_tags_exist_and_non_empty():
    """Vocabulary must contain canonical tags across all 7 required categories."""
    assert len(CANONICAL_VOCABULARY) > 40
    for cat in TagCategory:
        tags_in_cat = get_tags_by_category(cat)
        assert len(tags_in_cat) > 0, f"Category '{cat.value}' must have registered canonical tags"

def test_canonical_slugs_are_stable_snake_case():
    """Every canonical tag slug must follow strict lowercase snake_case format."""
    for slug, tag in CANONICAL_VOCABULARY.items():
        assert SLUG_PATTERN.match(slug), f"Slug '{slug}' is not valid snake_case"
        assert slug == tag.slug
        assert slug == slug.lower()
        assert " " not in slug
        assert "-" not in slug

def test_canonical_names_are_unique():
    """Every canonical tag must have a unique display name (case-insensitive)."""
    seen_names = set()
    for tag in CANONICAL_VOCABULARY.values():
        low_name = tag.name.lower().strip()
        assert low_name not in seen_names, f"Duplicate canonical tag name found: '{tag.name}'"
        seen_names.add(low_name)

def test_get_tag_by_slug():
    """Should retrieve the tag by slug or case-insensitive string, and None for invalid."""
    tag = get_tag_by_slug("boys_love")
    assert tag is not None
    assert tag.name == "Boys' Love"
    assert tag.category == TagCategory.THEME

    assert get_tag_by_slug("BOYS_LOVE") == tag
    assert get_tag_by_slug("non_existent_slug_xyz") is None
    assert get_tag_by_slug("") is None

# ─────────────────────────────────────────────────────────────────────────────
# 2. SYNONYM AND ALIAS MAPPING TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_tag_input():
    """Normalizer must strip punctuation, lower case, and collapse whitespace."""
    assert normalize_tag_input("  Boys' Love  ") == "boys love"
    assert normalize_tag_input("Shounen-Ai") == "shounen ai"
    assert normalize_tag_input("SCI_FI") == "sci fi"
    assert normalize_tag_input("Portal   Fantasy") == "portal fantasy"
    assert normalize_tag_input(None) == ""
    assert normalize_tag_input("") == ""

def test_known_aliases_map_to_canonical_tags():
    """Known aliases from diverse sources must resolve to correct canonical tags."""
    # Boys' Love aliases
    for alias in ["BL", "bl", "Boys Love", "boys' love", "boy's love", "Yaoi", "yaoi", "Shounen Ai", "shounen-ai"]:
        tag = resolve_canonical_tag(alias)
        assert tag is not None, f"Failed to resolve alias '{alias}'"
        assert tag.slug == "boys_love", f"Alias '{alias}' resolved to '{tag.slug}' instead of 'boys_love'"

    # Girls' Love aliases
    for alias in ["GL", "gl", "Girls Love", "girls' love", "Yuri", "yuri", "Shoujo Ai", "shoujo-ai"]:
        tag = resolve_canonical_tag(alias)
        assert tag is not None, f"Failed to resolve alias '{alias}'"
        assert tag.slug == "girls_love", f"Alias '{alias}' resolved to '{tag.slug}' instead of 'girls_love'"

    # Tropes and Themes
    assert resolve_canonical_tag("another world").slug == "isekai"
    assert resolve_canonical_tag("portal fantasy").slug == "isekai"
    assert resolve_canonical_tag("transmigration").slug == "reincarnation"
    assert resolve_canonical_tag("reborn").slug == "reincarnation"
    assert resolve_canonical_tag("time regression").slug == "regression"
    assert resolve_canonical_tag("returner").slug == "regression"
    assert resolve_canonical_tag("academy").slug == "school_life"
    assert resolve_canonical_tag("campus").slug == "college_university"
    assert resolve_canonical_tag("office worker").slug == "workplace"
    assert resolve_canonical_tag("op mc").slug == "overpowered_protagonist"
    assert resolve_canonical_tag("level up").slug == "system_level_up"

def test_unknown_tag_preservation():
    """Unrecognized source tags must return None so they remain intact in raw metadata."""
    assert resolve_canonical_tag("Completely Obscure Niche Tag 1234") is None
    assert resolve_canonical_tag("Random Publisher Specific Label") is None
    assert resolve_canonical_tag(None) is None

# ─────────────────────────────────────────────────────────────────────────────
# 3. ENRICHED METADATA AND STORAGE TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_inferred_tag_instantiation_and_validation():
    """InferredTag must enforce valid confidence (0.0 to 1.0) and allowed provenances."""
    tag = InferredTag.from_canonical(
        slug="boys_love",
        confidence=0.98,
        provenance="rule",
        source_rule="rule_bl_synopsis_keyword"
    )
    assert tag.slug == "boys_love"
    assert tag.name == "Boys' Love"
    assert tag.category == "theme"
    assert tag.confidence == 0.98
    assert tag.provenance == "rule"
    assert tag.source_rule == "rule_bl_synopsis_keyword"
    assert tag.created_at is not None

    # Serialization test
    d = tag.to_dict()
    assert d["slug"] == "boys_love"
    assert d["source_rule"] == "rule_bl_synopsis_keyword"

    # Invalid confidence test (< 0 or > 1)
    with pytest.raises(ValueError):
        InferredTag.from_canonical(slug="boys_love", confidence=1.5, provenance="rule")
    with pytest.raises(ValueError):
        InferredTag.from_canonical(slug="boys_love", confidence=-0.1, provenance="rule")

    # Invalid provenance test
    with pytest.raises(ValueError):
        InferredTag.from_canonical(slug="boys_love", confidence=0.8, provenance="magic_wand")

def test_merge_inferred_tags_deduplication_and_provenance_priority():
    """Inferred tags merger must deduplicate by slug and prioritize higher provenance / confidence."""
    existing = [
        {"slug": "isekai", "name": "Isekai", "category": "theme", "confidence": 0.60, "provenance": "llm"},
        {"slug": "action", "name": "Action", "category": "genre", "confidence": 0.95, "provenance": "external"}
    ]

    incoming = [
        # Same tag 'isekai' with higher priority provenance 'rule' -> should overwrite
        {"slug": "isekai", "name": "Isekai", "category": "theme", "confidence": 0.90, "provenance": "rule"},
        # New tag 'regression' -> should be added
        {"slug": "regression", "name": "Regression", "category": "theme", "confidence": 0.85, "provenance": "rule"}
    ]

    merged = merge_inferred_tags(existing, incoming)
    slugs = [t["slug"] for t in merged]

    assert len(merged) == 3
    assert "action" in slugs
    assert "isekai" in slugs
    assert "regression" in slugs

    # Check that isekai was upgraded to 'rule' provenance with 0.90 confidence
    isekai_tag = next(t for t in merged if t["slug"] == "isekai")
    assert isekai_tag["provenance"] == "rule"
    assert isekai_tag["confidence"] == 0.90

# ─────────────────────────────────────────────────────────────────────────────
# 4. ALTERNATIVE TITLES EXTRACTION & NORMALIZATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_anilist_synonyms_extraction():
    """AniList normalizer must preserve synonyms into alternative_titles without clobbering titles."""
    raw = {
        "id": 12345,
        "title": {"romaji": "Solo Leveling", "english": "Only I Level Up", "native": "나 혼자만 레벨업"},
        "synonyms": ["Na Honjaman Level-Up", "I Alone Level Up", "Solo Leveling"],
        "description": "A hunter discovers a secret quest.",
        "genres": ["Action", "Fantasy"],
        "tags": [{"name": "Dungeon", "rank": 95}]
    }
    rec = anilist_to_record(raw)
    assert "alternative_titles" in rec
    assert "Na Honjaman Level-Up" in rec["alternative_titles"]
    assert "I Alone Level Up" in rec["alternative_titles"]
    # Existing title fields remain intact
    assert rec["title_romaji"] == "Solo Leveling"
    assert rec["title_english"] == "Only I Level Up"
    assert rec["title_native"] == "나 혼자만 레벨업"

def test_mangadex_alt_titles_extraction():
    """MangaDex normalizer must preserve altTitles into alternative_titles."""
    raw = {
        "id": "md-12345",
        "attributes": {
            "title": {"en": "Omniscient Reader"},
            "altTitles": [
                {"ko": "전지적 독자 시점"},
                {"en": "ORV"},
                {"ja-ro": "Zenjiteki Dokusha Shiten"}
            ],
            "description": {"en": "Only one person knows the ending of the world."},
            "tags": []
        }
    }
    rec = mangadex_to_record(raw)
    assert "alternative_titles" in rec
    assert "전지적 독자 시점" in rec["alternative_titles"]
    assert "ORV" in rec["alternative_titles"]
    assert "Zenjiteki Dokusha Shiten" in rec["alternative_titles"]
    assert rec["title_english"] == "Omniscient Reader"

# ─────────────────────────────────────────────────────────────────────────────
# 5. DATABASE SCHEMA & UPSERT INTEGRATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_schema_columns_and_indexes_exist():
    """Verify live PostgreSQL schema contains alternative_titles, inferred_tags, and GIN indexes."""
    async with AsyncSessionLocal() as session:
        # Check columns
        res_cols = await session.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'manga' AND column_name IN ('alternative_titles', 'inferred_tags');
        """))
        cols = {row[0] for row in res_cols.fetchall()}
        assert "alternative_titles" in cols, "Column 'alternative_titles' must exist on manga table"
        assert "inferred_tags" in cols, "Column 'inferred_tags' must exist on manga table"

        # Check indexes
        res_idx = await session.execute(text("""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'manga' AND indexname IN ('idx_manga_alt_titles', 'idx_manga_inferred_tags', 'idx_manga_tags');
        """))
        idxs = {row[0] for row in res_idx.fetchall()}
        assert "idx_manga_alt_titles" in idxs, "GIN index 'idx_manga_alt_titles' must exist"
        assert "idx_manga_inferred_tags" in idxs, "GIN index 'idx_manga_inferred_tags' must exist"
        assert "idx_manga_tags" in idxs, "GIN index 'idx_manga_tags' must exist"

@pytest.mark.asyncio
async def test_smart_upsert_multi_source_merging():
    """Verify smart_upsert_manga merges alternative_titles, inferred_tags, and preserves existing titles."""
    async with AsyncSessionLocal() as session:
        # Create a unique test record
        test_year = 2024
        initial_record = {
            "anilist_id": 99999901,
            "title_romaji": "Phase1 Test Manga",
            "title_english": "Phase 1 Test Manga",
            "start_year": test_year,
            "alternative_titles": ["Test Alias Alpha"],
            "genres": ["Action"],
            "tags": [{"name": "Martial Arts", "rank": 80}],
            "inferred_tags": [
                {"slug": "action", "name": "Action", "category": "genre", "confidence": 1.0, "provenance": "external"}
            ]
        }

        # First insert
        manga_obj = await smart_upsert_manga(session, initial_record)
        await session.flush()
        m_id = manga_obj.id
        await session.commit()

        try:
            # Second upsert representing a secondary source match (e.g. MangaDex with new alias & inferred tag)
            secondary_record = {
                "anilist_id": 99999901,
                "mangadex_id": "md-test-99999901",
                "start_year": test_year,
                "alternative_titles": ["Test Alias Beta", "Test Alias Alpha"], # Duplicate should be unioned
                "genres": ["Fantasy"], # Should union with Action -> Action, Fantasy
                "inferred_tags": [
                    {"slug": "fantasy", "name": "Fantasy", "category": "genre", "confidence": 0.95, "provenance": "rule"}
                ]
            }

            updated_manga = await smart_upsert_manga(session, secondary_record)
            await session.commit()

            # Verify fields on updated manga
            assert updated_manga.id == m_id
            assert updated_manga.mangadex_id == "md-test-99999901"
            # Existing title was preserved
            assert updated_manga.title_romaji == "Phase1 Test Manga"
            # Alternative titles merged as union
            assert "Test Alias Alpha" in updated_manga.alternative_titles
            assert "Test Alias Beta" in updated_manga.alternative_titles
            assert len(updated_manga.alternative_titles) == 2
            # Genres merged as union
            assert "Action" in updated_manga.genres
            assert "Fantasy" in updated_manga.genres
            # Inferred tags merged
            inferred_slugs = [t["slug"] for t in updated_manga.inferred_tags]
            assert "action" in inferred_slugs
            assert "fantasy" in inferred_slugs
        finally:
            # Cleanup test record
            await session.execute(text("DELETE FROM manga WHERE id = :id AND start_year = :year"), {"id": m_id, "year": test_year})
            await session.commit()
