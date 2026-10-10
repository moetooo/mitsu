"""
Feature Construction and Ground-Truth Extraction for Local ML Tag Classification.

Enforces:
1. Consistent text representation for training and inference via build_ml_text().
2. Label leakage prevention: input text is derived strictly from Title, Alternative Titles,
   and Synopsis, without injecting raw tag strings that trivialise classification.
3. Canonical label extraction: ground-truth labels are mapped solely through
   resolve_canonical_tag() to eliminate unknown or non-canonical classes.
"""

import re
from typing import Dict, Any, List, Set, Union, Optional
from .synonyms import resolve_canonical_tag
from .vocabulary import CANONICAL_VOCABULARY

SOURCE_BOILERPLATE_RE = re.compile(
    r"\s*(?:\([Ss]ource:[^)]*\)|\[[Ss]ource:[^\]]*\]|\([Ww]ritten by[^)]*\)|\[[Ww]ritten by[^\]]*\]|(?:\b[Ss]ource:\s*[^\n]+$))",
    re.MULTILINE
)

def clean_synopsis_text(synopsis: Optional[str]) -> str:
    """Strips metadata citation boilerplate and source distributor watermarks from synopsis."""
    if not synopsis:
        return ""
    return SOURCE_BOILERPLATE_RE.sub("", synopsis).strip()

def build_ml_text(record: Union[Dict[str, Any], Any], include_metadata: bool = False) -> str:
    """
    Constructs a structured, standardized text representation of a manga record.
    Used identically during training and inference.
    
    Args:
        record: Manga dict or SQLAlchemy model instance.
        include_metadata: If False (default), excludes raw genres and tags to prevent
                          label leakage during training and force textual comprehension.
                          If True, includes genres and tags as secondary metadata.
                          
    Returns:
        Clean textual representation suitable for TF-IDF vectorization.
    """
    def _get(field_name: str) -> Any:
        if isinstance(record, dict):
            return record.get(field_name)
        return getattr(record, field_name, None)

    # 1. Title fields
    title_romaji = str(_get("title_romaji") or "").strip()
    title_english = str(_get("title_english") or "").strip()
    title_native = str(_get("title_native") or "").strip()
    
    raw_alts = _get("alternative_titles") or []
    clean_alts = [str(a).strip() for a in raw_alts if a and str(a).strip()]

    title_parts = [t for t in [title_romaji, title_english, title_native] if t]
    if clean_alts:
        title_parts.extend(clean_alts[:5])  # Cap at top 5 aliases to prevent dilution
    title_line = " ".join(title_parts)

    # 2. Synopsis (clean source/distributor watermarks like '(Source: Renta!)' that introduce label leakage)
    raw_synopsis = str(_get("synopsis") or "").strip()
    synopsis = clean_synopsis_text(raw_synopsis)

    # 3. Optional metadata (when explicitly requested)
    metadata_parts = []
    if include_metadata:
        genres = _get("genres") or []
        clean_genres = [str(g).strip() for g in genres if g and str(g).strip()]
        if clean_genres:
            metadata_parts.append(f"Genres: {', '.join(clean_genres)}")
            
        tags = _get("tags") or []
        tag_names = []
        for t in tags:
            if isinstance(t, dict) and t.get("name"):
                tag_names.append(str(t["name"]).strip())
            elif isinstance(t, str) and t.strip():
                tag_names.append(t.strip())
        if tag_names:
            metadata_parts.append(f"Tags: {', '.join(tag_names[:10])}")

    # Build coherent multi-line document
    doc_sections = []
    if title_line:
        doc_sections.append(f"Title: {title_line}")
    if metadata_parts:
        doc_sections.extend(metadata_parts)
    if synopsis:
        doc_sections.append(f"Synopsis: {synopsis}")

    return "\n".join(doc_sections).strip()


def extract_canonical_labels(record: Union[Dict[str, Any], Any]) -> List[str]:
    """
    Extracts ground-truth canonical tag slugs from a manga's raw genres and tags.
    
    Guarantees:
    - Every returned slug exists in CANONICAL_VOCABULARY.
    - Unknown or unmapped raw tags are safely ignored and never become labels.
    - Result is sorted and deduplicated.
    """
    def _get(field_name: str) -> Any:
        if isinstance(record, dict):
            return record.get(field_name)
        return getattr(record, field_name, None)

    canonical_slugs: Set[str] = set()

    # Extract from raw genres
    genres = _get("genres") or []
    for g in genres:
        if g:
            canon = resolve_canonical_tag(str(g))
            if canon and canon.slug in CANONICAL_VOCABULARY:
                canonical_slugs.add(canon.slug)

    # Extract from raw tags
    tags = _get("tags") or []
    for t in tags:
        name = None
        if isinstance(t, dict):
            name = t.get("name")
        elif isinstance(t, str):
            name = t
        if name:
            canon = resolve_canonical_tag(str(name))
            if canon and canon.slug in CANONICAL_VOCABULARY:
                canonical_slugs.add(canon.slug)

    return sorted(list(canonical_slugs))
