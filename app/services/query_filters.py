"""SQL predicate builders for catalogue filters (ARCH-10).

Split out of `retrieval.py`, which had become six modules in one file. Nothing
here touches the database: each function turns a caller's filters into a SQL
fragment plus bind parameters, which is what keeps the statement text constant
across requests.

Every user value is bound. The `params=None` branch that pasted a genre into the
SQL string was deleted in Stage 6A (SVC-10), and `params` is a required argument
so it cannot come back.

Format predicates are imported from `services/format.py` rather than re-exported
from here: the column and its classifier live there (ARCH-05), so there is one
owner and no shim.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from ..models import RecommendFilters
from .format import build_format_sql_condition


def generate_filter_hash(filters: Optional[RecommendFilters]) -> str:
    """Generates a stable MD5 fingerprint hash for a filter set"""
    if not filters:
        return "default"
    filter_dict = filters.model_dump(exclude_none=True)
    filter_str = json.dumps(filter_dict, sort_keys=True)
    return hashlib.md5(filter_str.encode()).hexdigest()[:12]


def _tag_json_condition(tag_name: str, key: str, params: Dict[str, Any]) -> str:
    """JSONB containment on tags, always bound as a parameter.

    There used to be a `params is None` branch here that pasted the value into
    the SQL text and doubled its single quotes. No production caller ever took
    that path -- every one of them passes a parameter dict -- but leaving the
    branch in place meant the next caller could reach for it and hand a request
    value to a string concatenation (SVC-10). The parameter is now required.
    """
    params[key] = json.dumps([{"name": tag_name}])
    return "tags @> CAST(:" + key + " AS jsonb)"


def _array_contains_condition(value: str, key: str, params: Dict[str, Any]) -> str:
    """`genres @> ARRAY[...]` containment, always bound as a parameter."""
    params[key] = [value]
    return "genres @> CAST(:" + key + " AS text[])"


def build_genre_sql_condition(
    genres_list: Optional[List[str]],
    params: Dict[str, Any],
    exclude: bool = False,
    key_prefix: Optional[str] = None,
) -> Optional[str]:
    """Builds an exhaustive SQL condition across PostgreSQL text array genres and JSONB tags.

    Every user-provided genre is emitted as a bind parameter, so the statement
    text stays constant across requests and can be prepared and cached by
    PostgreSQL. `params` is required: the old inline-literal form is gone, so
    there is no way to reach this with an unbound request value (SVC-10).

    `key_prefix` defaults from `exclude`. Include and exclude lists need
    distinct bind names or the exclusion overwrites the inclusion in `params`
    and the two conditions cancel out, so deriving it here means a caller
    cannot forget.
    """
    if key_prefix is None:
        key_prefix = "exclude_genre" if exclude else "genre"
    if not genres_list:
        return None

    conditions: List[str] = []
    for idx, genre in enumerate(genres_list):
        if not isinstance(genre, str) or not genre.strip():
            continue
        low = genre.lower().strip()
        # Include and exclude lists need distinct bind names, otherwise the
        # exclusion overwrites the inclusion and the two conditions cancel out.
        key = key_prefix + "_" + str(idx)

        if low in ("yaoi", "bl", "boys' love"):
            conditions.append("(" + " OR ".join([
                _array_contains_condition("Boys' Love", key + "_arr", params),
                _tag_json_condition("Boys' Love", key + "_t1", params),
                _tag_json_condition("Yaoi", key + "_t2", params),
            ]) + ")")
        elif low in ("yuri", "gl", "girls' love"):
            conditions.append("(" + " OR ".join([
                _array_contains_condition("Girls' Love", key + "_arr", params),
                _tag_json_condition("Girls' Love", key + "_t1", params),
                _tag_json_condition("Yuri", key + "_t2", params),
            ]) + ")")
        elif low in ("shoujo ai", "shoujo-ai"):
            conditions.append("(" + " OR ".join([
                _tag_json_condition("Shoujo Ai", key + "_t1", params),
                _tag_json_condition("Girls' Love", key + "_t2", params),
                _tag_json_condition("Yuri", key + "_t3", params),
            ]) + ")")
        elif low in ("shounen ai", "shounen-ai"):
            conditions.append("(" + " OR ".join([
                _tag_json_condition("Shounen Ai", key + "_t1", params),
                _tag_json_condition("Boys' Love", key + "_t2", params),
                _tag_json_condition("Yaoi", key + "_t3", params),
            ]) + ")")
        elif low in ("shounen", "shoujo", "seinen", "josei", "harem", "reverse harem", "love triangle"):
            conditions.append(_tag_json_condition(genre, key + "_tag", params))
        else:
            conditions.append("(" + " OR ".join([
                _array_contains_condition(genre, key + "_arr", params),
                _tag_json_condition(genre, key + "_tag", params),
            ]) + ")")

    if not conditions:
        return None
    combined = " OR ".join(conditions)
    if exclude:
        return "NOT (" + combined + ")"
    return "(" + combined + ")"


def apply_filter_criteria(
    filters: Optional[RecommendFilters],
    where_clauses: List[str],
    params: Dict[str, Any]
) -> None:
    """Applies structured RecommendFilters criteria into parameterized WHERE clauses and bind params."""
    if not filters:
        return

    if filters.status:
        status_placeholders = []
        for idx, st_val in enumerate(filters.status):
            p_key = f"st_{idx}"
            params[p_key] = st_val
            status_placeholders.append(f":{p_key}")
        where_clauses.append(f"status IN ({', '.join(status_placeholders)})")

    if filters.min_year is not None:
        params["min_year"] = filters.min_year
        where_clauses.append("start_year >= :min_year")

    if filters.max_year is not None:
        params["max_year"] = filters.max_year
        where_clauses.append("start_year <= :max_year")

    if filters.min_score is not None:
        params["min_score"] = filters.min_score
        where_clauses.append("average_score >= :min_score")

    if filters.min_chapters is not None:
        params["min_chapters"] = filters.min_chapters
        where_clauses.append("chapters >= :min_chapters")

    if filters.max_chapters is not None:
        params["max_chapters"] = filters.max_chapters
        where_clauses.append("chapters <= :max_chapters")

    if filters.genres:
        cond = build_genre_sql_condition(filters.genres, params)
        if cond:
            where_clauses.append(cond)

    if filters.exclude_genres:
        # `key_prefix` is derived from `exclude`, so the two lists cannot
        # overwrite each other's bind parameters.
        cond = build_genre_sql_condition(filters.exclude_genres, params, exclude=True)
        if cond:
            where_clauses.append(cond)

    if filters.format_type:
        raw_fmts = filters.format_type if isinstance(filters.format_type, list) else [filters.format_type]
        fmt_cond = build_format_sql_condition(raw_fmts)
        if fmt_cond:
            where_clauses.append(fmt_cond)
