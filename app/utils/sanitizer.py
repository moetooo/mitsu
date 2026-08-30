import re
from typing import List, Optional, Any
from ..models import RecommendFilters

# Matches non-printable control characters and NULL bytes
CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
# Matches SQL comment injection attempts and statement separators
SQL_INJECTION_RE = re.compile(r'(--|/\*|\*/|;|exec\s+|\bdrop\b|\bdelete\b|\btruncate\b)', re.IGNORECASE)

def sanitize_search_query(query: Optional[str], max_length: int = 300) -> str:
    """
    Sanitizes search query input strings against SQL/Vector injection, ReDoS vectors,
    and invalid control characters.
    """
    if not query:
        return ""

    # 1. Trim whitespace and restrict maximum query string length
    cleaned = query.strip()[:max_length]

    # 2. Strip NULL bytes and non-printable control characters
    cleaned = CONTROL_CHARS_RE.sub('', cleaned)

    # 3. Sanitize potential SQL injection comment/statement breakout markers
    cleaned = SQL_INJECTION_RE.sub('', cleaned)

    return cleaned.strip()


def sanitize_string_list(items: Optional[List[str]]) -> Optional[List[str]]:
    """
    Sanitizes string lists (genres, statuses) to allow only safe alphanumeric, 
    space, and hyphen characters, preventing SQL array injection.
    """
    if not items:
        return None

    sanitized = []
    for item in items:
        if not isinstance(item, str):
            continue
        # Remove non-alphanumeric/space/hyphen characters and single quotes
        clean_item = re.sub(r"[^\w\s\-\+\#]", "", item).strip()
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
