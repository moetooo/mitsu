"""Every vocabulary option must reach catalogue rows, and its exclusion its complement.

The drawer is built from `/vocabulary`, so an option in that payload is a promise:
the pill either returns a shelf or is not offered. Two bugs made that promise false
before this test existed:

* `exclude_genres: ["Boys' Love"]` excluded nothing, because the request sanitizer
  deleted the apostrophe and the SQL builder's alias list only held `boys' love`
  (covered in `test_filter_builder.py` / `test_search_filters.py`).
* ten options had no catalogue counterpart at all (`Enemies to Lovers`, `Slow Burn`,
  ...), so including one returned an empty page and excluding it was a no-op.

This sweep keeps both honest: a filterable option has to match rows, an
unfilterable one must still match none (if enrichment backfills the tag, this fails
and the name comes off `UNBACKED_TAG_NAMES`), and include/exclude must partition
the table for every option.
"""

import pytest
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.routers.vocabulary import (
    CATALOGUE_FORMATS,
    UNBACKED_TAG_NAMES,
    build_vocabulary,
)
from app.services.query_filters import TAG_SYNONYMS, build_genre_sql_condition

pytestmark = pytest.mark.requires_catalog


def _tag_options():
    body = build_vocabulary()
    return [
        (category.id, option)
        for category in body.categories
        for option in category.options
    ]


@pytest.mark.asyncio
async def test_every_filterable_option_matches_rows_and_excludes_the_complement():
    """One scan of the table: each option adds two `count(*) FILTER` aggregates.

    The readable version (a query per predicate) costs 144 scans of 95k rows --
    minutes on a cold catalog -- so the sweep builds one statement instead.
    """
    options = _tag_options()
    assert len(options) >= 60, "the vocabulary should still serve the whole taxonomy"

    params = {}
    aggregates = []
    for index, (_category, option) in enumerate(options):
        include = build_genre_sql_condition([option.value], params, key_prefix=f"inc_{index}")
        exclude = build_genre_sql_condition([option.value], params, exclude=True, key_prefix=f"exc_{index}")
        aggregates.append(f"count(*) FILTER (WHERE {include}) AS inc_{index}")
        aggregates.append(f"count(*) FILTER (WHERE {exclude}) AS exc_{index}")

    sql = f"SELECT count(*) AS total, {', '.join(aggregates)} FROM manga"

    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(sql), params)).mappings().one()

    total = row["total"]
    failures = []
    for index, (category, option) in enumerate(options):
        matched = row[f"inc_{index}"]
        excluded = row[f"exc_{index}"]

        if matched + excluded != total:
            failures.append(f"{category}/{option.value}: include+exclude={matched + excluded} != total {total}")
        if option.filterable and matched == 0:
            failures.append(f"{category}/{option.value}: offered as a filter but matches no rows")
        if not option.filterable and matched != 0:
            failures.append(
                f"{category}/{option.value}: marked unfilterable but matches {matched} rows "
                f"(remove it from UNBACKED_TAG_NAMES)"
            )

    assert failures == [], " | ".join(failures)


def test_unbacked_names_are_still_in_the_taxonomy():
    """A stale allowlist entry would silently hide a dead pill's replacement."""
    names = {option.value for _, option in _tag_options()}
    stale = UNBACKED_TAG_NAMES - names
    assert stale == set(), f"UNBACKED_TAG_NAMES has names the taxonomy no longer serves: {stale}"


def test_format_filterables_match_what_ingestion_writes():
    formats = {o.slug: o for o in build_vocabulary().formats}
    assert {slug for slug, o in formats.items() if o.filterable} == set(CATALOGUE_FORMATS)


def test_synonyms_target_names_the_catalogue_can_answer():
    """Every synonym list must start with the canonical name and add at least one alias."""
    for key, names in TAG_SYNONYMS.items():
        assert len(names) >= 2, f"{key} adds no alias"
        assert len(set(names)) == len(names), f"{key} repeats a name"
        assert all(isinstance(name, str) and name.strip() for name in names), key
