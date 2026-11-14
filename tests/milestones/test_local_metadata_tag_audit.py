import pytest
import os
import sys
import asyncio
from sqlalchemy import text

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from app.db import AsyncSessionLocal
from app.enrichment.vocabulary import CANONICAL_VOCABULARY, get_tag_by_slug
from app.enrichment.synonyms import normalize_tag_input, resolve_canonical_tag, RAW_ALIAS_DEFINITIONS

def test_exact_tag_mapping():
    """Verify that exact matches resolve accurately to their canonical tag slugs."""
    samples = [
        ("Reincarnation", "reincarnation"),
        ("Action", "action"),
        ("Drama", "drama"),
        ("Slice of Life", "slice_of_life"),
        ("Horror", "horror"),
        ("Time Travel", "time_travel"),
        ("Anthology", "anthology")
    ]
    for raw, expected_slug in samples:
        tag = resolve_canonical_tag(raw)
        assert tag is not None, f"Failed to resolve exact tag '{raw}'"
        assert tag.slug == expected_slug

def test_synonym_mapping():
    """Verify that defined synonyms in synonyms.py map to their canonical tags."""
    samples = [
        ("BL", "boys_love"),
        ("Yaoi", "boys_love"),
        ("GL", "girls_love"),
        ("Yuri", "girls_love"),
        ("Super Power", "superpowers"),
        ("Office", "workplace"),
        ("Samurai", "feudal_japan"),
        ("Dungeon", "dungeon_gate"),
        ("Villainess", "reborn_as_a_villainess"),
        ("Web Comic", "webtoon"),
        ("Oneshot", "one_shot")
    ]
    for raw, expected_slug in samples:
        tag = resolve_canonical_tag(raw)
        assert tag is not None, f"Failed to resolve synonym tag '{raw}'"
        assert tag.slug == expected_slug

def test_unknown_tag_handling():
    """Verify that unmapped source tags return None and are not falsely categorized."""
    unknown_samples = [
        "Drawing",
        "Heterosexual",
        "Bullying",
        "Nudity",
        "Primarily Adult Cast",
        "Unknown Tag 12345"
    ]
    for raw in unknown_samples:
        tag = resolve_canonical_tag(raw)
        assert tag is None, f"Unmapped tag '{raw}' should not resolve to canonical tag, got {tag}"

def test_no_unsafe_semantic_mapping():
    """Verify that speculative semantic leaps are strictly rejected."""
    unsafe_samples = [
        ("Marriage", "contract_marriage"),
        ("Friends", "friends_to_lovers"),
        ("Romance", "slow_burn"),
        ("Game", "system_level_up"),
        ("Teens' Love", "boys_love"),
        ("Teens' Love", "girls_love"),
        ("Age Regression", "regression")
    ]
    for raw, forbidden_slug in unsafe_samples:
        tag = resolve_canonical_tag(raw)
        if tag is not None:
            assert tag.slug != forbidden_slug, f"Unsafe semantic mapping detected: '{raw}' mapped to '{forbidden_slug}'"

def test_duplicate_raw_values():
    """Verify that duplicate raw tag inputs produce deduplicated canonical tag slugs."""
    raw_list = ["Action", "action", "ACTION", "Drama", "drama"]
    resolved = {resolve_canonical_tag(r).slug for r in raw_list if resolve_canonical_tag(r)}
    assert resolved == {"action", "drama"}

def test_case_normalization():
    """Verify that casing, spaces, and punctuation normalize cleanly."""
    variations = [
        "  REINCARNATION  ",
        "reincarnation",
        "ReInCaRnAtIoN",
        "Boys' Love",
        "boys love",
        "BOYS LOVE"
    ]
    expected = [
        "reincarnation",
        "reincarnation",
        "reincarnation",
        "boys_love",
        "boys_love",
        "boys_love"
    ]
    for raw, exp_slug in zip(variations, expected):
        tag = resolve_canonical_tag(raw)
        assert tag is not None
        assert tag.slug == exp_slug

@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_db_read_only_behavior():
    """Ensure PostgreSQL database remains completely untouched and read-only."""
    async with AsyncSessionLocal() as session:
        # Capture counts before operation
        r_total_before = await session.execute(text("SELECT COUNT(*) FROM manga"))
        total_before = r_total_before.scalar()
        r_inferred_before = await session.execute(
            text("SELECT COUNT(*) FROM manga WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb")
        )
        inferred_before = r_inferred_before.scalar()

        # Run read-only metadata audit sample operation
        sample = await session.execute(
            text("SELECT id, title_english, genres, tags, inferred_tags FROM manga LIMIT 20")
        )
        rows = sample.fetchall()
        assert len(rows) == 20

        # Capture counts after operation
        r_total_after = await session.execute(text("SELECT COUNT(*) FROM manga"))
        total_after = r_total_after.scalar()
        r_inferred_after = await session.execute(
            text("SELECT COUNT(*) FROM manga WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb")
        )
        inferred_after = r_inferred_after.scalar()

    assert total_before == total_after, f"Row count changed: {total_before} -> {total_after}"
    assert inferred_before == inferred_after, (
        f"Database inferred_tags count altered: before={inferred_before}, after={inferred_after}"
    )

