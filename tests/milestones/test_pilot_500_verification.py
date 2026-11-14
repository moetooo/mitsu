import os
import json
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "scratch"))

pytestmark = pytest.mark.requires_artifacts

# scratch/ is not tracked, so the verification script is a local artifact: skip
# with a reason instead of swallowing the ImportError and failing with NameError.
verify_pilot_500 = pytest.importorskip(
    "verify_pilot_500",
    reason="scratch/verify_pilot_500.py is a local artifact and is not tracked",
)
from verify_pilot_500 import (  # noqa: E402
    parse_verifier_response,
    evaluate_decision,
    call_verifier_api,
    verify_db_safety_before,
    verify_db_safety_after,
)

def test_valid_verifier_json():
    raw = '{"decision": "AUTO_ACCEPT", "confidence": 0.95, "evidence_quote": "They fell in love", "reason": "Clear", "definition_match": true, "original_evidence_supported": true}'
    parsed, is_valid, errs = parse_verifier_response(raw)
    assert is_valid
    assert parsed["decision"] == "AUTO_ACCEPT"

def test_invalid_json():
    raw = '{"decision": "AUTO_ACCEPT", oops}'
    parsed, is_valid, errs = parse_verifier_response(raw)
    assert not is_valid
    assert len(errs) > 0

def test_invalid_decision():
    raw = '{"decision": "MAYBE", "confidence": 0.95, "evidence_quote": "They fell in love", "reason": "Clear", "definition_match": true, "original_evidence_supported": true}'
    parsed, is_valid, errs = parse_verifier_response(raw)
    assert not is_valid
    assert "Invalid decision" in errs[0]

def test_invalid_confidence():
    raw = '{"decision": "AUTO_ACCEPT", "confidence": 1.5, "evidence_quote": "They fell in love", "reason": "Clear", "definition_match": true, "original_evidence_supported": true}'
    parsed, is_valid, errs = parse_verifier_response(raw)
    assert not is_valid

def test_missing_evidence():
    raw = '{"decision": "AUTO_ACCEPT", "confidence": 0.95, "evidence_quote": "", "reason": "Clear", "definition_match": true, "original_evidence_supported": true}'
    parsed, is_valid, errs = parse_verifier_response(raw)
    assert not is_valid

def test_auto_accept_conditions():
    decision, status = evaluate_decision("AUTO_ACCEPT", 0.89, "quote", True, True)
    assert status == "MANUAL_REVIEW"
    
    decision, status = evaluate_decision("AUTO_ACCEPT", 0.95, "quote", False, True)
    assert status == "MANUAL_REVIEW"
    
    decision, status = evaluate_decision("AUTO_ACCEPT", 0.95, "quote", True, False)
    assert status == "MANUAL_REVIEW"
    
    decision, status = evaluate_decision("AUTO_ACCEPT", 0.95, "quote", True, True)
    assert status == "AUTO_ACCEPT"

def test_auto_reject_conditions():
    decision, status = evaluate_decision("AUTO_REJECT", 0.95, "quote", True, True)
    assert status == "MANUAL_REVIEW"
    
    decision, status = evaluate_decision("AUTO_REJECT", 0.95, "quote", False, True)
    assert status == "AUTO_REJECT"

def test_ambiguous_evidence():
    decision, status = evaluate_decision("MANUAL_REVIEW", 0.5, "quote", True, True)
    assert status == "MANUAL_REVIEW"

@patch('verify_pilot_500.make_api_call')
def test_cache_hit_causes_zero_api_calls(mock_make_api_call):
    cache = {"some_key": {"response": '{"decision": "AUTO_ACCEPT", "confidence": 0.95, "evidence_quote": "They fell in love", "reason": "Clear", "definition_match": true, "original_evidence_supported": true}'}}
    res = call_verifier_api("some_key", "prompt", cache)
    assert mock_make_api_call.call_count == 0
    assert res is not None

@patch('verify_pilot_500.make_api_call')
def test_api_failure_becomes_verification_error(mock_make_api_call):
    mock_make_api_call.side_effect = Exception("API Down")
    cache = {}
    res = call_verifier_api("some_key", "prompt", cache)
    assert res is None 

def test_db_safety_check_accepts_unchanged_counts():
    """The safety check is silent when the two snapshots agree (QA-12)."""
    verify_db_safety_after(95255, 120, 95255, 120)


def test_db_safety_check_rejects_a_changed_row_count():
    """A row added or removed between snapshots must raise, not pass quietly."""
    with pytest.raises(AssertionError, match="manga count changed"):
        verify_db_safety_after(95255, 120, 95256, 120)


def test_db_safety_check_rejects_a_changed_inferred_tag_count():
    """A verified record whose inferred_tags appeared/disappeared must raise."""
    with pytest.raises(AssertionError, match="inferred_tags count changed"):
        verify_db_safety_after(95255, 120, 95255, 121)

