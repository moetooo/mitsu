"""Category-weighted tag alignment for inference-aware ranking (ARCH-10).

Split out of `retrieval.py`. The ranking SQL in
`retrieval.retrieve_similar_manga` asks this module for two fragments - the
`tag_alignment` select expression and the term added to `hybrid_score` - and
both come from the same weights, so the score that is displayed and the score
that was ranked cannot drift apart.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from ..config import settings
from ..enrichment.vocabulary import CANONICAL_VOCABULARY


DEFAULT_CATEGORY_WEIGHTS: Dict[str, float] = {
    "relationship": 1.00,
    "trope": 1.00,
    "theme": 0.90,
    "setting": 0.80,
    "genre": 0.60,
    "demographic": 0.30,
    "format": 0.15,
}

def compute_category_aware_tag_alignment(
    query_tags: Optional[List[Dict[str, Any]]],
    candidate_tags: Optional[List[Dict[str, Any]]],
    category_weights: Optional[Dict[str, float]] = None
) -> float:
    """
    Computes normalized category-aware tag alignment between query tags and candidate tags.
    Formula:
        tag_alignment = weighted_shared_tags / weighted_query_tags
    Clamped to [0.0, 1.0].
    """
    if not query_tags or not candidate_tags:
        return 0.0

    weights = category_weights or DEFAULT_CATEGORY_WEIGHTS

    cand_slugs = {
        t.get("slug") for t in candidate_tags
        if isinstance(t, dict) and t.get("slug")
    }

    weighted_shared = 0.0
    weighted_query = 0.0

    seen_query_slugs = set()
    for t in query_tags:
        if not isinstance(t, dict):
            continue
        slug = t.get("slug")
        if not slug or slug in seen_query_slugs:
            continue
        seen_query_slugs.add(slug)

        cat = t.get("category")
        if not cat:
            tag_def = CANONICAL_VOCABULARY.get(slug)
            cat = tag_def.category.value if tag_def else "unknown"

        w = weights.get(cat, 0.50)
        weighted_query += w
        if slug in cand_slugs:
            weighted_shared += w

    if weighted_query <= 0.0:
        return 0.0

    alignment = weighted_shared / weighted_query
    return max(0.0, min(1.0, alignment))


def build_tag_alignment_sql(
    query_tags: Optional[List[Dict[str, Any]]],
    category_weights: Optional[Dict[str, float]] = None,
    tag_boost: Optional[float] = None
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Constructs SQL expressions and parameters for category-aware tag alignment.
    Returns:
        tag_select_clause: String to include in SELECT of ranked CTE
        tag_boost_score_expr: String to add to hybrid_score in scored CTE
        params: Dict of parameter bindings
    """
    weights = category_weights or DEFAULT_CATEGORY_WEIGHTS
    boost = tag_boost if tag_boost is not None else settings.INFERRED_TAG_BOOST

    if not query_tags:
        return "0.0 as tag_alignment,", "", {}

    params: Dict[str, Any] = {"tag_boost": float(boost)}
    weighted_query = 0.0
    case_terms = []

    seen_slugs = set()
    for idx, t in enumerate(query_tags):
        if not isinstance(t, dict):
            continue
        slug = t.get("slug")
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        cat = t.get("category")
        if not cat:
            tag_def = CANONICAL_VOCABULARY.get(slug)
            cat = tag_def.category.value if tag_def else "unknown"

        w = float(weights.get(cat, 0.50))
        weighted_query += w

        param_key = f"q_tag_{idx}"
        params[param_key] = json.dumps([{"slug": slug}])
        case_terms.append(
            f"(CASE WHEN inferred_tags IS NOT NULL AND inferred_tags @> CAST(:{param_key} AS jsonb) THEN {w} ELSE 0.0 END)"
        )

    if weighted_query <= 0.0 or not case_terms:
        return "0.0 as tag_alignment,", "", {}

    sum_terms = " + ".join(case_terms)
    tag_select = f"LEAST(1.0, GREATEST(0.0, ({sum_terms}) / {weighted_query})) as tag_alignment,"
    tag_score_add = " + (:tag_boost * tag_alignment)"

    return tag_select, tag_score_add, params
