"""
Data models for enriched and inferred metadata.

Provides structured representation for inferred tags with confidence, provenance,
and auditing metadata, along with safe conflict-free merging.
"""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator
from .vocabulary import TagCategory, get_tag_by_slug

ALLOWED_PROVENANCES = {"external", "rule", "model", "llm", "human"}

# Provenance reliability hierarchy (higher value takes priority on conflict)
PROVENANCE_PRIORITY = {
    "human": 5,
    "external": 4,
    "rule": 3,
    "model": 2,
    "llm": 1
}

class InferredTag(BaseModel):
    """Structured representation of an enriched/inferred tag."""
    slug: str
    name: str
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: str = Field(description="Origin source of tag: external, rule, model, llm, human")
    source_rule: Optional[str] = None
    evidence: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("provenance")
    @classmethod
    def validate_provenance(cls, v: str) -> str:
        low = v.lower().strip()
        if low not in ALLOWED_PROVENANCES:
            raise ValueError(f"Invalid provenance '{v}'. Must be one of {sorted(ALLOWED_PROVENANCES)}")
        return low

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        low = v.lower().strip()
        valid_cats = {c.value for c in TagCategory}
        if low not in valid_cats:
            raise ValueError(f"Invalid category '{v}'. Must be one of {sorted(valid_cats)}")
        return low

    @classmethod
    def from_canonical(
        cls,
        slug: str,
        confidence: float,
        provenance: str,
        source_rule: Optional[str] = None,
        evidence: Optional[str] = None
    ) -> "InferredTag":
        """Factory constructor ensuring canonical tag existence."""
        tag = get_tag_by_slug(slug)
        if not tag:
            raise ValueError(f"Unknown canonical tag slug: '{slug}'")
        return cls(
            slug=tag.slug,
            name=tag.name,
            category=tag.category.value,
            confidence=round(confidence, 4),
            provenance=provenance,
            source_rule=source_rule,
            evidence=evidence
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes to a clean JSON-storable dictionary."""
        d = {
            "slug": self.slug,
            "name": self.name,
            "category": self.category,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "created_at": self.created_at
        }
        if self.source_rule:
            d["source_rule"] = self.source_rule
        if self.evidence:
            d["evidence"] = self.evidence
        return d


def merge_inferred_tags(
    existing_tags: Optional[List[Dict[str, Any]]],
    incoming_tags: Optional[Union[List[Dict[str, Any]], List[InferredTag]]]
) -> List[Dict[str, Any]]:
    """
    Safely merges new inferred tags into existing inferred tags.
    
    Rules:
    1. Tags are uniquely keyed by canonical `slug`.
    2. If a tag already exists:
       - Higher priority provenance always replaces lower priority provenance.
       - If provenance priority is equal, the tag with higher confidence is retained.
    3. Guarantees deterministic list ordered by category then name.
    """
    merged: Dict[str, Dict[str, Any]] = {}

    # Process existing tags
    for tag in (existing_tags or []):
        if not isinstance(tag, dict):
            continue
        slug = tag.get("slug")
        if slug:
            merged[slug] = dict(tag)

    # Process incoming tags
    for item in (incoming_tags or []):
        tag_dict = item.to_dict() if isinstance(item, InferredTag) else dict(item)
        slug = tag_dict.get("slug")
        if not slug:
            continue

        if slug not in merged:
            merged[slug] = tag_dict
        else:
            curr = merged[slug]
            curr_prov_prio = PROVENANCE_PRIORITY.get(curr.get("provenance", "rule"), 0)
            new_prov_prio = PROVENANCE_PRIORITY.get(tag_dict.get("provenance", "rule"), 0)

            if new_prov_prio > curr_prov_prio:
                merged[slug] = tag_dict
            elif new_prov_prio == curr_prov_prio:
                # Same provenance level: compare confidence
                if tag_dict.get("confidence", 0.0) >= curr.get("confidence", 0.0):
                    merged[slug] = tag_dict

    # Return sorted list for stable ordering
    return sorted(merged.values(), key=lambda t: (t.get("category", ""), t.get("name", "")))
