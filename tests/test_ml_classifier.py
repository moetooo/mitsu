"""
Unit and Integration Tests for Phase 3 Local ML-Based Tag Classification.

Uses small synthetic fixture datasets to guarantee fast, deterministic,
and isolated unit testing without requiring full database training during test runs.
"""

import os
import shutil
import tempfile
import pytest

from app.enrichment.vocabulary import CANONICAL_VOCABULARY
from app.enrichment.ml_features import build_ml_text, extract_canonical_labels
from app.enrichment.ml_classifier import TagClassifier
from app.enrichment.models import InferredTag, merge_inferred_tags
from app.enrichment.rules_engine import enrich_metadata

# Small synthetic dataset with clear, distinct textual patterns and known canonical tags
FIXTURE_RECORDS = [
    # Boys' love samples
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
    # Girls' love samples
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


def test_feature_builder_produces_stable_output():
    """Test 1: build_ml_text formats title and synopsis cleanly and stably."""
    rec = {
        "title_romaji": "Boku no Test",
        "title_english": "My Test Story",
        "alternative_titles": ["Alt 1", "Alt 2"],
        "synopsis": "A thrilling tale of adventure."
    }
    text1 = build_ml_text(rec)
    text2 = build_ml_text(rec)
    assert text1 == text2
    assert "Title: Boku no Test My Test Story Alt 1 Alt 2" in text1
    assert "Synopsis: A thrilling tale of adventure." in text1


def test_training_data_contains_only_canonical_labels():
    """Test 2: extract_canonical_labels resolves source strings to canonical slugs."""
    rec = {
        "genres": ["Romance", "Boys' Love"],
        "tags": [{"name": "Yaoi"}, {"name": "Shounen Ai"}, {"name": "UnknownTagXYZ"}]
    }
    labels = extract_canonical_labels(rec)
    for l in labels:
        assert l in CANONICAL_VOCABULARY
    assert "boys_love" in labels
    assert "romance" in labels


def test_unknown_raw_tags_never_become_ml_labels():
    """Test 3: Non-canonical or unknown tags are completely excluded."""
    rec = {
        "genres": ["NonExistentGenre123"],
        "tags": [{"name": "TotallyInventedTag999"}]
    }
    labels = extract_canonical_labels(rec)
    assert labels == []


def test_multilabel_training_works_on_small_fixture():
    """Test 4 & 5: Model trains successfully on fixture records."""
    clf = TagClassifier(default_threshold=0.35, min_df=1)
    metrics = clf.train(FIXTURE_RECORDS, min_samples_per_label=2, test_size=0.25, random_state=42)
    assert clf.is_trained
    assert len(clf.labels_) >= 3  # boys_love, girls_love, isekai, school_life
    assert "metrics" in metrics
    assert "baseline_comparison" in metrics
    assert "precision_micro" in metrics["metrics"]


def test_model_can_save_and_reload():
    """Test 6 & 7: Model can be serialized to disk and loaded identically."""
    tmp_dir = tempfile.mkdtemp()
    try:
        clf = TagClassifier(default_threshold=0.35, min_df=1)
        clf.train(FIXTURE_RECORDS, min_samples_per_label=2, test_size=0.25, random_state=42)
        clf.save(tmp_dir)

        # Check saved files exist
        assert os.path.exists(os.path.join(tmp_dir, "model.joblib"))
        assert os.path.exists(os.path.join(tmp_dir, "metadata.json"))

        # Reload
        loaded_clf = TagClassifier.load(tmp_dir)
        assert loaded_clf.is_trained
        assert loaded_clf.labels_ == clf.labels_

        # Predictions match identically
        test_rec = {"synopsis": "Two young boys in school fall in love with each other."}
        preds_orig = clf.predict(test_rec, threshold=0.1)
        preds_loaded = loaded_clf.predict(test_rec, threshold=0.1)
        assert preds_orig == preds_loaded
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_confidence_threshold_works():
    """Test 8: Changing threshold filters predictions appropriately."""
    clf = TagClassifier(min_df=1)
    clf.train(FIXTURE_RECORDS, min_samples_per_label=2, test_size=0.25, random_state=42)

    test_rec = {"synopsis": "Two boys share feelings and romance."}
    low_thresh_preds = clf.predict(test_rec, threshold=0.10)
    high_thresh_preds = clf.predict(test_rec, threshold=0.99)

    assert len(low_thresh_preds) >= len(high_thresh_preds)
    for p in high_thresh_preds:
        assert p["confidence"] >= 0.99


def test_predictions_contain_valid_canonical_slugs_only():
    """Test 9: Every single ML prediction slug is in CANONICAL_VOCABULARY."""
    clf = TagClassifier(min_df=1)
    clf.train(FIXTURE_RECORDS, min_samples_per_label=2, test_size=0.25, random_state=42)

    test_rec = {"synopsis": "Transported into a parallel fantasy universe."}
    preds = clf.predict(test_rec, threshold=0.1)
    for p in preds:
        assert p["slug"] in CANONICAL_VOCABULARY


def test_ml_predictions_use_provenance_model():
    """Test 10: InferredTag objects generated by classifier have provenance='model'."""
    clf = TagClassifier(min_df=1)
    clf.train(FIXTURE_RECORDS, min_samples_per_label=2, test_size=0.25, random_state=42)

    test_rec = {"synopsis": "Transported to another fantasy world with dragons."}
    tags = clf.enrich(test_rec, threshold=0.2)
    assert len(tags) > 0
    for t in tags:
        assert t.provenance == "model"
        assert t.source_rule is not None
        assert t.source_rule.startswith("ML-")


def test_ml_cannot_downgrade_a_stronger_rule_tag():
    """Test 11: Priority hierarchy ensures rule tags (priority 3) supersede ML tags (priority 2)."""
    # A rule tag with high confidence
    rule_tag = InferredTag.from_canonical(
        slug="boys_love",
        confidence=0.95,
        provenance="rule",
        source_rule="RULE-BL-001"
    )

    # An ML tag for the same slug
    ml_tag = InferredTag.from_canonical(
        slug="boys_love",
        confidence=0.99,  # Even with higher numerical confidence, rule provenance takes priority
        provenance="model",
        source_rule="ML-v1.0.0"
    )

    merged = merge_inferred_tags([rule_tag.to_dict()], [ml_tag.to_dict()])
    assert len(merged) == 1
    assert merged[0]["provenance"] == "rule"
    assert merged[0]["source_rule"] == "RULE-BL-001"


def test_empty_or_minimal_metadata_does_not_crash_ml():
    """Test 12: Empty metadata returns gracefully."""
    clf = TagClassifier(min_df=1)
    clf.train(FIXTURE_RECORDS, min_samples_per_label=2, test_size=0.25, random_state=42)

    assert clf.predict({}) == []
    assert clf.predict({"synopsis": None}) == []
    assert clf.enrich({}) == []


def test_insufficient_data_labels_excluded_gracefully():
    """Test 13: Labels with counts below min_samples_per_label are excluded gracefully, and too few labels raises ValueError."""
    clf = TagClassifier(min_df=1)
    # With threshold 3: labels with < 3 examples (like 'adventure' or 'comedy') are excluded
    metrics = clf.train(FIXTURE_RECORDS, min_samples_per_label=3, test_size=0.25, random_state=42)
    assert "adventure" in metrics["excluded_labels"]
    assert "comedy" in metrics["excluded_labels"]
    assert "adventure" not in clf.labels_

    # When min_samples_per_label is impossibly high, raises ValueError gracefully
    with pytest.raises(ValueError, match="Insufficient trainable labels"):
        clf.train(FIXTURE_RECORDS, min_samples_per_label=100)


def test_evaluation_metrics_and_baseline_comparison():
    """Test 14: Evaluation metrics and baseline comparison are computed."""
    clf = TagClassifier(min_df=1)
    metrics = clf.train(FIXTURE_RECORDS, min_samples_per_label=2, test_size=0.25, random_state=42)

    m = metrics["metrics"]
    b = metrics["baseline_comparison"]
    assert "precision_micro" in m
    assert "recall_micro" in m
    assert "f1_micro" in m
    assert "baseline_f1_micro" in b
    assert "f1_micro_improvement" in b


def test_repeated_inference_produces_identical_output():
    """Test 15: Determinism - Multiple inference passes on the same input yield identical results."""
    clf = TagClassifier(min_df=1)
    clf.train(FIXTURE_RECORDS, min_samples_per_label=2, test_size=0.25, random_state=42)

    test_rec = {
        "title_english": "Hero Academy",
        "synopsis": "High school students in an academy preparing for sports festivals."
    }

    res1 = clf.predict(test_rec)
    res2 = clf.predict(test_rec)
    assert res1 == res2


def test_pipeline_integration_rules_plus_ml():
    """Test 16: Integration of Rules + ML in enrich_metadata."""
    clf = TagClassifier(default_threshold=0.2, min_df=1)
    clf.train(FIXTURE_RECORDS, min_samples_per_label=2, test_size=0.25, random_state=42)

    rec = {
        "title_english": "Fantasy Portal",
        # Notice: synopsis contains explicit "boys love" (triggers Rule)
        # and "transported to a magical fantasy world" (triggers ML / rule)
        "synopsis": "A boys love story where he is transported to a magical fantasy world with dragons."
    }

    res = enrich_metadata(rec, classifier=clf)
    slugs = {t["slug"] for t in res.inferred_tags}
    assert "boys_love" in slugs

    # Verify provenance of boys_love is 'rule'
    bl_tag = next(t for t in res.inferred_tags if t["slug"] == "boys_love")
    assert bl_tag["provenance"] == "rule"
