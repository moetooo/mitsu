"""
TARGETED TESTS FOR CATEGORY-AWARE INFERRED_TAG RETRIEVAL INTEGRATION.

Covers Section 9 requirements:
- Test A: No inferred tags -> tag_alignment = 0, existing ranking unchanged.
- Test B: Shared relationship tag -> relationship overlap > format-only overlap.
- Test C: Shared trope vs shared format -> trope receives stronger boost.
- Test D: Format-only overlap -> small boost.
- Test E: No candidate metadata -> candidate remains eligible.
- Test F: Existing filters still work.
- Test G: Ranking remains deterministic.
- Test H: No SQL N+1 behavior introduced.
"""

import pytest
import os
import sys
from typing import List, Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.format import build_format_sql_condition
from app.services.query_filters import build_genre_sql_condition
from app.services.retrieval import retrieve_similar_manga
from app.services.tag_alignment import (
    DEFAULT_CATEGORY_WEIGHTS,
    build_tag_alignment_sql,
    compute_category_aware_tag_alignment,
)
from app.models import RecommendFilters


def test_a_no_inferred_tags_ranking_unchanged():
    """Test A: If query or candidate has no inferred tags, alignment is 0.0 and ranking is unchanged."""
    # Query with no tags
    align_empty_query = compute_category_aware_tag_alignment(
        query_tags=[],
        candidate_tags=[{"slug": "manga", "category": "format"}]
    )
    assert align_empty_query == 0.0

    # Candidate with no tags
    align_empty_cand = compute_category_aware_tag_alignment(
        query_tags=[{"slug": "childhood_friends", "category": "relationship"}],
        candidate_tags=[]
    )
    assert align_empty_cand == 0.0

    # SQL builder produces no boost clause
    tag_select, tag_boost_sql, params = build_tag_alignment_sql([])
    assert tag_select == "0.0 as tag_alignment,"
    assert tag_boost_sql == ""
    assert params == {}


def test_b_shared_relationship_vs_format():
    """Test B: Shared relationship tag produces significantly higher overlap than format-only overlap."""
    query_tags = [
        {"slug": "childhood_friends", "category": "relationship"},
        {"slug": "manga", "category": "format"}
    ]

    cand_relationship = [{"slug": "childhood_friends", "category": "relationship"}]
    cand_format = [{"slug": "manga", "category": "format"}]

    align_rel = compute_category_aware_tag_alignment(query_tags, cand_relationship)
    align_fmt = compute_category_aware_tag_alignment(query_tags, cand_format)

    # Relationship weight is 1.00 vs Format weight 0.15
    assert align_rel > align_fmt
    # rel: 1.00 / 1.15 =~ 0.8696, fmt: 0.15 / 1.15 =~ 0.1304
    assert round(align_rel, 3) == 0.870
    assert round(align_fmt, 3) == 0.130
    assert align_rel > 6.0 * align_fmt


def test_c_shared_trope_vs_format():
    """Test C: Shared trope tag receives stronger boost than format tag."""
    query_tags = [
        {"slug": "overpowered_protagonist", "category": "trope"},
        {"slug": "manhwa", "category": "format"}
    ]

    cand_trope = [{"slug": "overpowered_protagonist", "category": "trope"}]
    cand_fmt = [{"slug": "manhwa", "category": "format"}]

    align_trope = compute_category_aware_tag_alignment(query_tags, cand_trope)
    align_fmt = compute_category_aware_tag_alignment(query_tags, cand_fmt)

    # Trope weight is 1.00 vs Format weight 0.15
    assert align_trope > align_fmt
    assert align_trope > 6.0 * align_fmt


def test_d_format_only_overlap_small_boost():
    """Test D: Format-only overlap contributes a small, clamped boost."""
    query_tags = [
        {"slug": "childhood_friends", "category": "relationship"},
        {"slug": "slow_burn", "category": "relationship"},
        {"slug": "manga", "category": "format"}
    ]

    # Candidate only shares 'manga'
    cand_format_only = [{"slug": "manga", "category": "format"}]
    align_fmt = compute_category_aware_tag_alignment(query_tags, cand_format_only)

    # Total query weight = 1.0 + 1.0 + 0.15 = 2.15. Format alignment = 0.15 / 2.15 =~ 0.0698
    assert align_fmt < 0.10
    boost_val = 0.10 * align_fmt
    assert boost_val < 0.01  # Less than 1% boost on hybrid score


def test_e_candidate_no_metadata_remains_eligible():
    """Test E: A candidate with null/empty inferred tags receives 0.0 alignment but is not penalized or filtered."""
    query_tags = [{"slug": "isekai", "category": "theme"}]
    cand_no_meta = []

    alignment = compute_category_aware_tag_alignment(query_tags, cand_no_meta)
    assert alignment == 0.0

    # In SQL builder, NULL inferred_tags evaluate to 0.0 via ELSE 0.0, keeping candidate eligible
    tag_select, tag_boost_sql, params = build_tag_alignment_sql(query_tags, tag_boost=0.10)
    assert "ELSE 0.0 END" in tag_select
    assert params["tag_boost"] == 0.10


def test_f_existing_filters_still_work():
    """Test F: Format and genre filter conditions continue to work.

    The format filter reads the stored column now (ARCH-05); the manhwa/manhua
    distinction is decided when the row is written, so the filter no longer has
    to re-derive it from inferred_tags on every query.
    """
    manhwa_sql = build_format_sql_condition(["manhwa"])
    assert manhwa_sql == "(format_type = 'MANHWA')"

    # Genre SQL condition is unchanged in shape, but every value is bound (SVC-10).
    genre_params: dict = {}
    genre_sql = build_genre_sql_condition(["Action"], genre_params)
    assert "genres @> CAST(:genre_0_arr AS text[])" in genre_sql
    assert "tags @> CAST(:genre_0_tag AS jsonb)" in genre_sql
    assert genre_params["genre_0_arr"] == ["Action"]


def test_g_deterministic_ranking():
    """Test G: Category-aware tag alignment computation is 100% deterministic."""
    query_tags = [
        {"slug": "childhood_friends", "category": "relationship"},
        {"slug": "underdog", "category": "theme"},
        {"slug": "manga", "category": "format"}
    ]
    cand_tags = [
        {"slug": "underdog", "category": "theme"},
        {"slug": "manga", "category": "format"}
    ]

    res1 = compute_category_aware_tag_alignment(query_tags, cand_tags)
    res2 = compute_category_aware_tag_alignment(query_tags, cand_tags)
    res3 = compute_category_aware_tag_alignment(query_tags, cand_tags)

    assert res1 == res2 == res3
    # theme (0.90) + format (0.15) = 1.05 / (1.00 + 0.90 + 0.15 = 2.05) =~ 0.5122
    assert round(res1, 4) == 0.5122


@pytest.mark.asyncio
async def test_h_no_sql_n_plus_one():
    """Test H: retrieve_similar_manga executes exactly ONE SQL query for candidate retrieval and scoring."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session.execute.return_value = mock_result

    dummy_emb = [0.0] * 384
    query_tags = [{"slug": "childhood_friends", "category": "relationship"}]

    await retrieve_similar_manga(
        session=mock_session,
        query_embedding=dummy_emb,
        query_inferred_tags=query_tags,
        enable_inferred_tags=True,
        limit=10
    )

    # Two statements: the transaction-local ANN settings, then the single
    # candidate query. What this guard exists for is that scoring does not run
    # one query per candidate, so the count must stay constant as the candidate
    # list grows.
    assert mock_session.execute.call_count == 2, (
        f"expected 1 settings + 1 candidate query, got {mock_session.execute.call_count}"
    )
    settings_sql = str(mock_session.execute.call_args_list[0][0][0])
    assert "set_config" in settings_sql, (
        "the first statement must apply hnsw settings; without it the ANN scan is "
        "capped at ef_search and returns fewer rows than requested"
    )
    sql_text = str(mock_session.execute.call_args[0][0])
    assert "tag_alignment" in sql_text
    assert "q_tag_0" in mock_session.execute.call_args[0][1]
