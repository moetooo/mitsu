"""
Controlled LLM Fallback Layer for Manga Metadata Enrichment.

Features:
1. Fallback only: invoked strictly when deterministic rules and calibrated local ML
   cannot confidently classify metadata. Never runs for search or user queries.
2. Controlled canonical vocabulary: LLM may ONLY output tags from CANONICAL_VOCABULARY.
   Unknown tags, aliases, and free-form strings are strictly discarded.
3. Structured output: strict JSON schema enforcing tag, confidence [0, 1], and textual evidence.
4. Multi-tier confidence policy:
   - >= 0.80: accepted for automatic storage.
   - 0.60 <= conf < 0.80: provisional / review-only.
   - < 0.60: rejected.
5. Deterministic caching: avoids costly duplicate API calls and guarantees auditability.
6. Safe circuit breakers: LLM_ENRICHMENT_ENABLED (default False) and max call limits per run.
7. Resilience: API errors, timeouts, or invalid JSON never break enrichment/ingestion.
"""

import os
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional, Union, Tuple, Set

from .vocabulary import CANONICAL_VOCABULARY, get_tag_by_slug
from .models import InferredTag
from .ml_features import build_ml_text, clean_synopsis_text
from .llm_cache import LLMEnrichmentCache, compute_llm_cache_key

logger = logging.getLogger(__name__)

# Configuration constants
LLM_ENRICHMENT_ENABLED: bool = os.getenv("LLM_ENRICHMENT_ENABLED", "false").lower() in ("true", "1", "yes")
LLM_ACCEPT_THRESHOLD: float = 0.80
LLM_REVIEW_THRESHOLD: float = 0.60
LLM_MAX_CALLS_PER_RUN: int = int(os.getenv("LLM_MAX_CALLS_PER_RUN", "100"))
DEFAULT_LLM_MODEL: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
PROMPT_VERSION: str = "v1.0"

LLM_TAG_THRESHOLDS: Dict[str, float] = {
    # Broad/general tags that require higher confidence to avoid overinterpretation
    "comedy": 0.90,
    "adventure": 0.90,
    "survival": 0.90,
    "drama": 0.90,
    "fantasy": 0.90,
    "action": 0.90,

    # Subtle narrative tags where the LLM excels
    "slow_burn": 0.80,
    "friends_to_lovers": 0.80,
    "enemies_to_lovers": 0.80,
    "contract_marriage": 0.80,
    "fake_relationship": 0.80,
    "love_triangle": 0.80,
    "reborn_as_a_villainess": 0.80,
    "regression": 0.80,
    "revenge": 0.80,
    "time_travel": 0.80
}

def get_llm_accept_threshold(tag_slug: str, default_threshold: float = LLM_ACCEPT_THRESHOLD) -> float:
    """Returns the tag-specific LLM confidence threshold if configured, else the default."""
    return LLM_TAG_THRESHOLDS.get(tag_slug, default_threshold)

# Complex or subtle narrative tropes where LLM reasoning provides effective recall recovery
COMPLEX_TROPE_CANDIDATES: List[str] = [
    "slow_burn",
    "friends_to_lovers",
    "enemies_to_lovers",
    "contract_marriage",
    "childhood_friends",
    "love_triangle",
    "fake_relationship",
    "reborn_as_a_villainess",
    "revenge",
    "time_travel",
    "survival",
    "dungeon_gate"
]

SYSTEM_PROMPT = """You are a manga metadata classification assistant.
Your task is to determine whether specific candidate tags from a controlled canonical vocabulary
are factually supported by the provided manga title and synopsis.

CRITICAL RULES:
1. You may ONLY select tags from the CANDIDATE TAGS list provided in the user prompt.
2. NEVER create new tag names, synonyms, or free-form categories.
3. Infer a tag ONLY when the synopsis or titles explicitly or strongly support it.
4. DO NOT infer a tag merely because it often appears in similar genres.
5. DO NOT infer demographic labels (shounen, shoujo, seinen, josei) from weak clues.
6. DO NOT invent plot details or assume unmentioned facts.
7. If evidence is ambiguous, weak, or insufficient, you MUST set abstain=true or omit the tag.
8. For each inferred tag, provide a concise explanation ("evidence") directly referencing facts in the synopsis.
9. Assign a confidence score between 0.0 and 1.0 reflecting how strongly the text supports the tag.
10. Return ONLY valid JSON matching the schema below. No markdown backticks, no text outside the JSON object.

DISTINGUISH CLEARLY:
- SUPPORTED: The story synopsis explicitly or strongly implies the concept.
- UNSUPPORTED: The concept is not sufficiently supported by the supplied story text.
- ABSTAIN: There is insufficient evidence to make a reliable determination.

SCHEMA:
{
  "tags": [
    {
      "tag": "<canonical_tag_slug>",
      "confidence": <float between 0.0 and 1.0>,
      "evidence": "<short explanation referencing supplied text>"
    }
  ],
  "abstain": <true if uncertain or insufficient evidence, false otherwise>
}
"""


def validate_llm_result(
    raw_response: Union[str, Dict[str, Any]],
    candidate_tags: Set[str]
) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
    """
    Validates the structured output from an LLM against schema, canonical vocabulary,
    and the permissible candidate set.
    
    Returns:
        Tuple of:
        - valid_tags: List of verified tag dictionaries [{'slug': str, 'confidence': float, 'evidence': str}]
        - is_valid: Boolean indicating whether response was well-formed
        - errors: List of validation error/rejection explanations
    """
    errors: List[str] = []

    # 1. Parse JSON if string
    parsed: Dict[str, Any] = {}
    if isinstance(raw_response, str):
        cleaned_str = raw_response.strip()
        # Strip potential markdown formatting if returned
        if cleaned_str.startswith("```json"):
            cleaned_str = cleaned_str[7:]
        if cleaned_str.startswith("```"):
            cleaned_str = cleaned_str[3:]
        if cleaned_str.endswith("```"):
            cleaned_str = cleaned_str[:-3]
        cleaned_str = cleaned_str.strip()

        try:
            parsed = json.loads(cleaned_str)
        except Exception as e:
            return [], False, [f"Malformed JSON: {e}"]
    elif isinstance(raw_response, dict):
        parsed = raw_response
    else:
        return [], False, [f"Unsupported response type: {type(raw_response)}"]

    if not isinstance(parsed, dict):
        return [], False, ["Response root is not a JSON object"]

    # 2. Check for explicit abstention
    if parsed.get("abstain") is True:
        return [], True, ["LLM explicitly abstained due to insufficient evidence"]

    raw_tags = parsed.get("tags")
    if not isinstance(raw_tags, list):
        return [], False, ["'tags' field is missing or not a list"]

    # 3. Validate each tag entry
    valid_tags_map: Dict[str, Dict[str, Any]] = {}

    for idx, item in enumerate(raw_tags):
        if not isinstance(item, dict):
            errors.append(f"Item {idx}: not a dictionary")
            continue

        raw_slug = item.get("tag")
        if not raw_slug or not isinstance(raw_slug, str):
            errors.append(f"Item {idx}: missing or non-string 'tag'")
            continue

        slug = raw_slug.strip().lower()

        # Strict Canonical Vocabulary check
        if slug not in CANONICAL_VOCABULARY:
            errors.append(f"Item {idx}: tag '{slug}' is not in CANONICAL_VOCABULARY (discarded)")
            continue

        # Candidate containment check
        if candidate_tags and slug not in candidate_tags:
            errors.append(f"Item {idx}: tag '{slug}' was not in candidate set (discarded unprompted prediction)")
            continue

        # Confidence validation: float in [0.0, 1.0]
        confidence = item.get("confidence")
        if confidence is None or not isinstance(confidence, (int, float)):
            errors.append(f"Item {idx}: tag '{slug}' has missing or non-numeric confidence")
            continue

        conf_float = float(confidence)
        if conf_float < 0.0 or conf_float > 1.0:
            errors.append(f"Item {idx}: tag '{slug}' confidence {conf_float} outside [0.0, 1.0]")
            continue

        # Evidence validation
        evidence = str(item.get("evidence") or "").strip()
        if len(evidence) < 5:
            errors.append(f"Item {idx}: tag '{slug}' lacks substantial evidence explanation")
            continue

        # Deduplication: retain highest confidence if duplicate tag returned
        if slug in valid_tags_map:
            if conf_float > valid_tags_map[slug]["confidence"]:
                valid_tags_map[slug] = {
                    "slug": slug,
                    "confidence": round(conf_float, 4),
                    "evidence": evidence
                }
        else:
            valid_tags_map[slug] = {
                "slug": slug,
                "confidence": round(conf_float, 4),
                "evidence": evidence
            }

    valid_list = list(valid_tags_map.values())
    return valid_list, True, errors


def select_candidate_tags(
    record: Union[Dict[str, Any], Any],
    existing_rule_tags: Optional[List[Union[Dict[str, Any], InferredTag]]] = None,
    ml_predictions: Optional[List[Dict[str, Any]]] = None,
    explicit_candidates: Optional[List[str]] = None,
    max_candidates: int = 8
) -> List[str]:
    """
    Selects a controlled, relevant set of canonical candidate tags for LLM reasoning.
    
    Excludes:
    - Tags already inferred with high confidence by deterministic rules.
    - Tags already inferred with high confidence by calibrated ML.
    
    Includes:
    - ML predictions that were uncertain (medium tier or near-threshold).
    - Relevant complex/subtle narrative tropes.
    - Explicitly requested candidates.
    """
    if explicit_candidates is not None:
        # Caller provided an explicit candidate focus list
        return [s for s in explicit_candidates if s in CANONICAL_VOCABULARY][:max_candidates]

    # 1. Identify already confident tags that do not need LLM fallback
    confident_slugs: Set[str] = set()
    for t in (existing_rule_tags or []):
        slug = t.slug if isinstance(t, InferredTag) else t.get("slug")
        conf = t.confidence if isinstance(t, InferredTag) else t.get("confidence", 0.0)
        if slug and conf >= 0.75:
            confident_slugs.add(slug)

    for p in (ml_predictions or []):
        if p.get("accepted"):
            confident_slugs.add(p["slug"])

    # 2. Gather uncertain ML predictions (near threshold but not accepted)
    uncertain_candidates: Set[str] = set()
    for p in (ml_predictions or []):
        slug = p.get("slug")
        prob = p.get("confidence", 0.0)
        accepted = p.get("accepted", False)
        # If ML considered the label but it wasn't accepted
        if slug and slug not in confident_slugs and slug in CANONICAL_VOCABULARY:
            if not accepted and prob >= 0.40:
                uncertain_candidates.add(slug)

    # 3. Gather relevant complex tropes based on context hints (synopsis, titles, alternative titles)
    def _get_field(field_name: str) -> Any:
        if isinstance(record, dict):
            return record.get(field_name)
        return getattr(record, field_name, None)

    synopsis = str(_get_field("synopsis") or "")
    title_romaji = str(_get_field("title_romaji") or "")
    title_english = str(_get_field("title_english") or "")
    raw_alts = _get_field("alternative_titles") or []
    clean_alts = [str(a).strip() for a in raw_alts if a and str(a).strip()]
    context_corpus = f"{synopsis} {title_english} {title_romaji} {' '.join(clean_alts)}".lower()

    trope_candidates: Set[str] = set()
    for slug in COMPLEX_TROPE_CANDIDATES:
        if slug in confident_slugs or slug in uncertain_candidates:
            continue
        # Contextual heuristic trigger
        if slug in ("slow_burn", "friends_to_lovers", "enemies_to_lovers", "contract_marriage", "love_triangle", "fake_relationship"):
            if any(k in context_corpus for k in ("love", "romanc", "marry", "marriag", "feelings", "friend", "enem", "rival", "contract", "pretend", "fake")):
                trope_candidates.add(slug)
        elif slug == "reborn_as_a_villainess":
            if any(k in context_corpus for k in ("villainess", "otome", "noble", "reincarnat")):
                trope_candidates.add(slug)
        elif slug in ("survival", "dungeon_gate"):
            if any(k in context_corpus for k in ("hunter", "gate", "dungeon", "surviv", "monster", "apocalypse")):
                trope_candidates.add(slug)
        elif slug == "revenge":
            if any(k in context_corpus for k in ("revenge", "vengeance", "aveng", "betray")):
                trope_candidates.add(slug)
        elif slug == "time_travel":
            if any(k in context_corpus for k in ("time travel", "rewind", "timeline", "past years", "years ago")):
                trope_candidates.add(slug)

    # Combined candidate list, prioritized: subtle narrative tropes first (where LLM excels at nuance), then uncertain ML candidates
    combined = list(trope_candidates) + [s for s in uncertain_candidates if s not in trope_candidates]
    return combined[:max_candidates]


class LLMEnricher:
    """
    Controlled LLM Fallback Enricher using Groq / LLaMA.
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        accept_threshold: float = LLM_ACCEPT_THRESHOLD,
        review_threshold: float = LLM_REVIEW_THRESHOLD,
        max_calls_per_run: int = LLM_MAX_CALLS_PER_RUN,
        client: Optional[Any] = None,
        cache: Optional[LLMEnrichmentCache] = None,
        model: str = DEFAULT_LLM_MODEL,
        prompt_version: str = PROMPT_VERSION
    ):
        self.enabled = enabled if enabled is not None else LLM_ENRICHMENT_ENABLED
        self.accept_threshold = accept_threshold
        self.review_threshold = review_threshold
        self.max_calls_per_run = max_calls_per_run
        self.client = client
        self.cache = cache if cache is not None else LLMEnrichmentCache()
        self.model = model
        self.prompt_version = prompt_version

        self.call_count = 0
        self.total_accepted_tags = 0
        self.total_rejected_tags = 0
        self.total_abstentions = 0
        self.total_failures = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_latency_seconds = 0.0

    def _get_client(self) -> Optional[Any]:
        """Lazy-initializes or returns the Groq client."""
        if self.client is not None:
            return self.client
        from ..config import settings
        if settings.GROQ_API_KEY:
            try:
                from groq import AsyncGroq
                self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
            except Exception as e:
                logger.warning("Could not initialize AsyncGroq client: %s", e)
                self.client = None
        return self.client

    async def aenrich(
        self,
        record: Union[Dict[str, Any], Any],
        candidate_tags: Optional[List[str]] = None,
        rule_tags: Optional[List[Union[Dict[str, Any], InferredTag]]] = None,
        ml_predictions: Optional[List[Dict[str, Any]]] = None
    ) -> List[InferredTag]:
        """
        Asynchronously evaluates uncertain candidate tags using LLM reasoning.
        """
        if not self.enabled:
            return []

        if self.call_count >= self.max_calls_per_run:
            logger.warning("LLM enrichment circuit breaker reached max_calls_per_run (%d)", self.max_calls_per_run)
            return []

        # 1. Text & metadata extraction
        def _get(f: str) -> Any:
            if isinstance(record, dict):
                return record.get(f)
            return getattr(record, f, None)

        title_romaji = str(_get("title_romaji") or "")
        title_english = str(_get("title_english") or "")
        title_native = str(_get("title_native") or "")
        raw_alts = _get("alternative_titles") or []
        clean_alts = [str(a).strip() for a in raw_alts if a and str(a).strip()]
        raw_synopsis = str(_get("synopsis") or "")
        synopsis = clean_synopsis_text(raw_synopsis)

        # Narrative substance check:
        # Check combined narrative evidence (synopsis, titles, alternative titles).
        # If total narrative substance is < 50 chars, there is insufficient evidence to reason upon.
        narrative_corpus = " ".join([t for t in [synopsis, title_english, title_romaji] + clean_alts if t]).strip()
        if len(narrative_corpus) < 50:
            return []

        # 2. Candidate Tag Selection
        candidates = select_candidate_tags(
            record=record,
            existing_rule_tags=rule_tags,
            ml_predictions=ml_predictions,
            explicit_candidates=candidate_tags
        )
        if not candidates:
            # No tags require LLM fallback; skip completely
            return []

        candidate_set = set(candidates)

        # 3. Check Cache
        cache_key = compute_llm_cache_key(
            title_romaji=title_romaji,
            title_english=title_english,
            title_native=title_native,
            synopsis=synopsis,
            candidate_tags=candidates,
            prompt_version=self.prompt_version
        )
        cached_entry = self.cache.get(cache_key)
        if cached_entry:
            raw_response = cached_entry.get("response", {})
            cached_at = cached_entry.get("cached_at")
            valid_tags, is_valid, _ = validate_llm_result(raw_response, candidate_set)
            return self._build_inferred_tags(valid_tags, created_at=cached_at)

        # 4. Invoke LLM API
        client = self._get_client()
        if not client:
            logger.warning("LLM enrichment enabled but no Groq client/API key is configured.")
            return []

        alts_line = f"Alternative Titles: {', '.join(clean_alts[:5])}\n" if clean_alts else ""
        user_content = (
            f"Title: {title_english or title_romaji or 'Unknown'}\n"
            f"{alts_line}"
            f"Synopsis: {synopsis or 'None provided.'}\n\n"
            f"CANDIDATE TAGS TO EVALUATE:\n"
            + "\n".join(f"- {c}" for c in candidates)
        )

        import time
        t0 = time.perf_counter()
        try:
            self.call_count += 1
            chat_completion = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content}
                ],
                model=self.model,
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=12.0
            )
            self.total_latency_seconds += (time.perf_counter() - t0)
            if hasattr(chat_completion, "usage") and chat_completion.usage:
                self.total_prompt_tokens += getattr(chat_completion.usage, "prompt_tokens", 0) or 0
                self.total_completion_tokens += getattr(chat_completion.usage, "completion_tokens", 0) or 0

            raw_text = chat_completion.choices[0].message.content or "{}"
            raw_json = json.loads(raw_text)
        except Exception as e:
            self.total_failures += 1
            self.total_latency_seconds += (time.perf_counter() - t0)
            logger.warning("LLM API call failed: %s", e)
            return []

        # 5. Validate Structured Response
        valid_tags, is_valid, validation_errors = validate_llm_result(raw_json, candidate_set)

        # 6. Store in Cache (even if abstained or empty, to avoid re-calls)
        self.cache.set(
            cache_key=cache_key,
            data=raw_json,
            provider="groq",
            model=self.model,
            prompt_version=self.prompt_version,
            candidate_tags=candidates
        )

        if not is_valid:
            self.total_failures += 1
            return []

        if raw_json.get("abstain") is True or not valid_tags:
            self.total_abstentions += 1
            return []

        return self._build_inferred_tags(valid_tags)

    def _build_inferred_tags(
        self,
        valid_tags: List[Dict[str, Any]],
        created_at: Optional[str] = None
    ) -> List[InferredTag]:
        """Filters tags by accept_threshold and constructs InferredTag objects."""
        accepted: List[InferredTag] = []
        for t in valid_tags:
            conf = t["confidence"]
            slug = t["slug"]
            evidence = t.get("evidence")
            
            tag_threshold = get_llm_accept_threshold(slug, self.accept_threshold)

            if conf >= tag_threshold:
                self.total_accepted_tags += 1
                tag_obj = InferredTag.from_canonical(
                    slug=slug,
                    confidence=conf,
                    provenance="llm",
                    source_rule=f"LLM-{self.model}",
                    evidence=evidence
                )
                if created_at:
                    tag_obj.created_at = created_at
                accepted.append(tag_obj)
            else:
                self.total_rejected_tags += 1

        return accepted

    def enrich(
        self,
        record: Union[Dict[str, Any], Any],
        candidate_tags: Optional[List[str]] = None,
        rule_tags: Optional[List[Union[Dict[str, Any], InferredTag]]] = None,
        ml_predictions: Optional[List[Dict[str, Any]]] = None
    ) -> List[InferredTag]:
        """
        Synchronous wrapper for aenrich, safe for sync pipelines and testing.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Running inside existing event loop
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.aenrich(record, candidate_tags, rule_tags, ml_predictions)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self.aenrich(record, candidate_tags, rule_tags, ml_predictions)
                )
        except RuntimeError:
            return asyncio.run(
                self.aenrich(record, candidate_tags, rule_tags, ml_predictions)
            )
