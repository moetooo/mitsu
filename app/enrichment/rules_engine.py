"""
Rule-Based Metadata Enrichment Engine.

Provides deterministic evaluation of metadata against controlled taxonomy rules.
Does not make network calls, invoke LLMs, or mutate raw metadata.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Union, Set
import re
from .vocabulary import CANONICAL_VOCABULARY, get_tag_by_slug
from .synonyms import normalize_tag_input
from .models import InferredTag, merge_inferred_tags
from .rules import RULES, EnrichmentRule

@dataclass(frozen=True)
class RuleEvidence:
    """Audit trail for why a rule fired."""
    rule_id: str
    target_slug: str
    confidence: float
    source_field: str
    matched_content: str
    description: str

@dataclass
class EnrichmentResult:
    """Enrichment output containing inferred tags and verifiable evidence."""
    inferred_tags: List[Dict[str, Any]]
    evidences: List[RuleEvidence]
    new_inferred_tags: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inferred_tags": self.inferred_tags,
            "new_inferred_tags": self.new_inferred_tags,
            "evidences": [asdict(e) for e in self.evidences]
        }


def _extract_text_fields(record: Union[Dict[str, Any], Any]) -> Dict[str, str]:
    """Extracts and cleans all textual metadata fields without mutating input."""
    def _get(field_name: str) -> Any:
        if isinstance(record, dict):
            return record.get(field_name)
        return getattr(record, field_name, None)

    synopsis = str(_get("synopsis") or "").strip()
    title_romaji = str(_get("title_romaji") or "").strip()
    title_english = str(_get("title_english") or "").strip()
    title_native = str(_get("title_native") or "").strip()
    
    alt_titles_raw = _get("alternative_titles") or []
    alt_titles = [str(a).strip() for a in alt_titles_raw if a and str(a).strip()]

    # Aggregate title corpus
    all_titles = [t for t in [title_romaji, title_english, title_native] + alt_titles if t]
    title_corpus = " | ".join(all_titles)

    return {
        "synopsis": synopsis,
        "title_corpus": title_corpus,
        "title_romaji": title_romaji,
        "title_english": title_english,
    }


def _extract_tag_and_genre_lists(record: Union[Dict[str, Any], Any]) -> Dict[str, Set[str]]:
    """Extracts normalized sets of raw genres and tag names."""
    def _get(field_name: str) -> Any:
        if isinstance(record, dict):
            return record.get(field_name)
        return getattr(record, field_name, None)

    genres_raw = _get("genres") or []
    normalized_genres = {normalize_tag_input(str(g)) for g in genres_raw if g}

    tags_raw = _get("tags") or []
    normalized_tags: Set[str] = set()
    for item in tags_raw:
        if isinstance(item, dict):
            name = item.get("name")
            if name:
                normalized_tags.add(normalize_tag_input(str(name)))
        elif isinstance(item, str) and item:
            normalized_tags.add(normalize_tag_input(item))

    return {
        "genres": normalized_genres,
        "tags": normalized_tags
    }


def evaluate_rule(
    rule: EnrichmentRule,
    synopsis: str,
    title_corpus: str,
    normalized_genres: Set[str],
    normalized_tags: Set[str]
) -> Optional[RuleEvidence]:
    """
    Evaluates a single rule against metadata.
    Returns RuleEvidence if fired, None otherwise.
    """
    combined_text = f"{title_corpus}\n{synopsis}".strip()
    if not combined_text and not normalized_genres and not normalized_tags:
        return None

    # 1. Negative pattern check (Guardrail against false positives)
    if rule.negative_patterns and combined_text:
        for neg_pat in rule.negative_patterns:
            if neg_pat.search(combined_text):
                return None

    # 2. Check Genre Triggers
    if rule.genre_triggers and normalized_genres:
        for trig in rule.genre_triggers:
            if normalize_tag_input(trig) in normalized_genres:
                return RuleEvidence(
                    rule_id=rule.rule_id,
                    target_slug=rule.target_slug,
                    confidence=rule.confidence,
                    source_field="genres",
                    matched_content=f"genre:{trig}",
                    description=rule.description
                )

    # 3. Check Raw Tag Triggers
    if rule.tag_triggers and normalized_tags:
        for trig in rule.tag_triggers:
            if normalize_tag_input(trig) in normalized_tags:
                return RuleEvidence(
                    rule_id=rule.rule_id,
                    target_slug=rule.target_slug,
                    confidence=rule.confidence,
                    source_field="tags",
                    matched_content=f"tag:{trig}",
                    description=rule.description
                )

    # 4. Check Strong Text Patterns (Title first, then Synopsis)
    if rule.strong_patterns:
        # Check titles
        if title_corpus:
            for pat in rule.strong_patterns:
                m = pat.search(title_corpus)
                if m:
                    return RuleEvidence(
                        rule_id=rule.rule_id,
                        target_slug=rule.target_slug,
                        confidence=rule.confidence,
                        source_field="titles",
                        matched_content=m.group(0),
                        description=rule.description
                    )
        # Check synopsis
        if synopsis:
            for pat in rule.strong_patterns:
                m = pat.search(synopsis)
                if m:
                    return RuleEvidence(
                        rule_id=rule.rule_id,
                        target_slug=rule.target_slug,
                        confidence=rule.confidence,
                        source_field="synopsis",
                        matched_content=m.group(0),
                        description=rule.description
                    )

    # 5. Check Corroborating Patterns (Requires >= min_corroborating distinct matches)
    if rule.corroborating_patterns and combined_text:
        matched_terms = []
        for pat in rule.corroborating_patterns:
            m = pat.search(combined_text)
            if m:
                matched_terms.append(m.group(0))
        if len(matched_terms) >= rule.min_corroborating:
            return RuleEvidence(
                rule_id=rule.rule_id,
                target_slug=rule.target_slug,
                confidence=rule.confidence,
                source_field="synopsis",
                matched_content=", ".join(matched_terms),
                description=rule.description
            )

    return None


def enrich_metadata(
    record: Union[Dict[str, Any], Any],
    rules: Optional[List[EnrichmentRule]] = None,
    classifier: Optional[Any] = None,
    ml_threshold: Optional[float] = None,
    ml_accept_tier: str = "high",
    ml_per_label_thresholds: Optional[Dict[str, float]] = None,
    llm_enricher: Optional[Any] = None,
    candidate_tags: Optional[List[str]] = None
) -> EnrichmentResult:
    """
    Enriches metadata for a single manga record using deterministic rules,
    calibrated local ML classification, and optional controlled LLM fallback.
    
    Pipeline flow:
    1. Phase 1 Normalized metadata
    2. Phase 2 Deterministic rules (provenance="rule")
    3. Phase 3/4 Local ML classifier (provenance="model")
    4. Phase 5 Controlled LLM fallback (provenance="llm")
    5. Deterministic conflict-free merge (rule > model > llm)
    
    Guarantees:
    - Never modifies input record, raw tags, genres, or titles.
    - Zero network or LLM dependencies when llm_enricher is None or disabled.
    - Preserves existing higher-confidence/higher-provenance inferred tags.
    
    Args:
        record: Manga dict or Manga SQLAlchemy model instance.
        rules: Optional custom rule subset. Defaults to complete RULES registry.
        classifier: Optional TagClassifier instance for Phase 3/4 ML enrichment.
        ml_threshold: Optional probability cutoff for ML predictions.
        ml_accept_tier: Confidence tier requirement ('high', 'medium', 'all').
        ml_per_label_thresholds: Optional per-label threshold overrides.
        llm_enricher: Optional LLMEnricher instance for Phase 5 fallback.
        candidate_tags: Optional explicit candidate tags to evaluate with LLM.
        
    Returns:
        EnrichmentResult containing merged inferred_tags, newly inferred tags, and evidences.
    """
    active_rules = rules if rules is not None else RULES

    # Extract clean copies of textual & category metadata
    text_fields = _extract_text_fields(record)
    cat_fields = _extract_tag_and_genre_lists(record)

    synopsis = text_fields["synopsis"]
    title_corpus = text_fields["title_corpus"]
    normalized_genres = cat_fields["genres"]
    normalized_tags = cat_fields["tags"]

    # Extract existing inferred tags
    existing_inferred: List[Dict[str, Any]] = []
    if isinstance(record, dict):
        existing_inferred = record.get("inferred_tags") or []
    else:
        existing_inferred = getattr(record, "inferred_tags", None) or []

    # 1. Evaluate Phase 2 Rules (Deterministic)
    evidences: List[RuleEvidence] = []
    new_inferred_objects: List[InferredTag] = []

    for rule in active_rules:
        evidence = evaluate_rule(
            rule=rule,
            synopsis=synopsis,
            title_corpus=title_corpus,
            normalized_genres=normalized_genres,
            normalized_tags=normalized_tags
        )
        if evidence:
            evidences.append(evidence)
            inferred = InferredTag.from_canonical(
                slug=rule.target_slug,
                confidence=rule.confidence,
                provenance="rule",
                source_rule=rule.rule_id
            )
            new_inferred_objects.append(inferred)

    # 2. Evaluate Phase 3/4 Local ML (if provided)
    if classifier is not None and getattr(classifier, "is_trained", False):
        ml_tags = classifier.enrich(
            record,
            threshold=ml_threshold,
            per_label_thresholds=ml_per_label_thresholds,
            accept_tier=ml_accept_tier
        )
        for ml_tag in ml_tags:
            new_inferred_objects.append(ml_tag)
            evidences.append(RuleEvidence(
                rule_id=ml_tag.source_rule or f"ML-{classifier.model_version}",
                target_slug=ml_tag.slug,
                confidence=ml_tag.confidence,
                source_field="ml_model",
                matched_content=f"proba={ml_tag.confidence}",
                description="Local ML multilabel text classifier prediction"
            ))

    # 3. Evaluate Phase 5 Controlled LLM Fallback (if provided and enabled)
    if llm_enricher is not None and getattr(llm_enricher, "enabled", False):
        try:
            ml_preds = (
                classifier.predict(record, accept_tier=None, only_accepted=False)
                if classifier is not None and getattr(classifier, "is_trained", False)
                else []
            )
            llm_tags = llm_enricher.enrich(
                record=record,
                candidate_tags=candidate_tags,
                rule_tags=new_inferred_objects,
                ml_predictions=ml_preds
            )
            for llm_tag in llm_tags:
                new_inferred_objects.append(llm_tag)
                evidences.append(RuleEvidence(
                    rule_id=llm_tag.source_rule or f"LLM-{getattr(llm_enricher, 'model', 'default')}",
                    target_slug=llm_tag.slug,
                    confidence=llm_tag.confidence,
                    source_field="llm_fallback",
                    matched_content=llm_tag.evidence or f"conf={llm_tag.confidence}",
                    description="Controlled LLM fallback inference with textual evidence"
                ))
        except Exception:
            # LLM failure must NEVER break enrichment
            pass

    # 4. Deterministically merge with priority: human > rule > model > llm
    merged_tags = merge_inferred_tags(
        existing_tags=existing_inferred,
        incoming_tags=new_inferred_objects
    )

    new_inferred_dicts = [t.to_dict() for t in new_inferred_objects]

    return EnrichmentResult(
        inferred_tags=merged_tags,
        evidences=evidences,
        new_inferred_tags=new_inferred_dicts
    )
