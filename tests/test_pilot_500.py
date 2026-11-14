"""
Tests for Phase 6 500-Title Pilot infrastructure and dataset sampling.
"""

import pytest
import os
import json

# The sampling script lives in the gitignored scripts/ directory, so both the
# script and the artifact it produces are optional: skip explicitly instead of
# swallowing the ImportError and asserting against an empty list.
sample_pilot = pytest.importorskip(
    "scripts.sample_pilot_500",
    reason="scripts/ is not tracked; the pilot sampler is a local artifact",
)
STRATA_DEFINITIONS = sample_pilot.STRATA_DEFINITIONS


def test_pilot_500_ids_file_exists_and_valid():
    """Verify scratch/pilot_500_ids.json exists, contains 500 unique IDs, and has strata breakdown."""
    filepath = os.path.join("scratch", "pilot_500_ids.json")
    if not os.path.exists(filepath):
        pytest.skip(f"{filepath} is a local pilot artifact and is not tracked")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data["metadata"]
    assert meta["total_records"] == 500
    assert meta["unique_ids_count"] == 500

    records = data["records"]
    assert len(records) == 500
    ids = [r["id"] for r in records]
    assert len(set(ids)) == 500

    # Verify strata coverage
    breakdown = meta["stratum_breakdown"]
    assert len(breakdown) >= 15
    assert breakdown.get("boys_love", 0) > 0
    assert breakdown.get("girls_love", 0) > 0
    assert breakdown.get("slow_burn", 0) > 0
    assert breakdown.get("action_and_fantasy", 0) > 0
    assert breakdown.get("manhwa_webtoon", 0) > 0


def test_strata_definitions_have_valid_sql_and_action_fantasy():
    """Verify all strata definitions are deterministic and action_fantasy uses actual DB genres."""
    for name, query, count in STRATA_DEFINITIONS:
        assert "ORDER BY id ASC" in query, f"Stratum {name} lacks deterministic ORDER BY id ASC"
        assert count > 0

    # action_and_fantasy must use ARRAY['Action', 'Fantasy']
    af_stratum = next((s for s in STRATA_DEFINITIONS if s[0] == "action_and_fantasy"), None)
    assert af_stratum is not None
    assert "genres @> ARRAY['Action', 'Fantasy']" in af_stratum[1]
