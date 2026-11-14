"""
Unit and Integration Tests for Phase 2 Deterministic Rule-Based Tag Enrichment.
"""

import copy
import pytest
from app.enrichment import (
    CANONICAL_VOCABULARY,
    RULES,
    EnrichmentRule,
    enrich_metadata,
)
from app.enrichment.models import InferredTag


def test_explicit_bl_evidence_infers_boys_love():
    """Test 1: Explicit BL in genres/tags/synopsis infers canonical 'boys_love'."""
    # Via raw genre
    record_genre = {"genres": ["Romance", "Boys' Love"], "synopsis": "A lovely story."}
    res_genre = enrich_metadata(record_genre)
    slugs = [t["slug"] for t in res_genre.inferred_tags]
    assert "boys_love" in slugs
    bl_tag = next(t for t in res_genre.inferred_tags if t["slug"] == "boys_love")
    assert bl_tag["provenance"] == "rule"
    assert bl_tag["source_rule"] == "RULE-BL-001"
    assert bl_tag["confidence"] >= 0.95

    # Via synopsis multi-word romance
    record_synopsis = {
        "genres": ["Romance"],
        "synopsis": "Two male classmates gradually fall in love during their summer break."
    }
    res_synopsis = enrich_metadata(record_synopsis)
    slugs_synopsis = [t["slug"] for t in res_synopsis.inferred_tags]
    assert "boys_love" in slugs_synopsis


def test_explicit_gl_evidence_infers_girls_love():
    """Test 2: Explicit GL in genres/tags/synopsis infers canonical 'girls_love'."""
    # Via raw tag
    record_tag = {
        "genres": ["Romance"],
        "tags": [{"name": "Yuri", "rank": 90}],
        "synopsis": "A delicate story of two students."
    }
    res_tag = enrich_metadata(record_tag)
    slugs = [t["slug"] for t in res_tag.inferred_tags]
    assert "girls_love" in slugs
    gl_tag = next(t for t in res_tag.inferred_tags if t["slug"] == "girls_love")
    assert gl_tag["provenance"] == "rule"
    assert gl_tag["source_rule"] == "RULE-GL-001"

    # Via synopsis
    record_syn = {
        "genres": ["Romance"],
        "synopsis": "Two female students fall in love after joining the music club together."
    }
    res_syn = enrich_metadata(record_syn)
    slugs_syn = [t["slug"] for t in res_syn.inferred_tags]
    assert "girls_love" in slugs_syn


def test_school_evidence_infers_school_life():
    """Test 3: School environment patterns infer 'school_life'."""
    record = {
        "genres": ["Comedy"],
        "synopsis": "He is an ordinary high school student who joins the student council."
    }
    res = enrich_metadata(record)
    slugs = [t["slug"] for t in res.inferred_tags]
    assert "school_life" in slugs
    tag = next(t for t in res.inferred_tags if t["slug"] == "school_life")
    assert tag["provenance"] == "rule"
    assert tag["category"] == "setting"
    assert tag["confidence"] >= 0.85


def test_strong_romance_evidence_infers_romance():
    """Test 4: Strong romantic multi-word phrases infer 'romance'."""
    record = {
        "genres": ["Drama"],
        "synopsis": "After years of separation, they finally confess their feelings and fall in love."
    }
    res = enrich_metadata(record)
    slugs = [t["slug"] for t in res.inferred_tags]
    assert "romance" in slugs
    tag = next(t for t in res.inferred_tags if t["slug"] == "romance")
    assert tag["provenance"] == "rule"
    assert tag["category"] == "genre"


def test_multiple_pieces_of_evidence_combine_correctly():
    """Test 5: Multiple distinct themes, tropes, and settings are inferred simultaneously."""
    record = {
        "title_english": "The Villainess Regresses in High School",
        "genres": ["Drama"],
        "synopsis": "She was reborn as a villainess, but when tragedy struck, time rewound and she regressed to her past self as a high school student, gradually falling in love with her childhood friend."
    }
    res = enrich_metadata(record)
    slugs = {t["slug"] for t in res.inferred_tags}

    # Should detect villainess, regression, school_life, childhood_friends, slow_burn, and romance
    assert "reborn_as_a_villainess" in slugs
    assert "regression" in slugs
    assert "school_life" in slugs
    assert "childhood_friends" in slugs
    assert "slow_burn" in slugs
    assert "romance" in slugs


def test_ambiguous_keyword_does_not_cause_false_positive():
    """Test 6: Ambiguous single words ('love', 'school') do NOT trigger false positives."""
    # Case A: 'love' in non-romantic context ("he loves video games / martial arts")
    record_love = {
        "title_english": "Gamer Guy",
        "genres": ["Action"],
        "synopsis": "He loves video games and loves eating ramen every single day with his team."
    }
    res_love = enrich_metadata(record_love)
    slugs_love = [t["slug"] for t in res_love.inferred_tags]
    assert "romance" not in slugs_love
    assert "boys_love" not in slugs_love
    assert "girls_love" not in slugs_love

    # Case B: 'school' in non-academic context ("old school", "school of magic", "school of thought")
    record_school = {
        "title_english": "Sorcery Master",
        "genres": ["Fantasy"],
        "synopsis": "He studies the ancient school of magic and defeats dark sorcerers with old-school tactics."
    }
    res_school = enrich_metadata(record_school)
    slugs_school = [t["slug"] for t in res_school.inferred_tags]
    assert "school_life" not in slugs_school

    # Case C: incidental "doctor" should not infer unrelated medical tags
    record_doc = {
        "title_english": "The Dark Knight",
        "genres": ["Action"],
        "synopsis": "A mysterious doctor briefly treated his wounds before disappearing into the night."
    }
    res_doc = enrich_metadata(record_doc)
    assert len(res_doc.inferred_tags) == 0


def test_unknown_or_non_canonical_tags_are_never_generated():
    """Test 7: Every single inferred tag must strictly match CANONICAL_VOCABULARY."""
    for rule in RULES:
        assert rule.target_slug in CANONICAL_VOCABULARY, f"Rule {rule.rule_id} targets non-canonical slug {rule.target_slug}"

    record = {
        "synopsis": "A high school student summoned to another world with a status window to fight monsters."
    }
    res = enrich_metadata(record)
    for tag in res.inferred_tags:
        slug = tag["slug"]
        assert slug in CANONICAL_VOCABULARY
        assert CANONICAL_VOCABULARY[slug].name == tag["name"]
        assert CANONICAL_VOCABULARY[slug].category.value == tag["category"]


def test_rule_provenance_and_source_rule_are_properly_populated():
    """Test 8 & 9: All rule-inferred tags have provenance='rule' and non-empty source_rule."""
    record = {
        "genres": ["Action"],
        "tags": [{"name": "Murim", "rank": 95}],
        "synopsis": "He awoke in another world with a mysterious status window."
    }
    res = enrich_metadata(record)
    assert len(res.inferred_tags) > 0
    for tag in res.inferred_tags:
        assert tag["provenance"] == "rule"
        assert tag["source_rule"] is not None
        assert tag["source_rule"].startswith("RULE-")


def test_confidence_is_strictly_between_zero_and_one():
    """Test 10: Inferred tag confidences must be between 0.0 and 1.0."""
    record = {
        "genres": ["Romance", "Boys Love"],
        "synopsis": "High school students fall in love in a slow burn romance."
    }
    res = enrich_metadata(record)
    assert len(res.inferred_tags) > 0
    for tag in res.inferred_tags:
        assert 0.0 <= tag["confidence"] <= 1.0


def test_existing_stronger_inferred_tags_are_not_downgraded():
    """Test 11: Human or higher-confidence tags are preserved over weaker rule results."""
    # Pre-existing human tag with confidence 1.0
    existing_tags = [
        {
            "slug": "boys_love",
            "name": "Boys' Love",
            "category": "theme",
            "confidence": 1.0,
            "provenance": "human",
            "source_rule": "HUMAN-VERIFIED",
            "created_at": "2026-01-01T00:00:00Z"
        }
    ]

    record = {
        "synopsis": "Two boys fall in love in a male-male romance.",
        "inferred_tags": existing_tags
    }

    res = enrich_metadata(record)
    bl_tag = next(t for t in res.inferred_tags if t["slug"] == "boys_love")
    # Must preserve provenance 'human' and confidence 1.0
    assert bl_tag["provenance"] == "human"
    assert bl_tag["confidence"] == 1.0
    assert bl_tag["source_rule"] == "HUMAN-VERIFIED"


def test_raw_genres_and_tags_remain_unchanged():
    """Test 12: enrich_metadata does not mutate raw genres, tags, titles, or input dict."""
    original_record = {
        "title_romaji": "Original Title",
        "genres": ["Action", "Adventure"],
        "tags": [{"name": "Swordplay", "rank": 85}],
        "synopsis": "A swordsman travels back in time.",
        "alternative_titles": ["Alt 1"]
    }
    # Deep copy for immutability comparison
    copy_record = copy.deepcopy(original_record)

    res = enrich_metadata(original_record)

    assert original_record == copy_record
    assert original_record["genres"] == ["Action", "Adventure"]
    assert original_record["tags"] == [{"name": "Swordplay", "rank": 85}]
    assert original_record["synopsis"] == "A swordsman travels back in time."
    assert "time_travel" in [t["slug"] for t in res.inferred_tags]


def test_determinism_same_input_produces_identical_output():
    """Test 13: Determinism - Running enrich_metadata twice on identical input produces exact same output."""
    record = {
        "title_english": "Solo Gate Hunter",
        "genres": ["Action", "Fantasy"],
        "tags": [{"name": "Hunter", "rank": 80}],
        "synopsis": "Mysterious gates appeared and he awakened as a hunter with a status window."
    }

    res1 = enrich_metadata(record)
    res2 = enrich_metadata(record)

    def strip_timestamps(d):
        return {
            "inferred_tags": [{k: v for k, v in t.items() if k != "created_at"} for t in d["inferred_tags"]],
            "new_inferred_tags": [{k: v for k, v in t.items() if k != "created_at"} for t in d["new_inferred_tags"]],
            "evidences": d["evidences"]
        }

    assert strip_timestamps(res1.to_dict()) == strip_timestamps(res2.to_dict())


def test_empty_or_minimal_metadata_does_not_crash():
    """Test 14: Empty, None, or minimal inputs return safely without crashing."""
    assert enrich_metadata({}).inferred_tags == []
    assert enrich_metadata({"synopsis": ""}).inferred_tags == []
    assert enrich_metadata({"genres": None, "tags": None, "synopsis": None}).inferred_tags == []


def test_realistic_manga_synopsis_produces_expected_tags():
    """Test 15: Realistic multifaceted synopsis infers all expected canonical tags."""
    # Synopsis modeled after a popular regression/gate hunter manhwa
    record = {
        "title_english": "Return of the S-Rank Hunter",
        "title_romaji": "S-Geup Hunterui Gwihwan",
        "genres": ["Action", "Fantasy"],
        "tags": [{"name": "Manhwa", "rank": 99}],
        "synopsis": (
            "Ten years ago, mysterious gates appeared throughout modern society, spawning monstrous beasts. "
            "Jin-Woo was merely an E-rank hunter until he was betrayed and left for dead in a double dungeon. "
            "At the verge of death, time rewound and he regressed to the past with a unique status window that allows him to level up!"
        )
    }

    res = enrich_metadata(record)
    inferred_slugs = {t["slug"] for t in res.inferred_tags}

    # Verify expected tags
    assert "manhwa" in inferred_slugs
    assert "dungeon_gate" in inferred_slugs
    assert "regression" in inferred_slugs
    assert "system_level_up" in inferred_slugs

    # Verify evidence trail exists
    gate_ev = next(e for e in res.evidences if e.target_slug == "dungeon_gate")
    assert gate_ev.source_field in ("titles", "synopsis")
    assert "hunter" in gate_ev.matched_content.lower() or "gate" in gate_ev.matched_content.lower()
