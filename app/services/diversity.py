"""Page-level diversity for the roulette draw (ARCH-10).

Split out of `retrieval.py`. Two rules, both cheap and structural rather than
tuned to a particular catalogue:

* `franchise_key` collapses volume/season entries of one series into one key, so
  a single franchise cannot fill a page.
* `apply_diversity_filtering` honours `exclude_ids` absolutely (it used to undo
  it whenever everything was excluded) and spreads the page across genres.

Nothing here reads the database; it operates on rows the sampler already fetched.
"""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Set

from .format import infer_format_type
from .covers import public_cover


# Trailing markers that distinguish a volume/season entry from the series itself.
_VOLUME_MARKER = re.compile(
    r"\s*[\u2013\u2014-]?\s*(?:vol(?:ume)?\.?|book|part|season|season\s+\d+|"
    r"chapter|ch\.|#)\s*\d+\s*$",
    re.IGNORECASE,
)


def franchise_key(title: Optional[str], row_id: Any = None) -> str:
    """A normalized key used to keep one series from filling a whole page.

    This replaces `title.lower()[:15]`. The blind 15-character cut merged
    genuinely different series -- "Berserk" with "Berserk of Gluttony" -- and in
    this catalogue 81 different Gundam titles share one 15-character prefix, as
    do 79 villainess titles.

    The key is deliberately conservative: the whole normalized title, with a
    trailing volume/season/chapter marker removed. Two differently-named entries
    are therefore never merged, which is the failure mode that loses titles from
    a page. Merging a sequel into its parent is a nice-to-have and needs a real
    series identifier, not a title heuristic.
    """
    if not title or not str(title).strip():
        return f"id:{row_id}"

    text_value = str(title).strip().lower()
    # Unify the separators that catalogues use interchangeably.
    text_value = re.sub(r"[_/\\|~]", ":", text_value)
    text_value = re.sub(r"\s+", " ", text_value)
    # Drop a trailing volume/season marker, then any now-trailing punctuation.
    text_value = _VOLUME_MARKER.sub("", text_value)
    text_value = text_value.strip(" -\u2013\u2014:.,")
    return text_value or f"id:{row_id}"


def apply_diversity_filtering(rows: List[Any], exclude_ids: Set[int], max_target: int = 50) -> List[Dict[str, Any]]:
    """Applies lightweight rule-based diversity (genres, format, score bands, hidden gems)

    `exclude_ids` is honoured absolutely. It used to be undone: when every row was
    excluded the function restored the full unfiltered list, so marking a title as
    already-seen had no effect at exactly the moment it mattered. Relaxing the
    seen set is a product decision and belongs to the caller, which already does
    it explicitly for Discovery Roulette.
    """
    if not rows:
        return []

    # 1. Drop already-seen rows, then collapse repeats of the same series.
    seen_titles: Set[str] = set()
    filtered_rows = []

    for r in rows:
        if r.id in exclude_ids:
            continue
        stem = franchise_key(r.title_english or r.title_romaji or r.title_native, r.id)
        if stem in seen_titles:
            continue
        seen_titles.add(stem)
        filtered_rows.append(r)

    if not filtered_rows:
        # Nothing survived: either every candidate was already seen, or the page is
        # a single series. Returning the unfiltered rows here is what made
        # `exclude_ids` a no-op; the caller decides whether to relax it.
        return []

    # 2. Separate into High Confidence vs. Hidden Gems
    high_confidence = []
    hidden_gems = []

    for r in filtered_rows:
        score = r.average_score or 75
        pop = r.popularity or 10000
        # Hidden gem: solid score >= 75 but lower popularity / higher pop rank number
        if score >= 75 and pop > 8000:
            hidden_gems.append(r)
        else:
            high_confidence.append(r)

    random.shuffle(high_confidence)
    random.shuffle(hidden_gems)

    # 3. Target ratio: 80% High Confidence, 20% Hidden Gems
    target_gems_count = int(max_target * 0.20)
    selected_gems = hidden_gems[:target_gems_count]
    selected_conf = high_confidence[: max_target - len(selected_gems)]
    candidate_pool = selected_conf + selected_gems

    # 4. Enforce Genre Spread (Max 30% per genre)
    genre_counts: Dict[str, int] = {}
    diverse_selection = []
    max_per_genre = max(3, int(max_target * 0.30))

    for r in candidate_pool:
        primary_genre = r.genres[0] if (r.genres and len(r.genres) > 0) else "General"
        curr_count = genre_counts.get(primary_genre, 0)

        if curr_count < max_per_genre or len(diverse_selection) < 10:
            genre_counts[primary_genre] = curr_count + 1
            diverse_selection.append(r)

        if len(diverse_selection) >= max_target:
            break

    # If still below target, fill remaining with skipped rows
    if len(diverse_selection) < max_target:
        for r in candidate_pool:
            if r not in diverse_selection:
                diverse_selection.append(r)
            if len(diverse_selection) >= max_target:
                break

    random.shuffle(diverse_selection)

    # Format result dicts
    out = []
    for r in diverse_selection:
        title = r.title_english or r.title_romaji or r.title_native or "Unknown Title"
        fmt = getattr(r, "format_type", None) or infer_format_type(
            r.title_native, r.tags, r.genres, r.site_url
        )
        # No similarity is computed for roulette, so no similarity_score is
        # reported. The previous value was `average_score / 100` with a default
        # of 85 -- a community score presented as a match percentage, so an
        # unrated title claimed an 85% "match". `average_score` is already its
        # own field below.
        cover_url, cover_list = public_cover(r.cover_image_url, getattr(r, "cover_candidates", None))
        out.append({
            "id": r.id,
            "anilist_id": r.anilist_id,
            "mal_id": r.mal_id,
            "title": title,
            "cover_image_url": cover_url,
            "cover_candidates": cover_list,
            "banner_image": r.banner_image,
            "synopsis": r.synopsis,
            "genres": r.genres,
            "tags": r.tags,
            "status": r.status,
            "start_year": r.start_year,
            "chapters": r.chapters,
            "volumes": r.volumes,
            "average_score": r.average_score,
            "similarity_score": None,
            "llm_reasoning": "Discovery Roulette candidate.",
            "format_type": fmt
        })

    return out
