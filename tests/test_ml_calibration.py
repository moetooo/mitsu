"""
Unit and Integration Tests for Phase 4: ML Calibration & False-Positive Validation.

Tests verify:
1. Per-label metrics (precision, recall, f1, support) are generated.
2. Threshold configuration works across default and per-label settings.
3. Per-label threshold overrides global threshold.
4. Low-confidence predictions are rejected.
5. High-confidence predictions are accepted.
6. Rule predictions remain higher priority than ML (human > rule > model).
7. Suspicious BL example ("The Student I Thought I Knew") is reproduced and safely handled.
8. Model inference remains deterministic.
9. Database backfill integrity is validated and remains unchanged.
"""

import os
import pytest
from sqlalchemy import text
from app.db import AsyncSessionLocal
from app.enrichment.vocabulary import CANONICAL_VOCABULARY
from app.enrichment.models import InferredTag, merge_inferred_tags
from app.enrichment.rules_engine import enrich_metadata
from app.enrichment.ml_features import build_ml_text, clean_synopsis_text
from app.enrichment.ml_classifier import TagClassifier, DEFAULT_MODEL_DIR, SENSITIVE_LABELS

# Synthetic fixtures for fast, isolated unit testing
CALIBRATION_FIXTURES = [
    # Explicit BL samples
    {
        "title_english": "Spring Blossom Romance",
        "synopsis": "Two young boys share delicate feelings and gradually fall in love over the school year.",
        "genres": ["Romance", "Boys' Love"],
        "tags": [{"name": "Shounen Ai"}]
    },
    {
        "title_english": "Classmates in Love",
        "synopsis": "Male classmates discover their mutual affection and begin a secret romantic relationship.",
        "genres": ["Romance"],
        "tags": [{"name": "Yaoi"}]
    },
    {
        "title_english": "Whispers of the Heart",
        "synopsis": "A heartfelt boys love story between two childhood companions navigating their feelings.",
        "genres": ["Romance"],
        "tags": [{"name": "Boys Love"}]
    },
    # Explicit GL samples
    {
        "title_english": "Lily Petals",
        "synopsis": "Two female high school students find comfort in each other and begin a tender romance.",
        "genres": ["Romance", "Girls' Love"],
        "tags": [{"name": "Yuri"}]
    },
    {
        "title_english": "Summer Garden",
        "synopsis": "A beautiful story of girls love and romantic devotion between two young women.",
        "genres": ["Romance"],
        "tags": [{"name": "Shoujo Ai"}]
    },
    {
        "title_english": "Her Secret Smile",
        "synopsis": "Two female friends experience the gradual bloom of romantic feelings.",
        "genres": ["Romance"],
        "tags": [{"name": "Girls Love"}]
    },
    # Isekai & Fantasy samples
    {
        "title_english": "Summoned as a Hero",
        "synopsis": "An ordinary guy is suddenly transported to a magical fantasy world full of monsters and dragons.",
        "genres": ["Fantasy", "Adventure"],
        "tags": [{"name": "Isekai"}]
    },
    {
        "title_english": "Another World Rebirth",
        "synopsis": "Waking up in a parallel universe with extraordinary magic spells and dangerous labyrinths.",
        "genres": ["Fantasy"],
        "tags": [{"name": "Isekai"}]
    },
    {
        "title_english": "Arcane Portal",
        "synopsis": "Summoned to another world to master arcane sorcery and save the fantasy kingdom.",
        "genres": ["Fantasy"],
        "tags": [{"name": "Isekai"}]
    },
    # School life samples
    {
        "title_english": "Classroom Chronicles",
        "synopsis": "High school life in homeroom with active student council members and campus festivals.",
        "genres": ["Comedy", "Slice of Life"],
        "tags": [{"name": "School Life"}]
    },
    {
        "title_english": "Student Council President",
        "synopsis": "Daily adventures of high school classmates preparing for school examinations and sports day.",
        "genres": ["Slice of Life"],
        "tags": [{"name": "School Life"}]
    },
    {
        "title_english": "Academy Days",
        "synopsis": "A new transfer student arrives at the prestigious high school academy.",
        "genres": ["Comedy"],
        "tags": [{"name": "School Life"}]
    }
]


def test_per_label_metrics_generation():
    """Test 1: Per-label metrics (precision, recall, f1, support) are generated."""
    clf = TagClassifier(default_threshold=0.50, min_df=1)
    metrics = clf.train(CALIBRATION_FIXTURES, min_samples_per_label=2, test_size=0.25, random_state=42)

    assert "per_label_metrics" in clf.metadata_
    assert "precision_tiers" in clf.metadata_
    per_label = clf.metadata_["per_label_metrics"]

    assert len(per_label) > 0
    for slug, data in per_label.items():
        assert "precision" in data["metrics_at_recommended"]
        assert "recall" in data["metrics_at_recommended"]
        assert "f1" in data["metrics_at_recommended"]
        assert "support" in data
        assert "recommended_threshold" in data
        assert data["slug"] in CANONICAL_VOCABULARY

    tiers = clf.metadata_["precision_tiers"]
    assert "high" in tiers
    assert "medium" in tiers
    assert "low" in tiers
    assert "insufficient_support" in tiers


def test_threshold_configuration_works():
    """Test 2: Threshold configuration works across global defaults and per-label thresholds."""
    custom_thresholds = {
        "boys_love": 0.85,
        "school_life": 0.65,
        "romance": 0.75
    }
    clf = TagClassifier(default_threshold=0.70, per_label_thresholds=custom_thresholds)

    assert clf.get_threshold_for_label("boys_love") == 0.85
    assert clf.get_threshold_for_label("school_life") == 0.65
    assert clf.get_threshold_for_label("romance") == 0.75
    # Unconfigured tag returns default threshold
    assert clf.get_threshold_for_label("unconfigured_tag") == 0.70


def test_per_label_threshold_overrides_global_threshold():
    """Test 3: Per-label threshold overrides global threshold."""
    clf = TagClassifier(default_threshold=0.50, per_label_thresholds={"boys_love": 0.85}, min_df=1)
    clf.train(CALIBRATION_FIXTURES, min_samples_per_label=2, test_size=0.25, random_state=42)

    # Calling with no override uses the per-label threshold for boys_love (0.85)
    assert clf.get_threshold_for_label("boys_love") == 0.85

    # Calling with explicit per_label_thresholds in predict overrides instance setting
    preds_override = clf.predict(
        {"synopsis": "Two young boys falling in love."},
        per_label_thresholds={"boys_love": 0.99}
    )
    for p in preds_override:
        if p["slug"] == "boys_love":
            assert p["threshold"] == 0.99


def test_low_confidence_predictions_are_rejected():
    """Test 4: Predictions below active threshold or in low tier are rejected."""
    clf = TagClassifier(default_threshold=0.95, min_df=1)
    clf.train(CALIBRATION_FIXTURES, min_samples_per_label=2, test_size=0.25, random_state=42)

    # High threshold means weak/moderate predictions should be rejected
    weak_rec = {"synopsis": "A story happening in some unspecified place."}
    preds = clf.predict(weak_rec, threshold=0.95, only_accepted=True)
    assert len(preds) == 0

    enriched = clf.enrich(weak_rec, threshold=0.95)
    assert len(enriched) == 0


def test_high_confidence_predictions_are_accepted():
    """Test 5: Clear signal meeting calibrated threshold in acceptable tier is accepted."""
    clf = TagClassifier(default_threshold=0.10, min_df=1)
    clf.train(CALIBRATION_FIXTURES, min_samples_per_label=2, test_size=0.25, random_state=42)

    strong_rec = {"synopsis": "Two young boys share delicate feelings and gradually fall in love."}
    preds = clf.predict(strong_rec, threshold=0.10, only_accepted=True)
    assert any(p["slug"] == "boys_love" for p in preds)

    tags = clf.enrich(strong_rec, threshold=0.10)
    assert any(t.slug == "boys_love" for t in tags)
    for t in tags:
        assert t.provenance == "model"
        assert t.confidence >= 0.10


def test_rule_predictions_remain_higher_priority_than_ml():
    """Test 6: Priority hierarchy ensures rule tags (priority 3) supersede ML tags (priority 2)."""
    clf = TagClassifier(default_threshold=0.10, min_df=1)
    clf.train(CALIBRATION_FIXTURES, min_samples_per_label=2, test_size=0.25, random_state=42)

    # Synopsis contains explicit 'boys love' trigger for Phase 2 Rule
    # and also matches ML classifier
    rec = {
        "title_english": "Pure Romance",
        "synopsis": "A delicate boys love romance between two students."
    }

    res = enrich_metadata(rec, classifier=clf, ml_threshold=0.10)
    bl_tag = next((t for t in res.inferred_tags if t["slug"] == "boys_love"), None)
    assert bl_tag is not None
    # Provenance MUST be 'rule' (rules remain higher priority than ML)
    assert bl_tag["provenance"] == "rule"
    assert bl_tag["source_rule"].startswith("RULE-")


def test_suspicious_bl_example_is_reproduced_and_safely_rejected():
    """Test 7: Suspicious example 'The Student I Thought I Knew' is reproduced and safely rejected."""
    # Test record from validation issue
    rec = {
        "title_romaji": "Saikai Shita Oshiego wa Watashi ga Shiranai Kao wo Suro",
        "title_english": "The Student I Thought I Knew",
        "synopsis": (
            "\"I'm not a child anymore, says Honoka Miyama's former student... before kissing her!\n\n"
            "It's been five years since Honoka became a teacher. With the arrival of a new batch of trainee teachers "
            "and her dream of an event from five years ago, Honoka finds a wave of nostalgia coming over her. "
            "Much to her surprise, the student she dreamed about, Tougo Ashiya, is among the new trainees! "
            "After the welcome party, Tougo invites Honoka to his place, where he soon reveals that his feelings "
            "for her haven't changed. Not letting her speak, he pulls her shirt open, sucking softly on her exposed chest "
            "as his hand slips down her thigh to a sensitive spot... \"Make sure you remember every detail of tonight.\"\n\n"
            "The student she thought she knew shows a side of him she's never seen before!\n\n(Source: Renta!)"
        )
    }

    # 1. Verify that synopsis cleaning removes distributor boilerplate
    cleaned_syn = clean_synopsis_text(rec["synopsis"])
    assert "(Source: Renta!)" not in cleaned_syn
    assert "Renta!" not in cleaned_syn

    # 2. Verify on persisted calibrated model. `models/` is gitignored, so a
    #    missing artifact is a reported skip, never a silently disabled assert.
    if not os.path.exists(os.path.join(DEFAULT_MODEL_DIR, "model.joblib")):
        pytest.skip(
            f"calibrated model artifact missing at {DEFAULT_MODEL_DIR}; "
            "this assertion needs the real model, not a fixture-trained one"
        )

    clf = TagClassifier.load(DEFAULT_MODEL_DIR)
    assert clf.is_trained

    # Automatic enrichment with accept_tier='high'
    preds = clf.predict(rec, accept_tier="high", only_accepted=True)
    pred_slugs = {p["slug"] for p in preds}

    # CRITICAL ASSERTION: boys_love MUST NOT be accepted
    assert "boys_love" not in pred_slugs

    # In full enrichment pipeline
    result = enrich_metadata(rec, classifier=clf, ml_accept_tier="high")
    pipeline_slugs = {t["slug"] for t in result.inferred_tags}
    assert "boys_love" not in pipeline_slugs


def test_model_inference_remains_deterministic():
    """Test 8: Repeated inference on the same input produces identical results and confidence scores."""
    if os.path.exists(os.path.join(DEFAULT_MODEL_DIR, "model.joblib")):
        clf = TagClassifier.load(DEFAULT_MODEL_DIR)
    else:
        clf = TagClassifier(default_threshold=0.50, min_df=1)
        clf.train(CALIBRATION_FIXTURES, min_samples_per_label=2, test_size=0.25, random_state=42)

    sample = {
        "title_english": "Parallel World Sorcery",
        "synopsis": "An adventurer explores dungeons and uses arcane magic to defeat dragons."
    }

    preds1 = clf.predict(sample, accept_tier=None, only_accepted=False)
    preds2 = clf.predict(sample, accept_tier=None, only_accepted=False)

    assert preds1 == preds2
    for p1, p2 in zip(preds1, preds2):
        assert p1["confidence"] == p2["confidence"]
        assert p1["slug"] == p2["slug"]
        assert p1["tier"] == p2["tier"]


@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_database_backfill_integrity():
    """Test 9: Verify database enriched state is internally valid and unmodified."""
    async with AsyncSessionLocal() as session:
        # Capture counts before integrity check
        total_before = (await session.execute(text("SELECT COUNT(*) FROM manga;"))).scalar()
        inferred_before = (await session.execute(
            text("SELECT COUNT(*) FROM manga WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb;")
        )).scalar()
        total_instances_before = (await session.execute(
            text("SELECT SUM(jsonb_array_length(inferred_tags)) FROM manga WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb;")
        )).scalar()

        # Integrity checks: catalog size and enriched coverage
        assert total_before >= 95255, f"Unexpected manga row count: {total_before}"
        assert inferred_before == 11028, f"Unexpected enriched title count: {inferred_before}"
        assert total_instances_before == 11411, f"Unexpected total inferred tag instances: {total_instances_before}"

        # Verify internal validity of inferred_tags records
        rows = (await session.execute(text("""
            SELECT id, inferred_tags
            FROM manga
            WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb
            LIMIT 500;
        """))).mappings().fetchall()

        valid_provenances = {"external", "rule", "model", "llm", "human"}
        for r in rows:
            tags = r["inferred_tags"]
            assert isinstance(tags, list) and len(tags) > 0, f"Empty inferred_tags list in title {r['id']}"
            seen_slugs = set()
            for t in tags:
                assert isinstance(t, dict), f"Tag entry is not a dict in title {r['id']}"
                slug = t.get("slug")
                assert slug in CANONICAL_VOCABULARY, f"Invalid canonical slug '{slug}' in title {r['id']}"
                assert slug not in seen_slugs, f"Duplicate tag '{slug}' in title {r['id']}"
                seen_slugs.add(slug)
                prov = t.get("provenance")
                assert prov in valid_provenances, f"Invalid provenance '{prov}' in title {r['id']}"

        # Capture counts after integrity check to ensure test had zero side-effects
        total_after = (await session.execute(text("SELECT COUNT(*) FROM manga;"))).scalar()
        inferred_after = (await session.execute(
            text("SELECT COUNT(*) FROM manga WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb;")
        )).scalar()
        total_instances_after = (await session.execute(
            text("SELECT SUM(jsonb_array_length(inferred_tags)) FROM manga WHERE inferred_tags IS NOT NULL AND inferred_tags != '[]'::jsonb;")
        )).scalar()

        assert total_after == total_before
        assert inferred_after == inferred_before
        assert total_instances_after == total_instances_before

