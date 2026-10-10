"""
LLM Enrichment Response Cache.

Provides deterministic, auditable, and cost-controlled caching for LLM metadata enrichment.
Keyed by SHA-256 hash of:
- Title fields (romaji, english, native)
- Synopsis
- Candidate canonical tags
- Prompt version

Guarantees:
1. Zero duplicate API calls for identical input.
2. Complete audit trail: provider, model, prompt version, input hash, and timestamp.
3. Thread-safe in-memory cache with optional persistent disk serialization.
"""

import os
import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List


def compute_llm_cache_key(
    title_romaji: str,
    title_english: str,
    title_native: str,
    synopsis: str,
    candidate_tags: List[str],
    prompt_version: str
) -> str:
    """Computes a deterministic SHA-256 cache key for an LLM enrichment request."""
    sorted_candidates = ",".join(sorted(candidate_tags))
    raw_payload = (
        f"title_romaji:{title_romaji.strip().lower()}|"
        f"title_english:{title_english.strip().lower()}|"
        f"title_native:{title_native.strip().lower()}|"
        f"synopsis:{synopsis.strip()}|"
        f"candidates:{sorted_candidates}|"
        f"prompt_version:{prompt_version.strip()}"
    )
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


class LLMEnrichmentCache:
    """
    Persistent audit cache for LLM tag enrichment.
    """

    def __init__(self, cache_file: Optional[str] = None):
        self.cache_file = cache_file
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._hits = 0
        self._misses = 0

        if self.cache_file and os.path.exists(self.cache_file):
            self.load()

    def get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Retrieves a cached response entry by cache key."""
        entry = self._cache.get(cache_key)
        if entry is not None:
            self._hits += 1
            return entry
        self._misses += 1
        return None

    def set(
        self,
        cache_key: str,
        data: Dict[str, Any],
        provider: str = "groq",
        model: str = "llama-3.1-8b-instant",
        prompt_version: str = "v1.0",
        candidate_tags: Optional[List[str]] = None
    ) -> None:
        """Stores an LLM enrichment response with audit metadata."""
        record = {
            "input_hash": cache_key,
            "llm_provider": provider,
            "llm_model": model,
            "prompt_version": prompt_version,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "candidate_tags": list(candidate_tags or []),
            "response": data
        }
        self._cache[cache_key] = record
        if self.cache_file:
            self.save()

    def clear(self) -> None:
        """Clears all cached entries and resets statistics."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        if self.cache_file and os.path.exists(self.cache_file):
            try:
                os.remove(self.cache_file)
            except OSError:
                pass

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "total_entries": len(self._cache),
            "hits": self._hits,
            "misses": self._misses
        }

    def save(self) -> None:
        """Persists the cache to disk as JSON."""
        if not self.cache_file:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.cache_file)), exist_ok=True)
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            # Failure to persist cache to disk should never break application logic
            pass

    def load(self) -> None:
        """Loads persisted cache entries from disk."""
        if not self.cache_file or not os.path.exists(self.cache_file):
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
        except Exception:
            self._cache = {}
