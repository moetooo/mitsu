"""
Unit and Integration Tests for Phase 5: Controlled LLM Fallback Layer.

All LLM calls in unit tests are mocked using synthetic responses.
Zero real external API calls are made during test execution.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.enrichment.vocabulary import CANONICAL_VOCABULARY
from app.enrichment.models import InferredTag, merge_inferred_tags
from app.enrichment.rules_engine import enrich_metadata, RuleEvidence
from app.enrichment.llm_cache import LLMEnrichmentCache, compute_llm_cache_key
from app.enrichment.llm_enricher import (
    LLMEnricher,
    validate_llm_result,
    select_candidate_tags,
    LLM_ACCEPT_THRESHOLD,
    LLM_REVIEW_THRESHOLD
)


def create_mock_client(response_dict: dict):
    """Helper to generate a mock AsyncGroq client returning specified JSON dict."""
    client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(response_dict)
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    client.chat.completions.create = AsyncMock(return_value=mock_completion)
    return client


# --------------------------------------------------------------------------
# Test 1: Valid Response
# --------------------------------------------------------------------------
def test_valid_llm_response_is_accepted():
    """Test 1: Canonical tag, valid confidence, and valid evidence are accepted."""
    candidate_set = {"slow_burn", "friends_to_lovers"}
    response = {
        "tags": [
            {
                "tag": "slow_burn",
                "confidence": 0.88,
                "evidence": "Characters take years to acknowledge their mutual affection across multiple seasons."
            }
        ],
        "abstain": False
    }

    valid_tags, is_valid, errors = validate_llm_result(response, candidate_set)
    assert is_valid is True
    assert len(valid_tags) == 1
    assert valid_tags[0]["slug"] == "slow_burn"
    assert valid_tags[0]["confidence"] == 0.88
    assert "mutual affection" in valid_tags[0]["evidence"]

    mock_client = create_mock_client(response)
    enricher = LLMEnricher(enabled=True, client=mock_client)
    sample = {
        "title_english": "Distant Seasons",
        "synopsis": "Two colleagues gradually discover their mutual affection across many years of working side by side."
    }
    tags = enricher.enrich(sample, candidate_tags=["slow_burn"])
    assert len(tags) == 1
    assert tags[0].slug == "slow_burn"
    assert tags[0].provenance == "llm"
    assert tags[0].confidence == 0.88
    assert tags[0].evidence is not None


# --------------------------------------------------------------------------
# Test 2: Unknown or Non-Canonical Tag
# --------------------------------------------------------------------------
def test_unknown_or_hallucinated_tag_is_rejected():
    """Test 2: Non-canonical tags like 'super_romance' or 'cute_relationship' are discarded."""
    candidate_set = {"romance", "friends_to_lovers"}
    response = {
        "tags": [
            {
                "tag": "super_romance",
                "confidence": 0.95,
                "evidence": "Extremely romantic plot."
            },
            {
                "tag": "cute_relationship",
                "confidence": 0.90,
                "evidence": "Very cute interactions."
            },
            {
                "tag": "friends_to_lovers",
                "confidence": 0.85,
                "evidence": "Childhood companions develop romantic feelings."
            }
        ],
        "abstain": False
    }

    valid_tags, is_valid, errors = validate_llm_result(response, candidate_set)
    assert is_valid is True
    # Only friends_to_lovers is valid canonical
    assert len(valid_tags) == 1
    assert valid_tags[0]["slug"] == "friends_to_lovers"
    # Verify rejection was recorded
    assert any("super_romance" in err for err in errors)
    assert any("cute_relationship" in err for err in errors)


# --------------------------------------------------------------------------
# Test 3: Invalid Confidence
# --------------------------------------------------------------------------
def test_invalid_confidence_values_are_rejected():
    """Test 3: Confidences outside [0.0, 1.0] or non-numeric values are rejected."""
    candidate_set = {"isekai", "fantasy"}
    response = {
        "tags": [
            {"tag": "isekai", "confidence": 1.5, "evidence": "Transported to another world."},
            {"tag": "fantasy", "confidence": -0.2, "evidence": "Magic spells and monsters."},
            {"tag": "fantasy", "confidence": "high", "evidence": "String confidence."}
        ],
        "abstain": False
    }

    valid_tags, is_valid, errors = validate_llm_result(response, candidate_set)
    assert len(valid_tags) == 0
    assert len(errors) == 3


# --------------------------------------------------------------------------
# Test 4: Abstention Handling
# --------------------------------------------------------------------------
def test_abstain_returns_no_tags_gracefully():
    """Test 4: Explicit abstain=true returns empty tags and registers abstention."""
    candidate_set = {"boys_love", "girls_love"}
    response = {
        "tags": [],
        "abstain": True
    }

    valid_tags, is_valid, errors = validate_llm_result(response, candidate_set)
    assert is_valid is True
    assert len(valid_tags) == 0

    mock_client = create_mock_client(response)
    enricher = LLMEnricher(enabled=True, client=mock_client)
    tags = enricher.enrich(
        {"title_english": "Ambiguous Title", "synopsis": "A vague synopsis that lacks any gender or relationship clues whatsoever."},
        candidate_tags=["boys_love"]
    )
    assert len(tags) == 0
    assert enricher.total_abstentions == 1


# --------------------------------------------------------------------------
# Test 5: Malformed JSON
# --------------------------------------------------------------------------
def test_malformed_json_fails_safely():
    """Test 5: Malformed JSON or non-dict root returns safely without raising exceptions."""
    candidate_set = {"romance"}
    malformed_raw = "This is not json at all {broken"
    valid_tags, is_valid, errors = validate_llm_result(malformed_raw, candidate_set)
    assert is_valid is False
    assert len(valid_tags) == 0
    assert "Malformed JSON" in errors[0]


# --------------------------------------------------------------------------
# Test 6: Duplicate Tags Deduplication
# --------------------------------------------------------------------------
def test_duplicate_tags_are_deduplicated_retaining_highest_confidence():
    """Test 6: Multiple instances of the same tag slug retain the highest confidence."""
    candidate_set = {"slow_burn"}
    response = {
        "tags": [
            {"tag": "slow_burn", "confidence": 0.70, "evidence": "First mention."},
            {"tag": "slow_burn", "confidence": 0.89, "evidence": "Stronger evidence from chapter 50."}
        ],
        "abstain": False
    }

    valid_tags, is_valid, errors = validate_llm_result(response, candidate_set)
    assert len(valid_tags) == 1
    assert valid_tags[0]["slug"] == "slow_burn"
    assert valid_tags[0]["confidence"] == 0.89
    assert "chapter 50" in valid_tags[0]["evidence"]


# --------------------------------------------------------------------------
# Test 7: Hierarchy Preservation (Rule > Model > LLM)
# --------------------------------------------------------------------------
def test_existing_stronger_rule_preserves_rule_provenance():
    """Test 7: A rule prediction overrides and protects against lower-priority LLM predictions."""
    rule_tag = InferredTag.from_canonical(
        slug="romance",
        confidence=0.85,
        provenance="rule",
        source_rule="RULE-ROM-001"
    )

    llm_tag = InferredTag.from_canonical(
        slug="romance",
        confidence=0.99,  # Even with higher numeric confidence, rule provenance takes precedence
        provenance="llm",
        source_rule="LLM-llama-3.1-8b-instant",
        evidence="Obvious romantic feelings."
    )

    merged = merge_inferred_tags([rule_tag.to_dict()], [llm_tag.to_dict()])
    assert len(merged) == 1
    assert merged[0]["slug"] == "romance"
    assert merged[0]["provenance"] == "rule"
    assert merged[0]["source_rule"] == "RULE-ROM-001"


# --------------------------------------------------------------------------
# Test 8: Cache Hit Prevents Duplicate API Invocations
# --------------------------------------------------------------------------
def test_cache_hit_prevents_duplicate_api_calls():
    """Test 8: Successive calls with identical input hit cache and do not invoke LLM client."""
    response = {
        "tags": [{"tag": "friends_to_lovers", "confidence": 0.85, "evidence": "Longtime companions fall in love."}],
        "abstain": False
    }
    mock_client = create_mock_client(response)
    cache = LLMEnrichmentCache()

    enricher = LLMEnricher(enabled=True, client=mock_client, cache=cache)
    sample = {
        "title_english": "Childhood Promise",
        "synopsis": "Childhood companions promise to stay together, gradually realizing their romantic feelings over time."
    }

    # Call 1: Cache miss -> invokes client
    res1 = enricher.enrich(sample, candidate_tags=["friends_to_lovers"])
    assert len(res1) == 1
    assert mock_client.chat.completions.create.call_count == 1
    assert cache.stats["hits"] == 0
    assert cache.stats["misses"] == 1

    # Call 2: Cache hit -> zero client calls
    res2 = enricher.enrich(sample, candidate_tags=["friends_to_lovers"])
    assert len(res2) == 1
    assert res1[0].slug == res2[0].slug
    assert mock_client.chat.completions.create.call_count == 1  # Did not increase
    assert cache.stats["hits"] == 1


# --------------------------------------------------------------------------
# Test 9: LLM Disabled Setting
# --------------------------------------------------------------------------
def test_llm_disabled_bypasses_api_and_preserves_rules():
    """Test 9: When disabled, LLM is bypassed completely and rule/ML engine continues normally."""
    mock_client = create_mock_client({"tags": [{"tag": "romance", "confidence": 0.99, "evidence": "..."}], "abstain": False})
    enricher = LLMEnricher(enabled=False, client=mock_client)

    sample = {
        "title_english": "Fantasy Portal",
        "synopsis": "A boys love story where the hero is transported into another world."
    }

    res = enrich_metadata(sample, llm_enricher=enricher)
    assert mock_client.chat.completions.create.call_count == 0
    # Rule engine still functioned
    slugs = {t["slug"] for t in res.inferred_tags}
    assert "boys_love" in slugs


# --------------------------------------------------------------------------
# Test 10: API Failure Resilience
# --------------------------------------------------------------------------
def test_api_failure_does_not_break_enrichment():
    """Test 10: API exceptions/timeouts fail gracefully without crashing enrichment pipeline."""
    failing_client = MagicMock()
    failing_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("Groq 503 Service Unavailable"))

    enricher = LLMEnricher(enabled=True, client=failing_client)
    sample = {
        "title_english": "Hero Journey",
        "synopsis": "A boys love story exploring dungeons and defeating dragons."
    }

    # Pipeline should NOT raise RuntimeError
    res = enrich_metadata(sample, llm_enricher=enricher, candidate_tags=["slow_burn"])
    assert res is not None
    assert enricher.total_failures == 1
    # Deterministic rule results are still preserved intact
    assert any(t["slug"] == "boys_love" for t in res.inferred_tags)


# --------------------------------------------------------------------------
# Test 11: Idempotency
# --------------------------------------------------------------------------
def test_enrichment_idempotency():
    """Test 11: Running full enrichment twice on the same metadata yields identical outputs."""
    response = {
        "tags": [{"tag": "slow_burn", "confidence": 0.85, "evidence": "Romance unfolds slowly over many years."}],
        "abstain": False
    }
    mock_client = create_mock_client(response)
    enricher = LLMEnricher(enabled=True, client=mock_client)

    sample = {
        "title_english": "Tender Years",
        "synopsis": "A tender boys love story unfolding slowly over years between two students."
    }

    run1 = enrich_metadata(sample, llm_enricher=enricher, candidate_tags=["slow_burn"])
    run2 = enrich_metadata(sample, llm_enricher=enricher, candidate_tags=["slow_burn"])

    # Verify complete semantic idempotency (slug, confidence, provenance, source_rule, evidence)
    tags1_clean = [{k: v for k, v in t.items() if k != "created_at"} for t in run1.inferred_tags]
    tags2_clean = [{k: v for k, v in t.items() if k != "created_at"} for t in run2.inferred_tags]
    assert tags1_clean == tags2_clean
    assert len(run1.inferred_tags) == len(run2.inferred_tags)


# --------------------------------------------------------------------------
# Test 12: Candidate Selection Filtering
# --------------------------------------------------------------------------
def test_candidate_selection_excludes_already_confident_tags():
    """Test 12: Tags already inferred by rules/ML with high confidence are excluded from LLM candidates."""
    record = {
        "title_english": "Office Romance",
        "synopsis": "Two colleagues work together in an office and secretly develop feelings."
    }

    existing_rule_tag = InferredTag.from_canonical(
        slug="romance",
        confidence=0.90,
        provenance="rule"
    )

    ml_predictions = [
        {"slug": "workplace", "confidence": 0.85, "tier": "high", "accepted": True},
        {"slug": "slow_burn", "confidence": 0.55, "tier": "medium", "accepted": False}
    ]

    candidates = select_candidate_tags(
        record=record,
        existing_rule_tags=[existing_rule_tag],
        ml_predictions=ml_predictions
    )

    # romance and workplace must NOT be in candidates (already confident)
    assert "romance" not in candidates
    assert "workplace" not in candidates
    # slow_burn (uncertain ML prediction) SHOULD be in candidates
    assert "slow_burn" in candidates


# --------------------------------------------------------------------------
# Test 13: Tag-Specific Thresholds
# --------------------------------------------------------------------------
def test_tag_specific_thresholds_logic():
    """Test 13: Broad tags require higher confidence, subtle tags don't."""
    candidate_set = {"comedy", "action", "slow_burn", "dungeon_gate"} 
    response = {
        "tags": [
            {
                "tag": "comedy",
                "confidence": 0.84, # rejected (threshold 0.90)
                "evidence": "Humorous elements present."
            },
            {
                "tag": "action",
                "confidence": 0.92, # accepted (threshold 0.90)
                "evidence": "Lots of action scenes."
            },
            {
                "tag": "slow_burn",
                "confidence": 0.82, # accepted (threshold 0.80)
                "evidence": "Relationship develops over years."
            },
            {
                "tag": "dungeon_gate",
                "confidence": 0.85, # accepted (default threshold 0.80)
                "evidence": "Hunters and gates appear."
            }
        ],
        "abstain": False
    }
    
    mock_client = create_mock_client(response)
    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    enricher = LLMEnricher(enabled=True, client=mock_client, cache=mock_cache)
    sample = {"title_english": "Test", "synopsis": "This is a sufficiently long synopsis for testing tag thresholds to ensure it passes the length check."}
    
    tags = enricher.enrich(sample, candidate_tags=list(candidate_set))
    
    # Expected accepted: action, slow_burn, dungeon_gate
    accepted_slugs = {t.slug for t in tags}
    assert "action" in accepted_slugs
    assert "slow_burn" in accepted_slugs
    assert "dungeon_gate" in accepted_slugs
    assert "comedy" not in accepted_slugs


# --------------------------------------------------------------------------
# Test 14: ML Accepted Exclusion
# --------------------------------------------------------------------------
def test_candidate_selection_ml_accepted():
    """Test 14: ML accepted -> candidate excluded -> LLM not called for that tag."""
    record = {"title_english": "Test", "synopsis": "Test"}
    ml_predictions = [
        {"slug": "survival", "confidence": 0.72, "accepted": True}, # accepted, so exclude
        {"slug": "magic", "confidence": 0.65, "accepted": False} # not accepted, include
    ]
    candidates = select_candidate_tags(record, ml_predictions=ml_predictions)
    assert "survival" not in candidates
    assert "magic" in candidates
