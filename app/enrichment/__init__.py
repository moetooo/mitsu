"""
Enrichment package for manga metadata normalization, rule-based inference,
and canonical taxonomy management.
"""

from .vocabulary import CANONICAL_VOCABULARY, CanonicalTag, TagCategory, get_tag_by_slug
from .synonyms import resolve_canonical_tag, normalize_tag_input, ALIAS_MAP
from .models import InferredTag, merge_inferred_tags
from .rules import RULES, EnrichmentRule
from .rules_engine import RuleEvidence, EnrichmentResult, enrich_metadata
from .ml_features import build_ml_text, extract_canonical_labels
from .ml_classifier import TagClassifier
from .llm_cache import LLMEnrichmentCache, compute_llm_cache_key
from .llm_enricher import (
    LLMEnricher,
    validate_llm_result,
    select_candidate_tags,
    LLM_ACCEPT_THRESHOLD,
    LLM_REVIEW_THRESHOLD,
    LLM_ENRICHMENT_ENABLED,
)

__all__ = [
    "CANONICAL_VOCABULARY",
    "CanonicalTag",
    "TagCategory",
    "get_tag_by_slug",
    "resolve_canonical_tag",
    "normalize_tag_input",
    "ALIAS_MAP",
    "InferredTag",
    "merge_inferred_tags",
    "RULES",
    "EnrichmentRule",
    "RuleEvidence",
    "EnrichmentResult",
    "enrich_metadata",
    "build_ml_text",
    "extract_canonical_labels",
    "TagClassifier",
    "LLMEnricher",
    "validate_llm_result",
    "select_candidate_tags",
    "LLMEnrichmentCache",
    "compute_llm_cache_key",
    "LLM_ACCEPT_THRESHOLD",
    "LLM_REVIEW_THRESHOLD",
    "LLM_ENRICHMENT_ENABLED",
]
