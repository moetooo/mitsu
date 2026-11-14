"""Publication format: one definition, stored instead of recomputed (ARCH-05).

There used to be two implementations of the same idea, and they disagreed:

* `infer_format_type(...)` in Python, used for result payloads, and
* `build_format_sql_condition(...)`, a ~120-line SQL predicate that re-derived
  "is this a manhwa?" from `title_native` character ranges, JSON tag containment,
  `site_url` substrings and `inferred_tags` on every filtered query.

The classification is now stored on `manga.format_type` and every reader uses the
column: filtering is a plain `format_type IN (...)`, and the Python rule below is
the single definition, applied when a row is written and when it is backfilled
(`migrations/versions/0005_format_type.py` mirrors it in SQL).
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional

HANGUL_RE = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
HANZI_RE = re.compile(r"[\u4e00-\u9fff]")

MANGA = "MANGA"
MANHWA = "MANHWA"
MANHUA = "MANHUA"

#: Values the column can hold. Anything else is rejected rather than stored.
FORMAT_TYPES = (MANGA, MANHWA, MANHUA)

#: UI filter value -> column values. `manga` means "neither manhwa nor manhua",
#: which is exactly what the old SQL predicate expressed by hand.
FILTER_VALUES = {
    "manga": (MANGA,),
    "manhwa": (MANHWA,),
    "manhua": (MANHUA,),
}


def infer_format_type(
    title_native: Optional[str] = None,
    tags: Any = None,
    genres: Optional[List[str]] = None,
    site_url: Optional[str] = None,
    inferred_tags: Any = None,
) -> str:
    """Classify a title as MANGA, MANHWA or MANHUA from the metadata we have.

    Precedence, highest first: an explicit inferred tag, Korean markers, Chinese
    markers, then MANGA as the default. It never returns None: a row that gives
    no evidence is Japanese manga, which is what the catalog is mostly made of.
    """
    if inferred_tags and isinstance(inferred_tags, list):
        inferred_slugs = {t.get("slug") for t in inferred_tags if isinstance(t, dict)}
        if "manhwa" in inferred_slugs:
            return MANHWA
        if "manhua" in inferred_slugs:
            return MANHUA
        if "manga" in inferred_slugs:
            return MANGA

    tags_str = str(tags) if tags else ""
    genres_list = genres or []
    site_str = (site_url or "").lower()
    has_kana = bool(title_native and KANA_RE.search(title_native))
    has_hangul = bool(title_native and HANGUL_RE.search(title_native))
    has_hanzi = bool(title_native and HANZI_RE.search(title_native))

    if (
        has_hangul
        or "Manhwa" in genres_list
        or "Manhwa" in tags_str
        or "Webtoon" in tags_str
        or "Korean" in tags_str
        or "manhwa" in site_str
    ):
        return MANHWA

    if (
        "Manhua" in genres_list
        or "Manhua" in tags_str
        or "Chinese" in tags_str
        or "Ancient China" in tags_str
        or "manhua" in site_str
        or (
            has_hanzi
            and not has_kana
            and not has_hangul
            and ("Long Strip" in tags_str or "Full Color" in tags_str)
        )
    ):
        return MANHUA

    return MANGA


def format_type_for_row(row: Any) -> str:
    """`infer_format_type` for a Manga row or record with the same field names."""
    return infer_format_type(
        getattr(row, "title_native", None),
        getattr(row, "tags", None),
        getattr(row, "genres", None),
        getattr(row, "site_url", None),
        getattr(row, "inferred_tags", None),
    )


def filter_values(raw_fmts: Iterable[str] | None) -> List[str]:
    """UI filter values -> column values, order preserved, unknowns ignored."""
    if not raw_fmts:
        return []
    if isinstance(raw_fmts, str):
        raw_fmts = [raw_fmts]
    values: List[str] = []
    for raw in raw_fmts:
        if not isinstance(raw, str):
            continue
        for value in FILTER_VALUES.get(raw.strip().lower(), ()):
            if value not in values:
                values.append(value)
    return values


def build_format_sql_condition(raw_fmts: Iterable[str] | None) -> Optional[str]:
    """SQL condition over the stored column.

    Values come from `FILTER_VALUES`, so the interpolated list is a closed
    allowlist rather than user input.
    """
    values = filter_values(raw_fmts)
    if not values:
        return None
    if len(values) == 1:
        return f"(format_type = '{values[0]}')"
    joined = ", ".join(f"'{value}'" for value in values)
    return f"(format_type IN ({joined}))"
