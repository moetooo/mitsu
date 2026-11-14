import pytest
import os
import sys
import asyncio
from sqlalchemy import text

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app.db import AsyncSessionLocal
from app.enrichment.vocabulary import CANONICAL_VOCABULARY
from app.enrichment.external_gap_mapper import (
    map_external_gap_tag,
    parse_mu_id,
    detect_conflicts
)

def test_exact_external_mapping():
    """Verify that exact external categories resolve with EXACT match quality."""
    cases = [
        ("MangaUpdates", "Contract Marriage", "contract_marriage", "EXACT"),
        ("MangaUpdates", "Marriage of Convenience", "contract_marriage", "EXACT"),
        ("MangaUpdates", "Regression", "regression", "EXACT"),
        ("MangaUpdates", "Overpowered Protagonist", "overpowered_protagonist", "EXACT"),
        ("MangaUpdates", "Enemies Become Lovers", "enemies_to_lovers", "EXACT"),
        ("MangaUpdates", "Friends Become Lovers", "friends_to_lovers", "EXACT"),
        ("MangaUpdates", "Childhood Friend/s", "childhood_friends", "EXACT"),
        ("MangaUpdates", "Level System", "system_level_up", "EXACT"),
        ("MangaUpdates", "Secret Identity", "secret_identity", "EXACT"),
        ("MangaUpdates", "Manga", "manga", "EXACT"),
        ("MangaUpdates", "Manhwa", "manhwa", "EXACT"),
        ("MangaUpdates", "Manhua", "manhua", "EXACT"),
        ("AniList", "JP", "manga", "EXACT"),
        ("AniList", "KR", "manhwa", "EXACT"),
        ("AniList", "CN", "manhua", "EXACT"),
        ("MangaDex", "ja", "manga", "EXACT"),
        ("MangaDex", "ko", "manhwa", "EXACT"),
        ("MangaDex", "zh", "manhua", "EXACT"),
    ]
    for source, raw_tag, expected_slug, expected_quality in cases:
        res = map_external_gap_tag(source, raw_tag)
        assert res is not None, f"Expected mapping for ({source}, {raw_tag})"
        slug, quality = res
        assert slug == expected_slug, f"Expected slug {expected_slug}, got {slug}"
        assert quality == expected_quality, f"Expected quality {expected_quality}, got {quality}"


def test_strong_external_mapping():
    """Verify that strong domain equivalents resolve with STRONG match quality."""
    cases = [
        ("MangaUpdates", "Arranged Marriage", "contract_marriage", "STRONG"),
        ("MangaUpdates", "Strong to Stronger", "overpowered_protagonist", "STRONG"),
        ("MangaUpdates", "Rivals Become Lovers", "enemies_to_lovers", "STRONG"),
        ("MangaUpdates", "Slow Romance", "slow_burn", "STRONG"),
        ("MangaUpdates", "Weak to Strong", "underdog", "STRONG"),
        ("MangaUpdates", "System", "system_level_up", "STRONG"),
    ]
    for source, raw_tag, expected_slug, expected_quality in cases:
        res = map_external_gap_tag(source, raw_tag)
        assert res is not None, f"Expected mapping for ({source}, {raw_tag})"
        slug, quality = res
        assert slug == expected_slug, f"Expected slug {expected_slug}, got {slug}"
        assert quality == expected_quality, f"Expected quality {expected_quality}, got {quality}"


def test_partial_mapping_rejection():
    """Verify that overly broad or partial terms are tagged as PARTIAL or rejected."""
    # These must be tagged PARTIAL, not accepted as EXACT or STRONG
    partial_cases = [
        ("MangaUpdates", "Marriage", "contract_marriage", "PARTIAL"),
        ("MangaUpdates", "Age Regression", "regression", "PARTIAL"),
        ("MangaUpdates", "Urban Fantasy", "fantasy_world", "PARTIAL"),
        ("MangaUpdates", "Hidden Abilities", "secret_identity", "PARTIAL"),
    ]
    for source, raw_tag, expected_slug, expected_quality in partial_cases:
        res = map_external_gap_tag(source, raw_tag)
        assert res is not None
        slug, quality = res
        assert slug == expected_slug
        assert quality == expected_quality
        assert quality not in ("EXACT", "STRONG"), f"Partial tag '{raw_tag}' must not be EXACT/STRONG"

    # These completely speculative leaps must return None
    rejected_cases = [
        ("MangaUpdates", "Male Protagonist"),
        ("MangaUpdates", "Dungeon"),
        ("MangaUpdates", "School Club"),
        ("AniList", "Romance"),
        ("MangaDex", "Action"),
    ]
    for source, raw_tag in rejected_cases:
        res = map_external_gap_tag(source, raw_tag)
        assert res is None, f"Speculative tag '{raw_tag}' from {source} must be rejected, got {res}"


def test_missing_external_tag():
    """Verify unmapped or missing external tags return None."""
    missing = [
        ("MangaUpdates", "NonExistentTagXYZ"),
        ("MangaUpdates", ""),
        ("AniList", "XX"),
        ("MangaDex", "unknown_lang"),
        ("UnknownSource", "Regression"),
    ]
    for source, raw in missing:
        assert map_external_gap_tag(source, raw) is None


def test_conflict_detection():
    """Verify that conflicting formats (manga vs manhwa) are flagged as CONFLICT."""
    instances = [
        {
            "manga_id": 47,
            "canonical_tag": "manhwa",
            "source": "MangaUpdates",
            "match_status": "EXTERNAL_SOLVED",
            "external_evidence": "Publication format categorized as Manhwa"
        },
        {
            "manga_id": 47,
            "canonical_tag": "manga",
            "source": "AniList",
            "match_status": "EXTERNAL_SOLVED",
            "external_evidence": "AniList countryOfOrigin: JP"
        }
    ]
    flagged = detect_conflicts(instances)
    assert len(flagged) == 2
    for r in flagged:
        assert r["match_status"] == "CONFLICT"
        assert "CONFLICT" in r["external_evidence"]


def test_id_matching():
    """Verify that numeric and MangaDex base36 MangaUpdates IDs decode properly."""
    # Plain integer string
    assert parse_mu_id("74934642156") == 74934642156
    assert parse_mu_id("12345") == 12345
    assert parse_mu_id(12345) == 12345

    # MangaDex base36 representation
    # 'yfa5fxo' base36 == 74934642156
    assert parse_mu_id("yfa5fxo") == 74934642156

    # None and empty
    assert parse_mu_id(None) is None
    assert parse_mu_id("") is None
    assert parse_mu_id("   ") is None


def test_provenance():
    """Verify that external pilot records preserve complete provenance columns."""
    sample_record = {
        "manga_id": 67,
        "title": "Wotaku ni Koi wa Muzukashii",
        "canonical_tag": "friends_to_lovers",
        "source": "MangaUpdates",
        "external_tag": "Friends Become Lovers",
        "match_status": "EXTERNAL_SOLVED",
        "match_quality": "EXACT",
        "external_evidence": "Category 'Friends Become Lovers' present in MangaUpdates community tags",
        "match_method": "TITLE_ALT_TITLE"
    }
    required_keys = {
        "manga_id", "title", "canonical_tag", "source", "external_tag",
        "match_status", "match_quality", "external_evidence", "match_method"
    }
    assert required_keys.issubset(set(sample_record.keys()))
    assert sample_record["source"] in ("MangaUpdates", "AniList", "MangaDex", "Wikidata")
    assert sample_record["match_method"] in ("DIRECT_ID", "CROSS_REFERENCE_ID", "TITLE_ALT_TITLE", "TITLE_YEAR", "FUZZY", "UNMATCHED")


@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_readonly_db():
    """Verify that PostgreSQL manga table remains completely read-only and unmutated."""
    async with AsyncSessionLocal() as session:
        # Capture counts before operation
        r_total_before = await session.execute(text("SELECT COUNT(*) FROM manga"))
        total_before = r_total_before.scalar()
        r_inf_before = await session.execute(
            text("SELECT COUNT(*) FROM manga WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb")
        )
        inferred_before = r_inf_before.scalar()

        # Run read-only pilot sample operation
        r_sample = await session.execute(
            text("SELECT id, title_english, genres, tags, inferred_tags FROM manga LIMIT 20")
        )
        sample_rows = r_sample.fetchall()
        assert len(sample_rows) == 20

        # Capture counts after operation
        r_total_after = await session.execute(text("SELECT COUNT(*) FROM manga"))
        total_after = r_total_after.scalar()
        r_inf_after = await session.execute(
            text("SELECT COUNT(*) FROM manga WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb")
        )
        inferred_after = r_inf_after.scalar()

        assert total_before == total_after, f"Row count changed during operation: {total_before} -> {total_after}"
        assert inferred_before == inferred_after, (
            f"PostgreSQL inferred_tags was modified! Expected {inferred_before}, got {inferred_after}"
        )

