"""Input normalisation for user-supplied text -- **not** a security boundary (API-18).

Every SQL fragment in this codebase is built with bound parameters since Stages
6A/6B (`services/catalog.py`, `services/query_filters.py`), and the `LIKE`
metacharacters are escaped at the pattern (`catalog.escape_like`). A query string is
never spliced into a statement, so deleting SQL-looking substrings here protected
nothing -- and it removed text that is part of real titles.

Measured on the live catalogue before the removal: of the 76 titles containing
`;`, `--`, or the words `drop`/`delete`/`truncate`, **73 were altered before the
search ever saw them** (`Occultic;Nine` -> `OcculticNine`, `STEINS;GATE DROPS` ->
`STEINSGATE DROPS`), and a query of exactly `Drop` became the empty string, so the
endpoint answered nothing at all.

What remains is what a search box genuinely needs: a length cap (a 100 KB query is
a cheap denial of service) and removal of control characters/NUL bytes.
"""

import re
from typing import List, Optional, Any
from ..models import RecommendFilters

# Matches non-printable control characters and NULL bytes
CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def sanitize_search_query(query: Optional[str], max_length: int = 300) -> str:
    """
    Normalises a search query: length cap plus control-character removal.

    It deliberately does **not** try to detect SQL. That is the job of bound
    parameters, and a text filter can only produce false positives (API-18).
    """
    if not query:
        return ""

    # 1. Trim whitespace and restrict maximum query string length
    cleaned = query.strip()[:max_length]

    # 2. Strip NULL bytes and non-printable control characters
    cleaned = CONTROL_CHARS_RE.sub('', cleaned)

    return cleaned.strip()


def sanitize_string_list(items: Optional[List[str]]) -> Optional[List[str]]:
    r"""Normalises a list of filter values: control characters out, length capped.

    It used to run `re.sub(r"[^\w\s\-\+\#]", "", item)`, which deleted the
    apostrophe out of every tag name. That turned the catalogue's `Boys' Love`
    and `Girls' Love` into `Boys Love` / `Girls Love` **before** the SQL builder
    saw them, so the tag aliases no longer matched, the generic branch looked for
    a tag that does not exist, and excluding Boys' Love filtered nothing at all
    (including it silently returned zero rows).

    Nothing is spliced into SQL -- every genre/status/format value is a bound
    parameter (`services/query_filters.py`, `services/format.py`) -- so this is
    the same correction as `sanitize_search_query` (API-18): keep the real text,
    drop only what a database cannot store.
    """
    if not items:
        return None

    sanitized = []
    for item in items:
        if not isinstance(item, str):
            continue
        clean_item = CONTROL_CHARS_RE.sub('', item).strip()
        if clean_item:
            sanitized.append(clean_item[:50])

    return sanitized if sanitized else None


def sanitize_recommend_filters(filters: Optional[RecommendFilters]) -> Optional[RecommendFilters]:
    """
    Sanitizes filter fields inside RecommendFilters payload.
    """
    if not filters:
        return None

    if filters.status:
        filters.status = sanitize_string_list(filters.status)
    if filters.genres:
        filters.genres = sanitize_string_list(filters.genres)
    if filters.exclude_genres:
        filters.exclude_genres = sanitize_string_list(filters.exclude_genres)

    if filters.format_type:
        if isinstance(filters.format_type, list):
            filters.format_type = sanitize_string_list(filters.format_type)
        elif isinstance(filters.format_type, str):
            clean_fmt = re.sub(r"[^\w\s\-]", "", filters.format_type).strip()
            filters.format_type = clean_fmt if clean_fmt else None

    return filters
