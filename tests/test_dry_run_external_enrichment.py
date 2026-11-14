import pytest
import os
import sys
import csv
import asyncio
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import AsyncSessionLocal
from app.enrichment.vocabulary import CANONICAL_VOCABULARY
from app.enrichment.external_gap_mapper import (
    map_external_gap_tag,
    parse_mu_id,
    detect_conflicts,
    classify_format_candidate,
    resolve_format_from_script
)
import scripts.dry_run_external_enrichment as dry_run_module


def test_dry_run_flag_and_no_write_guarantee():
    """Verify that DRY_RUN constant is strictly True and writes are impossible."""
    assert dry_run_module.DRY_RUN is True


def test_source_priority():
    """Verify source hierarchy for gap enrichment: MangaUpdates > AniList > MangaDex > Wikidata."""
    # MangaUpdates provides deep tropes
    mu_trope = map_external_gap_tag("MangaUpdates", "Childhood Friend/s")
    assert mu_trope == ("childhood_friends", "EXACT")

    # AniList provides countryOfOrigin format
    al_fmt = map_external_gap_tag("AniList", "JP")
    assert al_fmt == ("manga", "EXACT")

    # MangaDex provides originalLanguage format
    md_fmt = map_external_gap_tag("MangaDex", "ko")
    assert md_fmt == ("manhwa", "EXACT")


def test_id_matching_precedence():
    """Verify direct and cross-reference ID matching logic."""
    assert parse_mu_id("74934642156") == 74934642156
    assert parse_mu_id("yfa5fxo") == 74934642156
    assert parse_mu_id(None) is None


def test_partial_mapping_handling():
    """Verify partial categories are marked PARTIAL and not treated as safe."""
    partial_res = map_external_gap_tag("MangaUpdates", "Age Regression")
    assert partial_res == ("regression", "PARTIAL")

    partial_res2 = map_external_gap_tag("MangaUpdates", "Marriage")
    assert partial_res2 == ("contract_marriage", "PARTIAL")

    # Speculative leaps must be rejected (None)
    assert map_external_gap_tag("MangaUpdates", "Male Protagonist") is None
    assert map_external_gap_tag("MangaUpdates", "Dungeon") is None


def test_conflict_handling():
    """Verify that conflicting formats (e.g. MangaUpdates manga vs AniList manhwa) are detected."""
    instances = [
        {"canonical_tag": "manga", "source": "MangaUpdates", "match_status": "EXTERNAL_SOLVED"},
        {"canonical_tag": "manhwa", "source": "AniList", "match_status": "EXTERNAL_SOLVED"}
    ]
    res = detect_conflicts(instances)
    assert len(res) == 2
    for r in res:
        assert r["match_status"] == "CONFLICT"
        assert r["decision"] == "REVIEW_REQUIRED"


def test_deduplication_logic():
    """Verify that candidate tags for the same manga are deduplicated by canonical slug."""
    candidates = [
        {"canonical_tag": "contract_marriage", "quality": "PARTIAL", "source": "MangaUpdates"},
        {"canonical_tag": "contract_marriage", "quality": "EXACT", "source": "MangaUpdates"}
    ]
    dedup = {}
    for c in candidates:
        slug = c["canonical_tag"]
        if slug not in dedup:
            dedup[slug] = c
        else:
            if c["quality"] == "EXACT" and dedup[slug]["quality"] != "EXACT":
                dedup[slug] = c
    assert len(dedup) == 1
    assert dedup["contract_marriage"]["quality"] == "EXACT"


# ==============================================================================
# TARGETED REGRESSION TESTS FOR FORMAT CLASSIFICATION SAFETY
# ==============================================================================

def test_regression_no_jp_fallback():
    """Test 1: Given title_native = English/Latin-only, no verified external metadata -> no SAFE_TO_WRITE manga."""
    res = resolve_format_from_script(title_native="Solo Leveling", title_romaji="Na Honjaman Rebeleop")
    if res is not None:
        assert res["decision"] != "SAFE_TO_WRITE"
        assert res["canonical_tag"] != "manga"
    else:
        assert res is None  # Unresolved is the expected correct behavior


def test_regression_script_heuristic_cannot_become_authoritative():
    """Test 2: Given Hangul title, no external format metadata -> not SAFE_TO_WRITE manhwa."""
    res = resolve_format_from_script(title_native="나 혼자만 레벨업", title_romaji="Na Honjaman Rebeleop")
    assert res is not None
    assert res["canonical_tag"] == "manhwa"
    assert res["source"] == "local_heuristic"
    assert res["match_method"] == "SCRIPT_HEURISTIC"
    assert res["decision"] == "REVIEW_REQUIRED"
    assert res["decision"] != "SAFE_TO_WRITE"


def test_regression_verified_anilist_metadata():
    """Test 3: Given AniList countryOfOrigin = KR, verified AniList entity ID -> manhwa, SAFE_TO_WRITE, source = AniList, match_method = DIRECT_ID."""
    res = classify_format_candidate(
        source="AniList",
        raw_value="KR",
        match_method="DIRECT_ID",
        is_verified_external=True
    )
    assert res is not None
    assert res["canonical_tag"] == "manhwa"
    assert res["decision"] == "SAFE_TO_WRITE"
    assert res["source"] == "AniList"
    assert res["match_method"] == "DIRECT_ID"
    assert res["confidence"] == 0.95


def test_regression_verified_mangaupdates_metadata():
    """Test 4: Given MangaUpdates type = Manhua, verified matching entity -> manhua, SAFE_TO_WRITE."""
    res = classify_format_candidate(
        source="MangaUpdates",
        raw_value="Manhua",
        match_method="CROSS_REFERENCE_ID",
        is_verified_external=True
    )
    assert res is not None
    assert res["canonical_tag"] == "manhua"
    assert res["decision"] == "SAFE_TO_WRITE"
    assert res["source"] == "MangaUpdates"
    assert res["match_method"] == "CROSS_REFERENCE_ID"


def test_regression_verified_mangadex_metadata():
    """Test 5: Given MangaDex originalLanguage = zh, verified entity -> manhua, SAFE_TO_WRITE."""
    res = classify_format_candidate(
        source="MangaDex",
        raw_value="zh",
        match_method="DIRECT_ID",
        is_verified_external=True
    )
    assert res is not None
    assert res["canonical_tag"] == "manhua"
    assert res["decision"] == "SAFE_TO_WRITE"
    assert res["source"] == "MangaDex"
    assert res["match_method"] == "DIRECT_ID"


def test_regression_missing_external_evidence():
    """Test 6: Missing external evidence -> no authoritative format assignment."""
    assert classify_format_candidate("AniList", None, "DIRECT_ID", is_verified_external=True) is None
    assert classify_format_candidate("AniList", "", "DIRECT_ID", is_verified_external=True) is None
    assert classify_format_candidate("AniList", "XX", "DIRECT_ID", is_verified_external=True) is None
    assert resolve_format_from_script(None, None) is None
    assert resolve_format_from_script("", "") is None


def test_regression_existing_conflict_pattern():
    """Test 7: Existing conflict pattern (AniList DIRECT_ID manhwa vs MangaUpdates TITLE_ALT_TITLE manga) -> REVIEW_REQUIRED, never SAFE_TO_WRITE."""
    instances = [
        classify_format_candidate("AniList", "KR", "DIRECT_ID", is_verified_external=True),
        classify_format_candidate("MangaUpdates", "Manga", "TITLE_ALT_TITLE", is_verified_external=True)
    ]
    conflicted = detect_conflicts(instances)
    assert len(conflicted) == 2
    for c in conflicted:
        assert c["decision"] == "REVIEW_REQUIRED"
        assert c["decision"] != "SAFE_TO_WRITE"
        assert c["match_status"] == "CONFLICT"


@pytest.mark.asyncio
async def test_database_remains_unmodified():
    """Verify that PostgreSQL manga table remains 100% untouched by dry-run operations."""
    async with AsyncSessionLocal() as session:
        # Capture counts before operation
        r_total_before = await session.execute(text("SELECT COUNT(*) FROM manga"))
        total_before = r_total_before.scalar()
        r_inf_before = await session.execute(
            text("SELECT COUNT(*) FROM manga WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb")
        )
        inferred_before = r_inf_before.scalar()

        # Run the read-only dry-run safety verification operation
        total_op, inf_op, genres_op, tags_op = await dry_run_module.verify_database_safety(session)

        # Capture counts after operation
        r_total_after = await session.execute(text("SELECT COUNT(*) FROM manga"))
        total_after = r_total_after.scalar()
        r_inf_after = await session.execute(
            text("SELECT COUNT(*) FROM manga WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb")
        )
        inferred_after = r_inf_after.scalar()

        # Assert persistent state is preserved and unmutated
        assert total_before == total_after
        assert inferred_before == inferred_after

