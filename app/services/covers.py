"""Backwards-compatible import site for the cover rules.

The implementation lives in `app.core.covers`: `app.models` needs the same
sanitisation, and a `models -> services` import created a package-level cycle
(`tests/test_layering.py`). Everything below is re-exported unchanged, so
`from app.services.covers import ...` keeps working for ingestion and routers.
"""

from ..core.covers import (  # noqa: F401
    BLOCKED_HOSTS,
    COVER_COLUMNS,
    KNOWN_SOURCES,
    BROWSER_SAFE_HOSTS,
    MAX_CANDIDATES,
    SOURCE_RANK,
    allowed_hosts,
    apply_cover_fields,
    blocked_hosts,
    candidates_for,
    classify_cover,
    cover_fields,
    cover_rank,
    cover_source_for,
    host_of,
    is_blocked,
    is_browser_safe,
    make_candidate,
    max_candidates,
    merge_candidates,
    normalise_candidates,
    primary_url,
    public_cover,
    source_order,
    source_rank,
    validate_cover_config,
)

__all__ = [
    "BLOCKED_HOSTS",
    "COVER_COLUMNS",
    "KNOWN_SOURCES",
    "BROWSER_SAFE_HOSTS",
    "MAX_CANDIDATES",
    "SOURCE_RANK",
    "allowed_hosts",
    "apply_cover_fields",
    "blocked_hosts",
    "candidates_for",
    "classify_cover",
    "cover_fields",
    "cover_rank",
    "cover_source_for",
    "host_of",
    "is_blocked",
    "is_browser_safe",
    "make_candidate",
    "max_candidates",
    "merge_candidates",
    "normalise_candidates",
    "primary_url",
    "public_cover",
    "source_order",
    "source_rank",
    "validate_cover_config",
]
