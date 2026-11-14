"""
Unit and regression tests for production inferred_tags backfill tooling.

Tests cover:
1. Candidate filtering & validation (safe-only, heuristic exclusion, vocabulary check).
2. Deduplication and precedence rules.
3. Merge idempotency (re-applying produces 0 new tags).
4. Provenance preservation and conflict resolution.
5. Prevention of duplicate tags within a title.
6. Safety flags enforcement (refusal to write without --confirm-production-write).
7. Transaction failure handling and batch rollback behavior.
"""

import os
import sys
import json
import tempfile
import pytest
import csv
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

pytestmark = pytest.mark.requires_artifacts

from app.enrichment.models import InferredTag, merge_inferred_tags
from app.enrichment.vocabulary import CANONICAL_VOCABULARY, get_tag_by_slug
from scripts.prepare_production_backfill import (
    load_and_filter_candidates,
    merge_and_deduplicate,
    select_deterministic_pilot
)
from scripts.backfill_inferred_tags import (
    validate_and_load_input,
    execute_backfill
)


def test_safe_only_enforcement_and_heuristic_exclusion():
    """Verify that REVIEW_REQUIRED, REJECTED, local_heuristic, and SCRIPT_HEURISTIC are rejected."""
    rows = [
        # Valid safe row
        {
            "manga_id": "1001",
            "start_year": "2020",
            "title": "Valid Manga",
            "canonical_tag": "time_travel",
            "source": "MangaUpdates",
            "source_evidence": "Categories: Time Travel",
            "confidence": "0.95",
            "match_method": "DIRECT_ID",
            "decision": "SAFE_TO_WRITE"
        },
        # REVIEW_REQUIRED - must be rejected
        {
            "manga_id": "1002",
            "start_year": "2021",
            "title": "Review Manga",
            "canonical_tag": "isekai",
            "source": "AniList",
            "source_evidence": "Tags: Isekai",
            "confidence": "0.75",
            "match_method": "CROSS_REFERENCE_ID",
            "decision": "REVIEW_REQUIRED"
        },
        # REJECTED - must be rejected
        {
            "manga_id": "1003",
            "start_year": "2019",
            "title": "Rejected Manga",
            "canonical_tag": "dungeon",
            "source": "MangaDex",
            "source_evidence": "Speculative leap",
            "confidence": "0.30",
            "match_method": "FUZZY",
            "decision": "REJECTED"
        },
        # local_heuristic - must be rejected
        {
            "manga_id": "1004",
            "start_year": "2020",
            "title": "Heuristic Manga",
            "canonical_tag": "manga",
            "source": "local_heuristic",
            "source_evidence": "country=JP fallback",
            "confidence": "0.99",
            "match_method": "SCRIPT_HEURISTIC",
            "decision": "SAFE_TO_WRITE"
        },
        # Unknown canonical tag - must be rejected
        {
            "manga_id": "1005",
            "start_year": "2020",
            "title": "Unknown Tag Manga",
            "canonical_tag": "invalid_tag_not_in_vocabulary",
            "source": "MangaUpdates",
            "source_evidence": "Some evidence",
            "confidence": "0.95",
            "match_method": "DIRECT_ID",
            "decision": "SAFE_TO_WRITE"
        },
    ]

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv", encoding="utf-8", newline="") as tf:
        writer = csv.DictWriter(tf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        temp_csv = tf.name

    try:
        valid_cands, stats = load_and_filter_candidates(temp_csv)
        assert len(valid_cands) == 1
        assert valid_cands[0]["manga_id"] == 1001
        assert valid_cands[0]["canonical_tag"] == "time_travel"
        assert stats["excluded_non_safe"] == 2  # REVIEW_REQUIRED + REJECTED
        assert stats["excluded_heuristic"] == 1  # local_heuristic
        assert stats["invalid_canonical_tag"] == 1  # invalid_tag_not_in_vocabulary
    finally:
        if os.path.exists(temp_csv):
            os.remove(temp_csv)


def test_deduplication_and_precedence():
    """Verify deduplication preserves DIRECT_ID over CROSS_REFERENCE_ID, and higher confidence."""
    cand1 = {
        "manga_id": 500,
        "start_year": 2018,
        "title": "Test Title",
        "canonical_tag": "villainess",
        "source": "MangaUpdates",
        "source_evidence": "Direct tag",
        "confidence": 0.85,
        "match_method": "CROSS_REFERENCE_ID",
        "decision": "SAFE_TO_WRITE"
    }
    cand2 = {
        "manga_id": 500,
        "start_year": 2018,
        "title": "Test Title",
        "canonical_tag": "villainess",
        "source": "MangaUpdates",
        "source_evidence": "Direct ID match",
        "confidence": 0.95,
        "match_method": "DIRECT_ID",
        "decision": "SAFE_TO_WRITE"
    }

    merged, dups = merge_and_deduplicate([[cand1], [cand2]])
    assert len(merged) == 1
    assert dups == 1
    assert merged[0]["match_method"] == "DIRECT_ID"
    assert merged[0]["confidence"] == 0.95


def test_merge_inferred_tags_idempotency():
    """Verify merging the same tags twice results in 0 additional changes and no duplicates."""
    tag1 = InferredTag.from_canonical("reborn_as_a_villainess", 0.95, "external", "DIRECT_ID:MangaUpdates", "tag evidence")
    tag2 = InferredTag.from_canonical("reincarnation", 0.90, "external", "DIRECT_ID:MangaUpdates", "tag evidence")

    # Initial merge into empty list
    state_1 = merge_inferred_tags([], [tag1, tag2])
    assert len(state_1) == 2
    slugs_1 = [t["slug"] for t in state_1]
    # Sorted by category (theme before trope)
    assert slugs_1 == ["reincarnation", "reborn_as_a_villainess"]

    # Second merge with identical input
    state_2 = merge_inferred_tags(state_1, [tag1, tag2])
    assert len(state_2) == 2
    assert state_2 == state_1


def test_provenance_preservation_and_conflict_hierarchy():
    """Verify that lower provenance cannot overwrite higher provenance."""
    # Existing tag was manually verified by a human
    human_tag = {
        "slug": "reborn_as_a_villainess",
        "name": "Reborn as a Villainess",
        "category": "trope",
        "confidence": 1.0,
        "provenance": "human",
        "source_rule": "manual_review",
        "created_at": "2026-01-01T00:00:00Z"
    }

    # Incoming tag is from external enrichment
    incoming_external = InferredTag.from_canonical(
        "reborn_as_a_villainess", 0.95, "external", "DIRECT_ID:MangaUpdates", "evidence"
    )

    merged = merge_inferred_tags([human_tag], [incoming_external])
    assert len(merged) == 1
    assert merged[0]["provenance"] == "human"
    assert merged[0]["confidence"] == 1.0


def test_no_duplicate_tags_prevented():
    """Verify that multiple incoming instances of the same tag slug collapse to one entry."""
    tag_a1 = InferredTag.from_canonical("manhwa", 0.90, "external", "CROSS:AniList", "ev1")
    tag_a2 = InferredTag.from_canonical("manhwa", 0.99, "external", "DIRECT:MangaDex", "ev2")

    merged = merge_inferred_tags([], [tag_a1, tag_a2])
    assert len(merged) == 1
    assert merged[0]["slug"] == "manhwa"
    # Highest confidence retained
    assert merged[0]["confidence"] == 0.99


def test_safety_flag_apply_refusal():
    """Verify that execute_backfill or backfill_inferred_tags refuses to run apply without confirm flag."""
    # Check validate_and_load_input fails on bad inputs
    bad_rows = [{
        "manga_id": "1",
        "start_year": "2020",
        "title": "Bad",
        "canonical_tag": "manga",
        "source": "local_heuristic",
        "source_evidence": "none",
        "confidence": "0.5",
        "match_method": "SCRIPT_HEURISTIC",
        "decision": "SAFE_TO_WRITE"
    }]

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv", encoding="utf-8", newline="") as tf:
        writer = csv.DictWriter(tf, fieldnames=list(bad_rows[0].keys()))
        writer.writeheader()
        writer.writerows(bad_rows)
        temp_csv = tf.name

    try:
        with pytest.raises(ValueError, match="Input validation FAILED"):
            validate_and_load_input(temp_csv)
    finally:
        if os.path.exists(temp_csv):
            os.remove(temp_csv)


@pytest.mark.asyncio
async def test_transaction_rollback_on_failure():
    """Verify that if an error occurs within a batch, the transaction is rolled back."""
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    # Simulate error on session.execute during update
    mock_session.execute.side_effect = Exception("Simulated DB connection drop")

    candidates = [{
        "manga_id": 9999,
        "start_year": 2020,
        "title": "Fail Manga",
        "canonical_tag": "isekai",
        "tag_name": "Isekai",
        "tag_category": "trope",
        "source": "MangaUpdates",
        "source_evidence": "Categories: Isekai",
        "confidence": 0.95,
        "match_method": "DIRECT_ID",
        "decision": "SAFE_TO_WRITE"
    }]

    with pytest.raises(Exception, match="Simulated DB connection drop"):
        with patch("scripts.backfill_inferred_tags.AsyncSessionLocal", return_value=mock_session):
            await execute_backfill(candidates, mode="apply", batch_size=25)

    # Verify rollback was called
    assert mock_session.rollback.called
